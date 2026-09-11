"""FastAPI service: the only bridge between the SQLite-backed quant engine and
the Next.js frontend (PROJECT_SPEC.md §8, §29).

The frontend NEVER talks to data providers directly — every request flows
through here. Credentials are read server-side only and never serialized into
any response.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .config import DCF_MODEL_VERSION, config, missing_credentials
from .db import connect, today, utcnow
from .errors import (
    CalculationError,
    InvalidAssumptionError,
    MissingDataError,
    ProviderError,
    QuantError,
)
from .errors import (
    ValidationError as QuantValidationError,
)
from .ingestion.service import IngestionService
from .ingestion.validator import validate_ticker
from .portfolio import analytics as P
from .portfolio.optimizer import covariance_from_prices, optimize
from .quant.metrics import max_drawdown_positive
from .quant.model import build_metric_inputs, run_factor_model
from .research import journal
from .simulation.monte_carlo import run_monte_carlo
from .simulation.regime import classify_regime
from .valuation.dcf import DCFAssumptions, run_dcf, sensitivity_table

app = FastAPI(
    title="In-Depth Quant Stock Analyzer API",
    version="0.1.0",
    description="Quantitative research platform backend (Wharton competition project).",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

_INGEST = IngestionService()


# ----------------------------------------------------------------- helpers
def _err(status: int, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail=detail)


@app.exception_handler(QuantError)
def _quant_error_handler(request, exc: QuantError):
    status = {
        ProviderError: 502,
        MissingDataError: 404,
        QuantValidationError: 400,
        CalculationError: 422,
        InvalidAssumptionError: 422,
    }.get(type(exc), 500)
    return HTTPException(status_code=status, detail=str(exc))


def _prices_frame(conn, ticker: str) -> pd.Series:
    rows = conn.execute(
        "SELECT date, adj_close, close FROM prices WHERE ticker = ? ORDER BY date",
        (ticker,),
    ).fetchall()
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series(
        {r["date"]: (r["adj_close"] if r["adj_close"] is not None else r["close"])
         for r in rows},
        dtype=float,
    )
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def _ensure_data(ticker: str, force: bool = False) -> dict:
    """Ingest if the ticker has no recent data; returns the ingest report."""
    with connect() as conn:
        row = conn.execute(
            "SELECT retrieved_at FROM prices WHERE ticker = ? ORDER BY date DESC"
            " LIMIT 1", (ticker,),
        ).fetchone()
    if force or row is None:
        return _INGEST.ingest_ticker(ticker)
    return {"ticker": ticker, "skipped": True,
            "reason": f"cached data through {row['retrieved_at']}"}


def _load_series(ticker: str) -> pd.Series:
    with connect() as conn:
        return _prices_frame(conn, ticker)


def _statement_items(conn, ticker: str, statement: str, period: str = "annual"):
    from .ingestion import repository as repo
    return repo.read_statements(conn, ticker, statement, period)


# ------------------------------------------------------------------- meta
@app.get("/api/health")
def health():
    with connect() as conn:
        counts = {}
        for table in ("companies", "prices", "financial_statements",
                      "fundamentals", "model_runs", "research_decisions"):
            counts[table] = conn.execute(
                f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]
    return {
        "status": "ok", "time": utcnow(),
        "db": config.DB_PATH.split("data")[-1],
        "row_counts": counts,
        "credentials_missing": missing_credentials(),
    }


@app.get("/api/coverage")
def coverage(ticker: str = Query(...)):
    """What data do we have for a ticker? (transparency / debugging)"""
    t = validate_ticker(ticker)
    with connect() as conn:
        px = conn.execute(
            "SELECT MIN(date) a, MAX(date) b, COUNT(*) c FROM prices WHERE ticker=?",
            (t,)).fetchone()
        stmts = conn.execute(
            "SELECT statement, COUNT(*) c FROM financial_statements WHERE ticker=?"
            " GROUP BY statement", (t,)).fetchall()
        earnings = conn.execute(
            "SELECT COUNT(*) c FROM earnings WHERE ticker=?", (t,)).fetchone()
    return {
        "ticker": t,
        "prices": {"from": px["a"], "to": px["b"], "rows": px["c"]},
        "statements": {r["statement"]: r["c"] for r in stmts},
        "earnings_rows": earnings["c"],
    }


# --------------------------------------------------------------- ingestion
@app.post("/api/ingest/{ticker}")
def ingest(ticker: str, force: bool = Query(False)):
    t = validate_ticker(ticker)
    try:
        report = _INGEST.ingest_ticker(t)
    except QuantValidationError as exc:
        raise _err(400, str(exc)) from exc
    return {
        "ticker": t, "ok": report.ok(), "report": {
            "companies": report.companies, "prices": report.prices,
            "statements": report.statements,
            "fundamentals": report.fundamentals,
            "earnings": report.earnings, "errors": report.errors,
            "validation": report.validation,
        },
    }


# ------------------------------------------------------------------- quote
@app.get("/api/quote/{ticker}")
def quote(ticker: str):
    t = validate_ticker(ticker)
    with connect() as conn:
        company = conn.execute(
            "SELECT name, sector, industry, exchange, currency FROM companies"
            " WHERE ticker = ?", (t,)).fetchone()
        px = conn.execute(
            "SELECT date, close, adj_close, volume FROM prices WHERE ticker=?"
            " ORDER BY date DESC LIMIT 1", (t,)).fetchone()
        px_prev = conn.execute(
            "SELECT close FROM prices WHERE ticker=? AND date < ?"
            " ORDER BY date DESC LIMIT 1",
            (t, px["date"] if px else "0000-00-00")).fetchone()
    if px is None:
        raise _err(404, f"no price data stored for {t}")
    prev = px_prev["close"] if px_prev else None
    return {
        "ticker": t,
        "name": company["name"] if company else None,
        "sector": company["sector"] if company else None,
        "industry": company["industry"] if company else None,
        "as_of": px["date"],
        "price": px["close"],
        "prev_close": prev,
        "change_pct": ((px["close"] - prev) / prev) if prev else None,
        "volume": px["volume"],
    }


# ------------------------------------------------------------- factor model
@app.post("/api/analyze/{ticker}")
def analyze(ticker: str, as_of: str | None = Query(None),
            benchmark: str = Query("SPY"), persist: bool = Query(True)):
    """Full factor analysis for one ticker (point-in-time on as_of)."""
    t = validate_ticker(ticker)
    on = date.fromisoformat(as_of) if as_of else date.today()
    try:
        payload = run_factor_model(t, on, benchmark_ticker=benchmark,
                                   persist=persist)
    except ValueError as exc:
        raise _err(404, str(exc)) from exc
    except QuantError as exc:
        raise _err(502, str(exc)) from exc
    return payload


@app.get("/api/analyze/{ticker}/metrics")
def analyze_metrics_breakdown(ticker: str, as_of: str | None = Query(None)):
    """Raw metric inputs + per-metric scores (no black box)."""
    t = validate_ticker(ticker)
    on = date.fromisoformat(as_of) if as_of else date.today()
    raw = build_metric_inputs(t, on)
    from .quant.factors import METRIC_DEFS, compute_factor_scores
    result = compute_factor_scores(raw, ticker=t, as_of=on.isoformat())
    defs = {m.name: {"factor": m.factor, "label": m.label,
                     "direction": m.direction, "weight": m.weight,
                     "band": list(m.band)} for m in METRIC_DEFS}
    return {"ticker": t, "as_of": on.isoformat(), "raw_inputs": result.raw_inputs,
            "metric_scores": result.metric_scores, "definitions": defs,
            "factor_scores": result.factor_scores,
            "quant_score": result.quant_score,
            "coverage": result.coverage, "missing": result.missing}


# ------------------------------------------------------ DCF input derivation
@app.get("/api/dcf-inputs/{ticker}")
def dcf_inputs(ticker: str, as_of: str | None = Query(None)):
    """Derive DCF assumption starting points from the most recent stored
    filings (point-in-time on as_of). Every derived value names its source;
    non-derivable assumptions (WACC, terminal growth, WC change) are flagged
    as placeholders for the analyst to override."""
    from .quant.model import _latest_stmt_before, _stmt_before

    t = validate_ticker(ticker)
    on = date.fromisoformat(as_of) if as_of else date.today()
    with connect() as conn:
        income = _statement_items(conn, t, "income")
        balance = _statement_items(conn, t, "balance")
        cash = _statement_items(conn, t, "cashflow")
        fund = conn.execute(
            "SELECT * FROM fundamentals WHERE ticker = ?"
            " ORDER BY as_of DESC LIMIT 1", (t,)).fetchone()
        px = _prices_frame(conn, t)

    def item(st, key):
        return None if st is None else ((st["items"] or {}).get(key))

    inc_now = _latest_stmt_before(income, on)
    bal_now = _latest_stmt_before(balance, on)
    cf_now = _latest_stmt_before(cash, on)
    inc_1y = _stmt_before(income, 1.0, on)
    if inc_now is None:
        raise _err(404, f"no income statements stored for {t}; ingest first")

    revenue = item(inc_now, "revenue")
    ebit = item(inc_now, "operating_income")
    da = item(cf_now, "depreciation_amortization")
    capex = item(cf_now, "capex")
    cash_v = item(bal_now, "cash")
    std = item(bal_now, "short_term_debt")
    ltd = item(bal_now, "long_term_debt")
    tax = item(inc_now, "tax_expense")
    pretax = item(inc_now, "pretax_income")
    shares = fund["shares_diluted"] if fund else None
    if shares is None:
        # SEC reports weighted-average diluted shares on the income statement;
        # balance sheets only carry the point-in-time outstanding count.
        shares = item(inc_now, "shares_diluted")
    if shares is None:
        shares = item(bal_now, "shares_outstanding")
    price = float(px.iloc[-1]) if not px.empty else None

    rev_1y = item(inc_1y, "revenue")
    growth_1y = (revenue / rev_1y - 1.0) if (revenue and rev_1y and rev_1y > 0) else None

    debt_parts = [d for d in (std, ltd) if d is not None]
    total_debt = sum(debt_parts) if debt_parts else None
    net_debt = (total_debt - cash_v) if (total_debt is not None and cash_v is not None) else None

    derived: dict[str, float | None] = {
        "base_revenue": revenue,
        "revenue_growth_1y": round(growth_1y, 4) if growth_1y is not None else None,
        "ebit_margin": round(ebit / revenue, 4) if (ebit is not None and revenue) else None,
        "capex_pct_revenue": round(abs(capex) / revenue, 4) if (capex is not None and revenue) else None,
        "depreciation_pct_revenue": round(da / revenue, 4) if (da is not None and revenue) else None,
        "effective_tax_rate": round(tax / pretax, 4) if (tax is not None and pretax and pretax > 0) else None,
        "net_debt": net_debt,
        "shares_diluted": shares,
        "current_price": price,
    }
    placeholders = {
        "wacc": 0.10,
        "terminal_growth": 0.02,
        "wc_change_pct_revenue": 0.01,
    }
    missing = [k for k, v in derived.items() if v is None]
    return {
        "ticker": t,
        "as_of": on.isoformat(),
        "fiscal_date": inc_now["fiscal_date"],
        "derived": derived,
        "placeholders": placeholders,
        "missing": missing,
    }


# --------------------------------------------------------------------- DCF
class DCFBody(BaseModel):
    base_revenue: float = Field(gt=0)
    revenue_growth: list[float] = Field(min_length=1)
    ebit_margin: float | list[float]
    tax_rate: float = Field(ge=0, lt=1)
    capex_pct_revenue: float | list[float]
    depreciation_pct_revenue: float | list[float]
    wc_change_pct_revenue: float | list[float]
    wacc: float = Field(gt=0)
    terminal_growth: float
    net_debt: float
    shares_diluted: float = Field(gt=0)
    current_price: float | None = None


@app.post("/api/dcf/{ticker}")
def dcf(ticker: str, body: DCFBody, years: int = Query(5, ge=1, le=10)):
    t = validate_ticker(ticker)
    try:
        a = DCFAssumptions(**body.model_dump())
        result = run_dcf(a, years)
    except InvalidAssumptionError as exc:
        raise _err(422, str(exc)) from exc
    payload = {
        "ticker": t,
        "fair_value_per_share": round(result.fair_value_per_share, 2),
        "enterprise_value": result.enterprise_value,
        "equity_value": result.equity_value,
        "pv_explicit": result.pv_explicit,
        "pv_terminal": result.pv_terminal,
        "terminal_value": result.terminal_value,
        "upside": result.upside,
        "warnings": result.warnings,
        "assumptions": body.model_dump(),
        "projected": result.projected,
    }
    from .research.journal import record_model_run
    record_model_run("dcf", DCF_MODEL_VERSION, t, body.model_dump(),
                     {"fair_value_per_share": payload["fair_value_per_share"],
                      "upside": payload["upside"]}, input_as_of=today())
    return payload


@app.post("/api/dcf/{ticker}/sensitivity")
def dcf_sensitivity(ticker: str, body: DCFBody,
                    wacc_low: float = 0.07, wacc_high: float = 0.13,
                    g_low: float = 0.01, g_high: float = 0.05,
                    steps: int = Query(5, ge=3, le=9)):
    t = validate_ticker(ticker)
    wacc_axis = [round(wacc_low + i * (wacc_high - wacc_low) / (steps - 1), 4)
                 for i in range(steps)]
    g_axis = [round(g_low + i * (g_high - g_low) / (steps - 1), 4)
              for i in range(steps)]
    try:
        a = DCFAssumptions(**body.model_dump())
        table = sensitivity_table(a, wacc_axis, g_axis)
    except InvalidAssumptionError as exc:
        raise _err(422, str(exc)) from exc
    return {"ticker": t, **table}


# ------------------------------------------------------------- monte carlo
@app.get("/api/montecarlo/{ticker}")
def montecarlo(ticker: str, days: int = Query(252, ge=1, le=1260),
               sims: int = Query(10_000, ge=100, le=100_000),
               seed: int = Query(42)):
    t = validate_ticker(ticker)
    with connect() as conn:
        px = _prices_frame(conn, t)
    if px.empty:
        raise _err(404, f"no price data for {t}")
    result = run_monte_carlo(px, t, days=days, n_simulations=sims, seed=seed)
    from .research.journal import record_model_run
    record_model_run("monte_carlo", result.version, t,
                     {"days": days, "sims": sims, "seed": seed},
                     {"median": result.median, "prob_gain": result.prob_gain},
                     input_as_of=today())
    return result.to_dict()


# ------------------------------------------------------------------ regime
@app.get("/api/regime")
def regime(benchmark: str = Query("SPY")):
    t = validate_ticker(benchmark)
    with connect() as conn:
        bench = _prices_frame(conn, t)
        spy = _prices_frame(conn, "SPY")
        tlt = _prices_frame(conn, "TLT")
    if bench.empty:
        raise _err(404, f"no price data for {t}; ingest it first")
    spy_s = spy if not spy.empty else None
    tlt_s = tlt if not tlt.empty else None
    return classify_regime(bench, pd.Timestamp(bench.index[-1]), spy_s, tlt_s)


# ----------------------------------------------------------------- earnings
@app.get("/api/earnings/{ticker}")
def earnings(ticker: str):
    t = validate_ticker(ticker)
    with connect() as conn:
        from .ingestion import repository as repo
        records = repo.read_earnings(conn, t)
        px = _prices_frame(conn, t)
    if not records:
        return {"ticker": t, "records": [], "summary": {"n_reports": 0}}
    from .simulation.earnings import analyze_earnings
    return analyze_earnings(records, px)


# ---------------------------------------------------------------- portfolio
class PositionBody(BaseModel):
    ticker: str
    quantity: float = Field(gt=0)
    avg_cost: float | None = None


class PortfolioCreateBody(BaseModel):
    name: str
    benchmark: str = "SPY"
    cash: float = 0.0


@app.post("/api/portfolios")
def create_portfolio(body: PortfolioCreateBody):
    pid = journal.create_portfolio(body.name, body.benchmark, body.cash)
    return {"id": pid, "name": body.name}


@app.get("/api/portfolios")
def list_portfolios():
    return journal.list_portfolios()


@app.get("/api/portfolios/{portfolio_id}")
def get_portfolio(portfolio_id: str):
    p = journal.get_portfolio(portfolio_id)
    if p is None:
        raise _err(404, "portfolio not found")
    return p


@app.post("/api/portfolios/{portfolio_id}/positions")
def add_position(portfolio_id: str, body: PositionBody):
    t = validate_ticker(body.ticker)
    journal.add_position(portfolio_id, t, body.quantity, body.avg_cost)
    return {"ok": True}


@app.get("/api/portfolios/{portfolio_id}/analytics")
def portfolio_analytics(portfolio_id: str, benchmark: str = Query("SPY")):
    p = journal.get_portfolio(portfolio_id)
    if p is None:
        raise _err(404, "portfolio not found")
    positions = p["positions"]
    if not positions:
        raise _err(400, "portfolio has no positions")
    with connect() as conn:
        series = {pos["ticker"]: _prices_frame(conn, pos["ticker"])
                  for pos in positions}
        bench = _prices_frame(conn, benchmark)
    missing = [t for t, s in series.items() if s.empty]
    if missing:
        raise _err(404, f"no price data for: {', '.join(missing)}")
    rets_df = pd.DataFrame({t: s.pct_change() for t, s in series.items()})
    weights = {pos["ticker"]: pos["quantity"] for pos in positions}
    total_q = sum(weights.values())
    weights = {t: q / total_q for t, q in weights.items()}
    port_rets = (rets_df.fillna(0.0)
                 .mul(pd.Series(weights)).sum(axis=1).dropna())
    b_rets = bench.pct_change().dropna()
    stats = P.portfolio_stats(port_rets, b_rets)
    curve = P.equity_curve(port_rets, 1.0)
    stats["max_drawdown"] = max_drawdown_positive(curve)
    # Current value / allocation
    last_prices = {t: float(s.iloc[-1]) for t, s in series.items() if not s.empty}
    value = {t: last_prices[t] * w_total for t, w_total in
             ((pos["ticker"], pos["quantity"]) for pos in positions)}
    total_value = sum(value.values())
    return {
        "portfolio_id": portfolio_id, "benchmark": benchmark,
        "weights": {t: round(w, 4) for t, w in weights.items()},
        "positions_value": {t: round(v, 2) for t, v in value.items()},
        "total_value": round(total_value, 2),
        "stats": _round_stats(stats),
        "correlation": P.correlation_analysis(series),
        "equity_curve": {"dates": [str(d.date()) for d in curve.index],
                         "values": [round(float(v), 4) for v in curve.values]},
    }


def _round_stats(stats: dict) -> dict:
    return {k: (round(v, 4) if isinstance(v, float) else v)
            for k, v in stats.items()}


# --------------------------------------------------------------- optimizer
class OptimizeBody(BaseModel):
    tickers: list[str] = Field(min_length=2)
    objective: str = "max_sharpe"
    max_position: float = Field(0.35, gt=0, le=1)
    min_position: float = Field(0.0, ge=0)
    target_return: float | None = None


@app.post("/api/optimize")
def optimize_endpoint(body: OptimizeBody, benchmark: str = Query("SPY")):
    tickers = [validate_ticker(t) for t in body.tickers]
    with connect() as conn:
        series = {t: _prices_frame(conn, t) for t in tickers}
    missing = [t for t, s in series.items() if s.empty]
    if missing:
        raise _err(404, f"no price data for: {', '.join(missing)}; ingest first")
    mu, cov = covariance_from_prices(series)
    try:
        result = optimize(mu, cov, body.objective, body.max_position,
                          body.min_position, body.target_return)
    except CalculationError as exc:
        raise _err(422, str(exc)) from exc
    from .research.journal import record_model_run
    record_model_run("optimizer", result["version"], ",".join(tickers),
                     body.model_dump(), result["weights"], input_as_of=today())
    return result


# ---------------------------------------------------------------- backtest
class BacktestBody(BaseModel):
    universe: list[str] = Field(min_length=1)
    start: str
    end: str
    benchmark: str = "SPY"
    rebalance_frequency: str = "monthly"
    commission_bps: float = 0.0
    slippage_bps: float = 0.0
    top_n: int = 3
    factor: str = "momentum"


@app.post("/api/backtest")
def backtest(body: BacktestBody):
    """Factor backtest: rank universe by the chosen factor using ONLY
    point-in-time data at each rebalance date."""
    from .backtest.engine import BacktestConfig, factor_backtest
    from .quant.factors import compute_factor_scores
    from .quant.model import build_metric_inputs

    universe = [validate_ticker(t) for t in body.universe]
    cfg = BacktestConfig(
        universe=universe, start=body.start, end=body.end,
        benchmark=body.benchmark,
        rebalance_frequency=body.rebalance_frequency,
        commission_bps=body.commission_bps, slippage_bps=body.slippage_bps,
    )

    def factor_score_at(ticker: str, on: pd.Timestamp) -> float | None:
        """Point-in-time factor score: factor model recomputed as of `on`."""
        try:
            raw = build_metric_inputs(ticker, on.date(), body.benchmark)
            fs = compute_factor_scores(raw, ticker=ticker,
                                       as_of=str(on.date()))
            return fs.factor_scores.get(body.factor)
        except Exception:
            return None

    with connect() as conn:
        px = pd.DataFrame({t: _prices_frame(conn, t) for t in [*universe, body.benchmark]})
    bench = (px.pop(body.benchmark) if body.benchmark in px.columns
             else pd.Series(dtype=float))
    px = px.dropna(how="all")
    if px.empty:
        raise _err(404, "no price data for the requested universe")

    try:
        result = factor_backtest(px, bench, cfg, factor_score_at, body.top_n)
    except ValueError as exc:
        raise _err(422, str(exc)) from exc

    from .config import BACKTEST_ENGINE_VERSION
    from .research.journal import record_model_run
    curve = result.equity_curve
    payload = {
        "config": result.config.to_record(),
        "stats": result.stats,
        "equity_curve": {"dates": [str(d.date()) for d in curve.index],
                         "values": [round(float(v), 2) for v in curve.values]},
        "benchmark_curve": {
            "dates": [str(d.date()) for d in result.benchmark_curve.index],
            "values": [round(float(v), 4) for v in result.benchmark_curve.values]},
        "trade_log": result.trade_log[:50],
        "skipped_executions": result.skipped_executions[:20],
    }
    record_model_run("backtest", BACKTEST_ENGINE_VERSION, ",".join(universe),
                     body.model_dump(), result.stats, input_as_of=body.start)
    return payload


# ---------------------------------------------------------------- research
class DecisionBody(BaseModel):
    ticker: str
    decision: str
    price: float | None = None
    quant_score: float | None = None
    value_score: float | None = None
    growth_score: float | None = None
    quality_score: float | None = None
    momentum_score: float | None = None
    risk_score: float | None = None
    dcf_fair_value: float | None = None
    dcf_upside: float | None = None
    position_size: float | None = None
    thesis: str | None = None
    catalysts: str | None = None
    risks: str | None = None
    model_run_id: int | None = None


@app.post("/api/decisions")
def create_decision(body: DecisionBody):
    t = validate_ticker(body.ticker)
    try:
        did = journal.record_decision(ticker=t, **body.model_dump(exclude={"ticker"}))
    except ValueError as exc:
        raise _err(422, str(exc)) from exc
    return {"id": did, "ok": True}


@app.get("/api/decisions")
def list_decisions(ticker: str | None = None, limit: int = Query(200, le=1000)):
    return journal.list_decisions(ticker, limit)


@app.patch("/api/decisions/{decision_id}/outcome")
def decision_outcome(decision_id: int, outcome: str = Query(...)):
    journal.update_outcome(decision_id, outcome)
    return {"ok": True}


@app.get("/api/model_runs")
def model_runs(subject: str | None = None, model: str | None = None,
               limit: int = Query(100, le=500)):
    return journal.list_model_runs(subject, model, limit)


@app.get("/api/model_runs/{run_id}")
def model_run(run_id: int):
    run = journal.get_model_run(run_id)
    if run is None:
        raise _err(404, "model run not found")
    return run


# ---------------------------------------------------------- recommendation
@app.get("/api/recommend/{ticker}")
def recommend_endpoint(ticker: str, as_of: str | None = Query(None)):
    from .simulation.recommendation import RecommendationInput, recommend
    t = validate_ticker(ticker)
    on = date.fromisoformat(as_of) if as_of else date.today()

    from .quant.model import run_factor_model
    fs = run_factor_model(t, on, persist=False)
    from .simulation.earnings import analyze_earnings
    with connect() as conn:
        from .ingestion import repository as repo
        recs = repo.read_earnings(conn, t)
        px = _prices_frame(conn, t)
    earnings = analyze_earnings(recs, px) if recs else {"summary": {}}
    from .quant.factors import compute_factor_scores
    raw = build_metric_inputs(t, on)
    full = compute_factor_scores(raw, ticker=t, as_of=on.isoformat())
    mom = full.raw_inputs.get("momentum_12m")
    vol = full.raw_inputs.get("annual_volatility")
    dd = full.raw_inputs.get("max_drawdown_mag")
    rec = recommend(t, RecommendationInput(
        quant_score=fs["quant_score"] if math_ok(fs["quant_score"]) else None,
        dcf_upside=None,  # DCF run separately; UI combines
        momentum_12m=mom,
        earnings_beat_rate=earnings.get("summary", {}).get("beat_rate"),
        annual_volatility=vol,
        max_drawdown=dd,
    ))
    from .research.journal import record_model_run
    record_model_run("recommendation", rec.version, t,
                     {"quant_score": fs.get("quant_score")},
                     rec.to_dict(), input_as_of=on.isoformat())
    return rec.to_dict()


def math_ok(v) -> bool:
    import math as _m
    return v is not None and _m.isfinite(v)


# ------------------------------------------------------------------- run
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
