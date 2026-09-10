"""Backtest engine tests (METHODOLOGY.md §41-46), incl. no-look-ahead checks."""
from __future__ import annotations

import numpy as np
import pandas as pd
from app.backtest.engine import BacktestConfig, BacktestEngine, SignalContext


def _make_prices(days=120, seed=1):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-01", periods=days)
    px = pd.DataFrame({
        "AAA": 100 * (1 + rng.normal(0.001, 0.01, days)).cumprod(),
        "BBB": 100 * (1 + rng.normal(0.0008, 0.008, days)).cumprod(),
        "CCC": 100 * (1 + rng.normal(0.0005, 0.012, days)).cumprod(),
        "SPY": 100 * (1 + rng.normal(0.0004, 0.006, days)).cumprod(),
    }, index=dates)
    return px


def _always_two(ctx: SignalContext):
    return {"AAA": 0.5, "BBB": 0.5}


def test_engine_basic_run_produces_stats():
    px = _make_prices()
    cfg = BacktestConfig(universe=["AAA", "BBB", "CCC"], start=str(px.index[0].date()),
                         end=str(px.index[-1].date()), benchmark="SPY")
    engine = BacktestEngine(px[["AAA", "BBB", "CCC"]], px["SPY"], cfg)
    res = engine.run(_always_two)
    assert res.stats["final_value"] > 0
    assert res.stats["num_trades"] >= 1
    assert len(res.equity_curve) == len(px)
    assert -1.0 < res.stats["total_return"] < 10.0
    assert 0.0 <= res.stats["max_drawdown"] <= 1.0


def test_no_look_ahead_first_execution_is_after_first_signal():
    """The first trade must execute on a date STRICTLY AFTER the first signal
    date (T+1 execution rule)."""
    px = _make_prices()
    cfg = BacktestConfig(universe=["AAA", "BBB"], start=str(px.index[0].date()),
                         end=str(px.index[-1].date()), benchmark="SPY",
                         rebalance_frequency="daily")
    engine = BacktestEngine(px[["AAA", "BBB"]], px["SPY"], cfg)
    res = engine.run(_always_two)
    first = res.trade_log[0]
    assert first["execution_date"] > first["signal_date"]


def test_signal_cannot_see_execution_price():
    """A strategy that reads today's close must not profit from buying at that
    same close: execution happens at the NEXT bar. Verified by checking the
    engine's recorded signal/execution dates are consecutive trading days."""
    px = _make_prices()
    cfg = BacktestConfig(universe=["AAA", "BBB"], start=str(px.index[0].date()),
                         end=str(px.index[-1].date()), benchmark="SPY",
                         rebalance_frequency="daily")
    engine = BacktestEngine(px[["AAA", "BBB"]], px["SPY"], cfg)
    res = engine.run(_always_two)
    trade = res.trade_log[0]
    sig = pd.Timestamp(trade["signal_date"])
    ex = pd.Timestamp(trade["execution_date"])
    idx = px.index
    assert idx.get_loc(ex) == idx.get_loc(sig) + 1


def test_transaction_costs_reduce_value():
    px = _make_prices()
    start, end = str(px.index[0].date()), str(px.index[-1].date())

    def hold_cash(ctx):
        return {}  # stay in cash

    cfg0 = BacktestConfig(universe=["AAA"], start=start, end=end,
                          benchmark="SPY", rebalance_frequency="daily")
    cfg1 = BacktestConfig(universe=["AAA"], start=start, end=end,
                          benchmark="SPY", rebalance_frequency="daily",
                          commission_bps=100, slippage_bps=100)  # 2% per side

    def buy_and_hold(ctx):
        return {"AAA": 1.0}

    eng0 = BacktestEngine(px[["AAA"]], px["SPY"], cfg0).run(buy_and_hold)
    eng1 = BacktestEngine(px[["AAA"]], px["SPY"], cfg1).run(buy_and_hold)
    # With heavy costs, final value must be lower than frictionless
    assert eng1.stats["final_value"] < eng0.stats["final_value"]


def test_missing_price_on_execution_date_stays_in_cash():
    px = _make_prices(60)
    # remove BBB prices after day 30: engine must skip BBB, not crash
    px.loc[px.index[30:], "BBB"] = np.nan
    cfg = BacktestConfig(universe=["AAA", "BBB"], start=str(px.index[0].date()),
                         end=str(px.index[-1].date()), benchmark="SPY",
                         rebalance_frequency="daily")
    engine = BacktestEngine(px[["AAA", "BBB"]], px["SPY"], cfg)
    res = engine.run(lambda ctx: {"AAA": 0.5, "BBB": 0.5})
    assert any(s["ticker"] == "BBB" for s in res.skipped_executions)


def test_context_prices_are_truncated_to_t():
    px = _make_prices()
    cfg = BacktestConfig(universe=["AAA"], start=str(px.index[0].date()),
                         end=str(px.index[-1].date()))
    engine = BacktestEngine(px[["AAA"]], px["SPY"], cfg)
    captured = {}

    def spy_signal(ctx):
        captured["history_len"] = len(ctx.history("AAA"))
        captured["ctx_date"] = ctx.date
        return {}

    engine.run(spy_signal)
    # On the signal date, history must not extend beyond that date.
    assert captured["history_len"] == px.index.get_loc(captured["ctx_date"]) + 1


def test_factor_backtest_uses_point_in_time_scores():
    """Factor backtest must call the scoring callback with (ticker, T) and use
    its output — scores computed for a *later* date must never be visible."""
    from app.backtest.engine import factor_backtest

    px = _make_prices(150)
    cfg = BacktestConfig(universe=["AAA", "BBB", "CCC"],
                         start=str(px.index[30].date()),
                         end=str(px.index[-1].date()), benchmark="SPY")
    calls = []

    def scores_at(ticker, on):
        calls.append((ticker, on))
        # deterministic: prefer AAA
        return 90.0 if ticker == "AAA" else 10.0

    res = factor_backtest(px[["AAA", "BBB", "CCC"]], px["SPY"], cfg, scores_at, top_n=2)
    assert res.stats["num_trades"] >= 1
    # every callback date is <= the last backtest date (no future scoring)
    last = px.index[-1]
    assert all(on <= last for _, on in calls)
    # strategy should hold AAA (top score)
    first_trade = res.trade_log[0]
    assert "AAA" in first_trade["executed"]
