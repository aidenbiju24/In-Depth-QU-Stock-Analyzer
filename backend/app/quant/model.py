"""Factor model: build raw metric inputs from stored data, point-in-time.

Look-ahead discipline (PROJECT_SPEC §51-53, METHODOLOGY §3):
- Prices used on date T are strictly <= T.
- Fundamental metrics on date T come only from statements whose FILING date
  (or, when unknown, retrieval date) is <= T. A statement for fiscal year 2023
  filed 2024-02-15 is NOT usable for a 2024-01-10 decision.
- Momentum uses trailing windows of prices up to T only.
- The benchmark series for relative momentum is likewise truncated at T.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import date, timedelta

import pandas as pd

from ..config import FACTOR_MODEL_VERSION, config
from ..db import connect, utcnow
from ..ingestion import repository as repo
from . import metrics as M
from .factors import METRIC_DEFS, compute_factor_scores

LOGGER = logging.getLogger(__name__)


def _latest_stmt_before(stmts: list[dict], on: date) -> dict | None:
    """Most recent statement whose filing date (fallback: fiscal date) <= on."""
    best = None
    for st in stmts:
        fd = date.fromisoformat(st["fiscal_date"])
        filed = st.get("filing_date")
        filed = date.fromisoformat(filed) if filed else fd
        if filed <= on and (best is None or fd > date.fromisoformat(best["fiscal_date"])):
            best = st
    return best


def _stmt_before(stmts: list[dict], years: float, on: date) -> dict | None:
    """Statement ~`years` before the LATEST statement available at `on`.

    Both the base and the comparison statement must be filed by `on`. Anchoring
    on the latest statement (rather than on `on - years`) prevents the latest
    filing from being compared against itself when the fiscal year-end falls
    near the analysis date — which would silently zero every YoY metric.
    """
    latest = _latest_stmt_before(stmts, on)
    if latest is None:
        return None
    latest_fd = date.fromisoformat(latest["fiscal_date"])
    target = latest_fd - timedelta(days=int(365.25 * years))
    best, best_gap = None, None
    for st in stmts:
        fd = date.fromisoformat(st["fiscal_date"])
        if fd >= latest_fd:
            continue  # strictly earlier than the base statement
        filed = st.get("filing_date")
        filed = date.fromisoformat(filed) if filed else fd
        if filed > on:
            continue
        gap = abs((fd - target).days)
        if best_gap is None or gap < best_gap:
            best, best_gap = st, gap
    return best


def _prices_frame(rows: list[dict]) -> pd.Series:
    if not rows:
        return pd.Series(dtype=float)
    s = pd.Series(
        {r["date"]: (r["adj_close"] if r["adj_close"] is not None else r["close"])
         for r in rows},
        dtype=float,
    )
    s.index = pd.to_datetime(s.index)
    return s.sort_index()


def _momentum(prices: pd.Series, on: pd.Timestamp, days: int) -> float:
    """Trailing price return over ~days calendar days, using only data <= on."""
    window = prices.loc[:on]
    if len(window) < 2:
        return float("nan")
    end = float(window.iloc[-1])
    start_ts = on - pd.Timedelta(days=days)
    prior = window.loc[:start_ts]
    if len(prior) == 0:
        return float("nan")
    start = float(prior.iloc[-1])
    if start == 0:
        return float("nan")
    return end / start - 1.0


def _consistency(prices: pd.Series, on: pd.Timestamp) -> float:
    # Slice by date — Series.last() was removed in pandas 3.0.
    window = prices.loc[on - pd.Timedelta(days=400):on]
    if len(window) < 40:
        return float("nan")
    r = window.pct_change().dropna()
    monthly = (1 + r).resample("ME").prod() - 1
    if len(monthly) < 6:
        return float("nan")
    return float((monthly > 0).mean())


def _safe(fn, *args):
    try:
        v = fn(*args)
    except Exception as exc:
        # Deliberate boundary: a factor input that fails to compute must degrade
        # to "missing" (NaN), never crash the whole score build.
        LOGGER.debug("factor input %s failed: %s", fn.__name__, exc)
        return float("nan")
    if v is None:
        return float("nan")
    v = float(v)
    return v if math.isfinite(v) else float("nan")


def build_metric_inputs(ticker: str, as_of: date,
                        benchmark_ticker: str = "SPY") -> dict:
    """Assemble raw metric values for `ticker` using only data public by as_of."""
    out: dict[str, float | None] = {m.name: None for m in _METRIC_NAMES}
    with connect() as conn:
        prices = _prices_frame(repo.read_prices(conn, ticker))
        bench_rows = repo.read_prices(conn, benchmark_ticker)
    fund = repo.read_fundamentals_latest(conn, ticker) or {}
    income = repo.read_statements(conn, ticker, "income", "annual", as_of.isoformat())
    balance = repo.read_statements(conn, ticker, "balance", "annual", as_of.isoformat())
    cash = repo.read_statements(conn, ticker, "cashflow", "annual", as_of.isoformat())

    on = pd.Timestamp(as_of)
    px_on = prices.loc[:on]
    if len(px_on) == 0:
        raise ValueError(f"no price data for {ticker} on/before {as_of}")

    # ---------------- Momentum (trailing windows, prices <= as_of only)
    out["momentum_1m"] = _safe(_momentum, prices, on, 30)
    out["momentum_3m"] = _safe(_momentum, prices, on, 91)
    out["momentum_6m"] = _safe(_momentum, prices, on, 182)
    out["momentum_12m"] = _safe(_momentum, prices, on, 365)
    out["momentum_consistency"] = _safe(_consistency, prices, on)
    if len(bench_rows) > 0:
        bench = _prices_frame(bench_rows)
        b12 = _safe(_momentum, bench, on, 365)
        s12 = out["momentum_12m"]
        if math.isfinite(b12) and math.isfinite(s12):
            out["rel_strength_12m"] = s12 - b12

    # Returns for risk metrics: last 252 trading days <= as_of.
    rets = px_on.pct_change().dropna().tail(252)
    out["annual_volatility"] = _safe(M.volatility, rets)
    out["sharpe"] = _safe(M.sharpe_ratio, rets, config.RISK_FREE_RATE)
    out["downside_deviation"] = _safe(M.downside_deviation, rets)
    dd = _safe(M.max_drawdown_positive, px_on.tail(252))
    out["max_drawdown_mag"] = dd

    bench_rets = _prices_frame(bench_rows).loc[:on].pct_change().dropna().tail(252)
    if len(rets) > 20 and len(bench_rets) > 20:
        b = _safe(M.beta, rets, bench_rets)
        out["beta"] = b
        out["beta_deviation"] = abs(b - 1.0) if math.isfinite(b) else None

    # ---------------- Fundamentals (point-in-time snapshot if available)
    fund_ok = fund and str(fund.get("as_of", "")) <= as_of.isoformat()
    pe = fund.get("pe") if fund_ok else None
    out["pe"] = pe
    out["forward_pe"] = fund.get("forward_pe") if fund_ok else None
    out["pb"] = fund.get("pb") if fund_ok else None
    out["ps"] = fund.get("ps") if fund_ok else None
    out["ev_ebitda"] = fund.get("ev_ebitda") if fund_ok else None
    if fund_ok and pe:
        out["earnings_yield"] = 1.0 / pe

    # ---------------- Statement-derived metrics (filing-date aware)
    inc_now = _latest_stmt_before(income, as_of)
    bal_now = _latest_stmt_before(balance, as_of)
    cf_now = _latest_stmt_before(cash, as_of)
    inc_1y = _stmt_before(income, 1.0, as_of)
    inc_3y = _stmt_before(income, 3.0, as_of)
    cf_1y = _stmt_before(cash, 1.0, as_of)

    def item(st, key):
        return None if st is None else (st["items"] or {}).get(key)

    # --- Value additions from statements
    eps_now = item(inc_now, "eps_diluted")
    if fund_ok and fund.get("market_cap") and eps_now:
        out["earnings_yield"] = eps_now / (fund["market_cap"] / fund["shares_diluted"]) \
            if fund.get("shares_diluted") else out["earnings_yield"]
    fcf_now = None
    ocf_now = item(cf_now, "operating_cash_flow")
    capex_now = item(cf_now, "capex")
    if ocf_now is not None and capex_now is not None:
        fcf_now = ocf_now - abs(capex_now)
    if fund_ok and fund.get("market_cap") and fcf_now:
        out["fcf_yield"] = fcf_now / fund["market_cap"]

    # --- Growth
    rev_now, rev_1y, rev_3y = item(inc_now, "revenue"), item(inc_1y, "revenue"), item(inc_3y, "revenue")
    if rev_now and rev_1y and rev_1y > 0:
        out["revenue_growth_1y"] = rev_now / rev_1y - 1.0
    out["revenue_cagr_3y"] = _safe(M.cagr, rev_3y, rev_now, 3.0)
    ni_now, ni_1y = item(inc_now, "net_income"), item(inc_1y, "net_income")
    if ni_now is not None and ni_1y is not None and ni_1y > 0 and ni_now > 0:
        out["eps_growth_1y"] = ni_now / ni_1y - 1.0
    fcf_1y = None
    ocf_1y = item(cf_1y, "operating_cash_flow")
    capex_1y = item(cf_1y, "capex")
    if ocf_1y is not None and capex_1y is not None:
        fcf_1y = ocf_1y - abs(capex_1y)
    if fcf_now and fcf_1y and fcf_1y > 0 and fcf_now > 0:
        out["fcf_growth_1y"] = fcf_now / fcf_1y - 1.0
    oi_now, oi_1y = item(inc_now, "operating_income"), item(inc_1y, "operating_income")
    if oi_now is not None and oi_1y is not None and oi_1y > 0 and oi_now > 0:
        out["op_income_growth_1y"] = oi_now / oi_1y - 1.0
    if rev_now and oi_now is not None and rev_1y and oi_1y is not None:
        om_now, om_1y = oi_now / rev_now, oi_1y / rev_1y
        out["margin_expansion"] = om_now - om_1y

    # --- Quality
    if rev_now and rev_now > 0:
        gp = item(inc_now, "gross_profit")
        if gp is not None:
            out["gross_margin"] = gp / rev_now
        if oi_now is not None:
            out["operating_margin"] = oi_now / rev_now
        if ni_now is not None:
            out["net_margin"] = ni_now / rev_now
    if fcf_now is not None and rev_now and rev_now > 0:
        out["fcf_margin"] = fcf_now / rev_now
    eq_now = item(bal_now, "total_equity")
    if ni_now is not None and eq_now and eq_now > 0:
        out["roe"] = ni_now / eq_now
    debt = None
    ltd, std = item(bal_now, "long_term_debt"), item(bal_now, "short_term_debt")
    parts = [d for d in (ltd, std) if d is not None]
    if parts:
        debt = sum(parts)
    tax = item(inc_now, "tax_expense")
    pretax = item(inc_now, "pretax_income")
    tax_rate = (tax / pretax) if (tax is not None and pretax and pretax > 0) else None
    ic = None
    if debt is not None and eq_now is not None:
        ic = debt + eq_now
    elif eq_now is not None:
        ic = eq_now
    if oi_now is not None and ic and ic > 0:
        nopat = oi_now * (1 - tax_rate) if tax_rate is not None else oi_now
        out["roic"] = nopat / ic
    if debt is not None and eq_now and eq_now > 0:
        out["debt_to_equity"] = debt / eq_now
    int_exp = item(inc_now, "interest_expense")
    if oi_now is not None and int_exp and int_exp > 0:
        out["interest_coverage"] = oi_now / int_exp

    # --- Earnings consistency: fraction of last 5 annual statements with NI > 0
    nis = [item(st, "net_income") for st in income[-5:]]
    nis = [x for x in nis if x is not None]
    if len(nis) >= 3:
        out["earnings_consistency"] = sum(1 for x in nis if x > 0) / len(nis)

    def _clean(v):
        if v is None:
            return None
        if isinstance(v, (int, float)) and math.isfinite(float(v)):
            return float(v)
        return None

    return {k: _clean(v) for k, v in out.items()}


_METRIC_NAMES = METRIC_DEFS


def run_factor_model(ticker: str, as_of: date,
                     benchmark_ticker: str = "SPY",
                     persist: bool = True) -> dict:
    """Run the full factor model for one ticker; persist a model_run."""
    raw = build_metric_inputs(ticker, as_of, benchmark_ticker)
    result = compute_factor_scores(raw, ticker=ticker, as_of=as_of.isoformat())
    payload = result.to_dict()
    if persist:
        with connect() as conn:
            cur = conn.execute(
                "INSERT INTO model_runs (model, version, subject, run_at, input_as_of,"
                " parameters, output, source_data) VALUES (?,?,?,?,?,?,?,?)",
                ("factor_model", FACTOR_MODEL_VERSION, ticker, utcnow(),
                 as_of.isoformat(),
                 json.dumps({"benchmark": benchmark_ticker, "mode": "absolute"}),
                 json.dumps(payload),
                 json.dumps({"prices_source": "db",
                             "statements": "filing-date filtered"})),
            )
            run_id = cur.lastrowid
            conn.execute(
                "INSERT INTO factor_scores (model_run_id, ticker, as_of, universe,"
                " value_score, growth_score, quality_score, momentum_score,"
                " risk_score, quant_score, components_json, coverage, version)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, ticker, as_of.isoformat(), "absolute",
                 payload["factor_scores"].get("value"),
                 payload["factor_scores"].get("growth"),
                 payload["factor_scores"].get("quality"),
                 payload["factor_scores"].get("momentum"),
                 payload["factor_scores"].get("risk"),
                 payload["quant_score"] if math.isfinite(payload["quant_score"]) else None,
                 json.dumps(payload),
                 payload["overall_coverage"], FACTOR_MODEL_VERSION),
            )
    return payload
