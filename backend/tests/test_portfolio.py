"""Portfolio analytics + optimizer tests (METHODOLOGY.md §31-37)."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from app.errors import CalculationError
from app.portfolio.optimizer import covariance_from_prices, optimize

from app.portfolio import analytics as P


def _mock_prices(tickers: list[str], days: int = 400, seed: int = 9):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-01", periods=days)
    out = {}
    for i, t in enumerate(tickers):
        rets = rng.normal(0.0006 + 0.0002 * i, 0.012 - 0.002 * i, days)
        out[t] = pd.Series(100 * np.cumprod(1 + rets), index=dates)
    return out


def test_portfolio_stats_known_degenerate():
    # constant positive daily return: vol ~ 0 (ddof=1 of identical values = 0)
    r = pd.Series([0.001] * 100, index=pd.bdate_range("2024-01-01", periods=100))
    s = P.portfolio_stats(r, risk_free_rate=0.0)
    assert s["volatility"] == pytest.approx(0.0, abs=1e-9)
    assert math.isnan(s["sharpe"])          # 0/0 -> NaN, never fabricated
    assert s["win_rate"] == pytest.approx(1.0)
    assert s["var_95_daily"] == pytest.approx(0.0, abs=1e-9)


def test_portfolio_stats_with_benchmark():
    rng = np.random.default_rng(4)
    b = pd.Series(rng.normal(0.0003, 0.01, 300))
    s = 1.3 * b + 0.0002
    stats = P.portfolio_stats(s, b, risk_free_rate=0.0)
    assert stats["beta"] == pytest.approx(1.3, abs=0.05)
    assert stats["alpha"] > 0


def test_equity_curve_compounds():
    r = pd.Series([0.10, -0.10], index=pd.bdate_range("2024-01-01", periods=2))
    curve = P.equity_curve(r, 100.0)
    assert curve.iloc[-1] == pytest.approx(100 * 1.1 * 0.9)


def test_correlation_analysis_flags_high_pairs():
    px = _mock_prices(["AAA", "BBB"], days=300, seed=5)
    # BBB perfectly tracks AAA -> correlation ~ 1
    px["BBB"] = px["AAA"] * 1.1
    res = P.correlation_analysis(px, lookback_days=250)
    assert res["matrix"]["AAA"]["BBB"] > 0.99
    assert len(res["highly_correlated"]) == 1
    assert res["pairs_sorted"][0]["correlation"] > 0.99


# ------------------------------------------------------------- optimization
def test_optimizer_max_sharpe_concentrates_on_best_asset():
    px = _mock_prices(["LOW", "MID", "HIGH"], days=400, seed=9)
    mu, cov = covariance_from_prices(px)
    res = optimize(mu, cov, "max_sharpe", max_position=0.60)
    assert abs(sum(res["weights"].values()) - 1.0) < 1e-6
    assert all(w >= 0 for w in res["weights"].values())
    # the highest-Sharpe asset should get the largest weight
    assert max(res["weights"], key=res["weights"].get) == "HIGH"


def test_optimizer_min_volatility_spreads():
    # two uncorrelated assets, identical vol -> min vol is exactly 50/50
    mu = pd.Series({"A": 0.10, "B": 0.10})
    cov = pd.DataFrame({"A": [0.04, 0.0], "B": [0.0, 0.04]}, index=["A", "B"])
    res = optimize(mu, cov, "min_volatility", max_position=0.5)
    assert res["weights"]["A"] == pytest.approx(0.5, abs=0.01)
    assert res["expected_volatility"] == pytest.approx(
        math.sqrt(0.5 * 0.5 * 0.04 * 2), rel=1e-3)


def test_optimizer_target_return_constraint():
    px = _mock_prices(["AAA", "BBB", "CCC"], days=400, seed=3)
    mu, cov = covariance_from_prices(px)
    res = optimize(mu, cov, "target_return", max_position=0.5,
                   target_return=float(mu.min()))
    assert abs(sum(res["weights"].values()) - 1.0) < 1e-6
    # portfolio expected return must meet the target
    assert res["expected_return"] >= float(mu.min()) - 1e-6


def test_optimizer_validates_constraints():
    px = _mock_prices(["AAA", "BBB"], days=200, seed=1)
    mu, cov = covariance_from_prices(px)
    with pytest.raises(CalculationError):
        optimize(mu, cov, "bogus_objective")
    with pytest.raises(CalculationError):
        optimize(mu, cov, "max_sharpe", max_position=0.4)  # 0.4*2 < 1
    with pytest.raises(CalculationError):
        optimize(mu.loc[["AAA"]], cov, "max_sharpe")  # single asset
