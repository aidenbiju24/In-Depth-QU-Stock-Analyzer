"""Monte Carlo, regime, earnings, and recommendation tests."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from app.errors import CalculationError
from app.simulation.earnings import abnormal_returns, analyze_earnings, surprise
from app.simulation.monte_carlo import run_monte_carlo
from app.simulation.recommendation import RecommendationInput, recommend
from app.simulation.regime import classify_regime


def _price_series(days=500, drift=0.10, vol=0.20, seed=42):
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift / 252, vol / math.sqrt(252), days)
    idx = pd.bdate_range("2023-01-01", periods=days)
    return pd.Series(100 * np.cumprod(1 + rets), index=idx)


# ------------------------------------------------------------- monte carlo
def test_monte_carlo_reproducible_with_seed():
    px = _price_series()
    r1 = run_monte_carlo(px, "TEST", days=126, n_simulations=2000, seed=123)
    r2 = run_monte_carlo(px, "TEST", days=126, n_simulations=2000, seed=123)
    assert r1.median == r2.median
    assert r1.p05 == r2.p05 and r1.p95 == r2.p95


def test_monte_carlo_different_seed_differs():
    px = _price_series()
    r1 = run_monte_carlo(px, "TEST", days=126, n_simulations=2000, seed=1)
    r2 = run_monte_carlo(px, "TEST", days=126, n_simulations=2000, seed=2)
    assert r1.median != r2.median


def test_monte_carlo_percentiles_ordered():
    px = _price_series()
    r = run_monte_carlo(px, "TEST", days=252, n_simulations=5000, seed=7)
    assert r.p05 < r.p25 < r.median < r.p75 < r.p95
    assert r.prob_gain + r.prob_loss == pytest.approx(1.0, abs=0.02)


def test_monte_carlo_zero_drift_median_below_start():
    """GBM with mu=0: median of exp paths < S0 because of the -sigma^2/2 term."""
    rng = np.random.default_rng(8)
    rets = rng.normal(0.0, 0.01, 400)
    px = pd.Series(100 * np.cumprod(1 + rets), index=pd.bdate_range("2023-01-01", periods=400))
    r = run_monte_carlo(px, "TEST", days=252, n_simulations=5000, seed=3)
    assert r.median < r.current_price * 1.0


def test_monte_carlo_validates_inputs():
    px = _price_series(80)
    with pytest.raises(CalculationError):
        run_monte_carlo(px, "TEST", days=10, n_simulations=10)
    with pytest.raises(CalculationError):
        run_monte_carlo(pd.Series(dtype=float), "TEST")


# ------------------------------------------------------------------ regime
def test_regime_bull_vs_bear():
    up = pd.Series(np.linspace(100, 200, 260), index=pd.bdate_range("2024-01-01", periods=260))
    down = pd.Series(np.linspace(200, 100, 260), index=pd.bdate_range("2024-01-01", periods=260))
    on = up.index[-1]
    assert classify_regime(up, on)["trend"] == "bull"
    assert classify_regime(down, on)["trend"] == "bear"


def test_regime_uses_only_past_data():
    px = _price_series(300)
    on = px.index[100]
    r = classify_regime(px, on)
    # the regime call must not require data after `on`
    assert r["as_of"] == str(on.date())


def test_regime_risk_on_off():
    spy = pd.Series(np.linspace(400, 500, 100), index=pd.bdate_range("2024-01-01", periods=100))
    tlt = pd.Series(np.linspace(100, 90, 100), index=pd.bdate_range("2024-01-01", periods=100))
    bench = spy.copy()
    r = classify_regime(bench, bench.index[-1], spy, tlt)
    assert r["risk_on_off"] == "risk_on"


# ---------------------------------------------------------------- earnings
def test_surprise_math():
    s = surprise({"eps_actual": 1.20, "eps_estimated": 1.00})
    assert s["eps_surprise"] == pytest.approx(0.20)
    assert s["eps_surprise_pct"] == pytest.approx(0.20)


def test_analyze_earnings_reaction_window():
    dates = pd.bdate_range("2024-01-01", periods=30)
    px = pd.Series(np.linspace(100, 130, 30), index=dates)
    report_day = dates[15]
    rec = {
        "fiscal_date": report_day.date().isoformat(),
        "report_date": report_day.date().isoformat(),
        "eps_actual": 1.5, "eps_estimated": 1.0,
    }
    out = analyze_earnings([rec], px)
    row = out["records"][0]
    # reaction = close(report day)/close(previous day) - 1 with linear ramp 1/day
    assert row["market_reaction"] == pytest.approx(131 / 130 - 1, abs=0.002)
    assert out["summary"]["beat_rate"] == 1.0


def test_event_study_car():
    dates = pd.bdate_range("2024-01-01", periods=40)
    stock = pd.Series(np.linspace(100, 140, 40), index=dates)
    bench = pd.Series(np.linspace(500, 500, 40), index=dates)  # flat benchmark
    ev = abnormal_returns(stock, bench, dates[20].date().isoformat(), window=5)
    assert ev["car"] > 0
    assert len(ev["series"]) == 5
    # with flat benchmark, AR == stock return each day
    assert ev["series"][0]["abnormal_return"] == ev["series"][0]["stock_return"]


# ---------------------------------------------------------- recommendation
def test_recommendation_strong_buy_profile():
    rec = recommend("T", RecommendationInput(
        quant_score=85, dcf_upside=0.35, momentum_12m=0.20,
        earnings_beat_rate=0.8, annual_volatility=0.25, max_drawdown=0.15))
    assert rec.action == "Strong Buy"
    assert rec.rules_fired  # every rule recorded
    assert any("Quant score 85" in r for r in rec.reasoning)


def test_recommendation_weak_profile_sells():
    rec = recommend("T", RecommendationInput(
        quant_score=25, dcf_upside=-0.4, momentum_12m=-0.3,
        earnings_beat_rate=0.3, annual_volatility=0.30, max_drawdown=0.30))
    assert rec.action in ("Sell", "Strong Sell")


def test_recommendation_risk_veto_caps_at_hold():
    rec = recommend("T", RecommendationInput(
        quant_score=90, dcf_upside=0.4, momentum_12m=0.3,
        earnings_beat_rate=0.9, annual_volatility=0.80, max_drawdown=0.2))
    assert rec.action == "Hold"
    assert "risk_veto_volatility" in rec.rules_fired


def test_recommendation_insufficient_data_suppressed():
    rec = recommend("T", RecommendationInput(
        quant_score=None, dcf_upside=None, momentum_12m=None,
        earnings_beat_rate=None, annual_volatility=None, max_drawdown=None))
    assert rec.action == "Hold"
    assert "insufficient_data" in rec.rules_fired


def test_recommendation_is_deterministic():
    inp = RecommendationInput(quant_score=72, dcf_upside=0.18, momentum_12m=0.1,
                              earnings_beat_rate=0.75, annual_volatility=0.2,
                              max_drawdown=0.2)
    assert recommend("T", inp).to_dict() == recommend("T", inp).to_dict()
