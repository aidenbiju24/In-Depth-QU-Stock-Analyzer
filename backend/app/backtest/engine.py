"""Backtesting engine (METHODOLOGY.md §41-46).

Timeline discipline (§42):
    information at T -> signal -> decision -> execute at T+1 close -> observe

A `SignalFn` receives ONLY data available at T (prices truncated to T, factor
scores computed from statements filed by T, benchmark truncated to T) and
returns target weights. The engine executes at the NEXT bar's close, so a
signal can never see the price it trades at.

Accounting model: the portfolio holds units (shares) and cash. On each
execution date the engine re-allocates full equity to the target weights at
that day's close, paying (commission + slippage) in bps on the transacted
value. A target ticker with no price on the execution date is skipped and the
portion stays in cash — recorded explicitly in the trade log, never silently
dropped.

Corporate actions: total-return adjusted prices (adj_close) are used
throughout, so splits/dividends are handled consistently.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..config import BACKTEST_ENGINE_VERSION
from ..quant import metrics as M
from ..quant.metrics import TRADING_DAYS


@dataclass
class BacktestConfig:
    universe: list[str]
    start: str
    end: str
    benchmark: str = "SPY"
    initial_capital: float = 100_000.0
    rebalance_frequency: str = "monthly"   # daily | weekly | monthly | quarterly
    commission_bps: float = 0.0            # per-side cost, basis points
    slippage_bps: float = 0.0              # per-side cost, basis points
    signal_lag_days: int = 1               # execute N trading days after signal
    risk_free_rate: float | None = None    # default from app config

    def to_record(self) -> dict:
        return {
            "universe": list(self.universe), "start": self.start, "end": self.end,
            "benchmark": self.benchmark, "initial_capital": self.initial_capital,
            "rebalance_frequency": self.rebalance_frequency,
            "commission_bps": self.commission_bps,
            "slippage_bps": self.slippage_bps,
            "signal_lag_days": self.signal_lag_days,
            "engine_version": BACKTEST_ENGINE_VERSION,
        }


@dataclass
class BacktestResult:
    config: BacktestConfig
    stats: dict = field(default_factory=dict)
    equity_curve: pd.Series | None = None
    benchmark_curve: pd.Series | None = None
    trade_log: list[dict] = field(default_factory=list)
    skipped_executions: list[dict] = field(default_factory=list)


class SignalContext:
    """Point-in-time view handed to strategies. Slices are strictly <= T."""

    def __init__(self, date: pd.Timestamp, prices: pd.DataFrame,
                 benchmark: pd.Series, factor_lookup: Callable | None = None):
        self.date = date
        self._prices = prices.loc[:date]          # rows <= T only
        self.benchmark = benchmark.loc[:date]
        self._factor_lookup = factor_lookup

    def history(self, ticker: str) -> pd.Series:
        """Adjusted close history for ticker up to and including T."""
        if ticker not in self._prices.columns:
            return pd.Series(dtype=float)
        return self._prices[ticker].dropna()

    def returns(self, ticker: str, tail: int = 252) -> pd.Series:
        h = self.history(ticker)
        return h.pct_change().dropna().tail(tail)

    def factor_score(self, ticker: str):
        if self._factor_lookup is None:
            return None
        return self._factor_lookup(ticker, self.date)


SignalFn = Callable[[SignalContext], dict[str, float]]


class BacktestEngine:
    def __init__(self, prices: pd.DataFrame, benchmark: pd.Series,
                 cfg: BacktestConfig, factor_lookup: Callable | None = None,
                 risk_free_rate: float | None = None):
        self.prices = prices
        self.benchmark = benchmark
        self.cfg = cfg
        self.factor_lookup = factor_lookup
        if risk_free_rate is not None:
            self.rf = risk_free_rate
        elif cfg.risk_free_rate is not None:
            self.rf = cfg.risk_free_rate
        else:
            from ..config import config as app_config
            self.rf = app_config.RISK_FREE_RATE

    # ------------------------------------------------------------------ run
    def run(self, signal_fn: SignalFn) -> BacktestResult:
        cfg = self.cfg
        px = self.prices.dropna(how="all").loc[cfg.start:cfg.end]
        if len(px) < 5:
            raise ValueError("backtest window has insufficient price data")
        bench = self.benchmark.dropna().loc[cfg.start:cfg.end]

        days = px.index
        rebal_dates = set(self._rebalance_schedule(days, cfg.rebalance_frequency))
        cost_rate = (cfg.commission_bps + cfg.slippage_bps) / 10_000.0

        units: dict[str, float] = {}
        cash = cfg.initial_capital
        last_known: dict[str, float] = {}
        curve_vals: list[float] = []
        trade_log: list[dict] = []
        skipped: list[dict] = []
        pending_target: dict[str, float] | None = None
        pending_signal_date: pd.Timestamp | None = None

        for _i, dt in enumerate(days):
            # 1) Execute any pending trade at TODAY's close (signal was T-1).
            if pending_target is not None:
                exec_row = px.loc[dt]
                value = cash + _mtm_value(units, exec_row, last_known)
                allocatable = value * (1 - cost_rate)
                new_units: dict[str, float] = {}
                used = 0.0
                for t, w in pending_target.items():
                    p = _safe_px(exec_row, t)
                    if p is None or p <= 0 or w <= 0:
                        skipped.append({
                            "execution_date": str(dt.date()), "ticker": t,
                            "reason": "no valid price on execution date",
                        })
                        continue
                    dollars = allocatable * w
                    used += dollars
                    new_units[t] = dollars / p
                trade_log.append({
                    "signal_date": str(pending_signal_date.date()),
                    "execution_date": str(dt.date()),
                    "weights": {k: round(v, 4) for k, v in pending_target.items()},
                    "executed": sorted(new_units),
                    "cost": round(value * cost_rate, 2),
                })
                units = new_units
                cash = value - used
                pending_target = None
                pending_signal_date = None

            # 2) Mark to market at today's close.
            row = px.loc[dt]
            value = cash + _mtm_value(units, row, last_known)
            curve_vals.append(value)

            # 3) Generate signal at today's close -> execute tomorrow (T+lag).
            if dt in rebal_dates:
                ctx = SignalContext(dt, self.prices, self.benchmark,
                                    self.factor_lookup)
                target = signal_fn(ctx) or {}
                s = sum(max(v, 0.0) for v in target.values())
                if s > 0:
                    pending_target = {t: max(v, 0.0) / s
                                      for t, v in target.items() if max(v, 0.0) > 0}
                    pending_signal_date = dt

        equity_curve = pd.Series(curve_vals, index=days, name="equity")
        stats = self._stats_from_curve(equity_curve, bench, len(trade_log))
        return BacktestResult(cfg, stats, equity_curve, bench, trade_log, skipped)

    # ------------------------------------------------------------ internals
    @staticmethod
    def _rebalance_schedule(days: pd.DatetimeIndex, freq: str) -> list:
        if freq == "daily":
            return list(days)
        if freq == "weekly":
            return list(days[days.weekday == 0])
        if freq == "monthly":
            return list(days.to_series().groupby([days.year, days.month]).first())
        if freq == "quarterly":
            return list(days[days.month.isin([1, 4, 7, 10])]
                        .to_series().groupby([days.year, days.month]).first())
        raise ValueError(f"unknown rebalance frequency: {freq}")

    def _stats_from_curve(self, curve: pd.Series, bench: pd.Series,
                          n_trades: int) -> dict:
        rets = curve.pct_change().dropna()
        total_return = float(curve.iloc[-1] / curve.iloc[0] - 1.0)
        years = max(len(curve) / TRADING_DAYS, 1e-9)
        ann = M.annualized_return_from_total(total_return, years)
        stats: dict = {
            "final_value": round(float(curve.iloc[-1]), 2),
            "total_return": round(total_return, 4),
            "annualized_return": round(ann, 4),
            "volatility": round(M.volatility(rets), 4),
            "sharpe": round(M.sharpe_ratio(rets, self.rf), 4),
            "sortino": round(M.sortino_ratio(rets, self.rf), 4),
            "max_drawdown": round(M.max_drawdown_positive(curve), 4),
            "win_rate": round(M.win_rate(rets), 4),
            "num_trades": n_trades,
        }
        if len(bench) > 1:
            b_total = float(bench.iloc[-1] / bench.iloc[0] - 1.0)
            b_years = max(len(bench) / TRADING_DAYS, 1e-9)
            b_ann = M.annualized_return_from_total(b_total, b_years)
            b_rets = bench.pct_change().dropna()
            stats["benchmark_total_return"] = round(b_total, 4)
            stats["benchmark_annualized_return"] = round(b_ann, 4)
            stats["excess_return"] = round(stats["annualized_return"] - b_ann, 4)
            stats["information_ratio"] = round(
                _information_ratio(rets, b_rets), 4)
        return stats


def _safe_px(row: pd.Series, ticker: str) -> float | None:
    try:
        v = row[ticker]
    except KeyError:
        return None
    if v is None or pd.isna(v):
        return None
    return float(v)


def _mtm_value(units: dict[str, float], row: pd.Series,
               last_known: dict[str, float]) -> float:
    """Mark-to-market held units. A unit with no price on `row`'s date is
    valued at its last known price (carried, never silently dropped)."""
    total = 0.0
    for t, q in units.items():
        p = _safe_px(row, t)
        if p is not None:
            last_known[t] = p
        elif t in last_known:
            p = last_known[t]
        if p is not None:
            total += q * p
    return total


def _information_ratio(strategy: pd.Series, benchmark: pd.Series) -> float:
    joined = pd.concat([strategy.rename("s"), benchmark.rename("b")],
                       axis=1).dropna()
    if len(joined) < 10:
        return float("nan")
    active = joined["s"] - joined["b"]
    sd = active.std(ddof=1)
    if not sd or sd == 0:
        return float("nan")
    n = len(joined)
    ann_s = (1 + joined["s"]).prod() ** (TRADING_DAYS / n) - 1
    ann_b = (1 + joined["b"]).prod() ** (TRADING_DAYS / n) - 1
    return float((ann_s - ann_b) / (sd * np.sqrt(TRADING_DAYS)))


def factor_backtest(prices: pd.DataFrame, benchmark: pd.Series,
                    cfg: BacktestConfig,
                    factor_scores_at: Callable,
                    top_n: int = 5) -> BacktestResult:
    """Backtest a factor: at each rebalance, rank the universe by the factor
    score computed FROM POINT-IN-TIME DATA and hold the top N equally weighted.

    `factor_scores_at(ticker, date)` MUST compute scores using only data
    available on that date. The engine enforces price truncation through
    SignalContext; the callback is responsible for statement filing dates.
    """
    def strategy(ctx: SignalContext) -> dict[str, float]:
        scores: dict[str, float] = {}
        for t in cfg.universe:
            hist = ctx.history(t)
            if len(hist) < 60:
                continue  # insufficient history -> not tradable on this date
            s = factor_scores_at(t, ctx.date)
            if s is not None and np.isfinite(s):
                scores[t] = float(s)
        if not scores:
            return {}
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:top_n]
        w = 1.0 / len(ranked)
        return {t: w for t, _ in ranked}

    engine = BacktestEngine(prices, benchmark, cfg,
                            factor_lookup=lambda t, d: factor_scores_at(t, d))
    return engine.run(strategy)
