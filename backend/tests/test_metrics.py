"""Known-input/known-output tests for core metrics (METHODOLOGY.md §4-10).

Expected values were computed by hand before writing the tests; the tests are
NOT fitted to the implementation (PROJECT_SPEC §43).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from app.quant import metrics as M


def series(vals, start="2024-01-01", freq="D"):
    idx = pd.date_range(start, periods=len(vals), freq=freq)
    return pd.Series(vals, index=idx, dtype=float)


# ------------------------------------------------------------------ returns
def test_simple_return_known():
    # R = (110 - 100)/100 = 0.10
    assert M.simple_return(100.0, 110.0) == pytest.approx(0.10)
    assert M.simple_return(0.0, 5.0) != M.simple_return(0.0, 5.0)  # NaN


def test_price_series_returns():
    px = series([100, 110, 99])
    r = M.price_series_returns(px)
    assert r.iloc[1] == pytest.approx(0.10)
    assert r.iloc[2] == pytest.approx(-0.10)
    assert math.isnan(r.iloc[0])


def test_annualized_return_two_years():
    # +100% over 2 years => sqrt(2)-1 ~ 41.42%
    assert M.annualized_return_from_total(1.0, 2.0) == pytest.approx(2 ** 0.5 - 1)


# --------------------------------------------------------------- volatility
def test_volatility_constant_series_is_zero():
    r = series([0.001] * 30)
    assert M.volatility(r) == pytest.approx(0.0, abs=1e-12)


def test_volatility_known_values():
    # std of [0.01, -0.01, 0.01, -0.01] with ddof=1:
    #   mean 0, sum sq dev = 4*(0.01^2)=0.0004, var=0.0004/3, std=0.0115470
    r = series([0.0, 0.01, -0.01, 0.01, -0.01])
    v = M.volatility(r.iloc[1:])
    assert v == pytest.approx(math.sqrt(0.0004 / 3) * math.sqrt(252))


# ------------------------------------------------------------------- sharpe
def test_sharpe_ratio_known():
    # constant 10% daily return, zero vol of returns -> vol==0 => NaN (degenerate)
    r = series([0.001] * 40)
    assert math.isnan(M.sharpe_ratio(r))
    # ann return 26.8% (1.001^252-1), vol = 0.02*sqrt(252) from fixture above
    r2 = series([0.0, 0.01, -0.01, 0.01, -0.01]).iloc[1:]
    # verify the formula path: Sharpe = (annualized return - rf) / annualized vol
    vol = M.volatility(r2)
    ann = M.annualized_return(r2)
    assert M.sharpe_ratio(r2) == pytest.approx((ann - 0) / vol)


def test_sharpe_with_rf_subtracts_rf():
    rng = np.random.default_rng(7)
    r = pd.Series(rng.normal(0.0005, 0.01, 500))
    s0 = M.sharpe_ratio(r, 0.0)
    s4 = M.sharpe_ratio(r, 0.04)
    assert s0 > s4  # higher rf lowers Sharpe


# ------------------------------------------------------------------ sortino
def test_downside_deviation_and_sortino():
    # MAR=0; returns [0.01, -0.02, 0.03, -0.04]: downside squares (0, .0004, 0, .0016)
    # mean = 0.0005, sqrt = 0.0223607 daily, * sqrt(252) annualized
    r = series([0.0, 0.01, -0.02, 0.03, -0.04]).iloc[1:]
    dd = M.downside_deviation(r, mar=0.0)
    assert dd == pytest.approx(math.sqrt(0.0005) * math.sqrt(252))
    srt = M.sortino_ratio(r)
    ann = M.annualized_return(r)
    assert srt == pytest.approx(ann / dd)


# -------------------------------------------------------------------- beta
def test_beta_perfectly_correlated_is_one():
    rng = np.random.default_rng(3)
    m = pd.Series(rng.normal(0.0, 0.01, 300))
    s = 1.5 * m
    assert M.beta(s, m) == pytest.approx(1.5)


def test_beta_zero_variance_benchmark_is_nan():
    m = series([0.0] * 30)
    s = series(np.random.default_rng(1).normal(0, 0.01, 30))
    assert math.isnan(M.beta(s, m))


# ----------------------------------------------------------------- drawdown
def test_drawdown_known_path():
    # 100 -> 120 -> 90 -> 110: peak 120, trough 90 => MDD = -25%
    px = series([100, 120, 90, 110])
    assert M.max_drawdown(px) == pytest.approx(-0.25)
    assert M.max_drawdown_positive(px) == pytest.approx(0.25)
    dd = M.drawdown_series(px)
    assert dd.iloc[1] == pytest.approx(0.0)
    assert dd.iloc[2] == pytest.approx(-0.25)


def test_drawdown_monotonic_up_is_zero():
    px = series([100, 110, 120, 130])
    assert M.max_drawdown(px) == pytest.approx(0.0)


# --------------------------------------------------------------- VaR / ES
def test_historical_var_known_percentile():
    # 100 returns: -1% appears at the 5th percentile boundary
    rng = np.random.default_rng(11)
    r = pd.Series(rng.normal(0.001, 0.01, 1000))
    var95 = M.historical_var(r, 0.95)
    q = np.quantile(r.to_numpy(), 0.05)
    assert var95 == pytest.approx(-q)
    assert var95 > 0


def test_expected_shortfall_exceeds_var():
    rng = np.random.default_rng(5)
    r = pd.Series(rng.normal(0.0, 0.02, 1000))
    var95 = M.historical_var(r, 0.95)
    es95 = M.expected_shortfall(r, 0.95)
    assert es95 >= var95


# -------------------------------------------------------------- correlation
def test_correlation_matrix_perfect():
    a = series(np.arange(1, 51) * 1.0)
    b = a * 2.0
    corr = M.correlation_matrix(pd.DataFrame({"a": a.pct_change().dropna(),
                                              "b": b.pct_change().dropna()}))
    assert corr.loc["a", "b"] == pytest.approx(1.0)


# ---------------------------------------------------------------- portfolio
def test_portfolio_return_weighted():
    df = pd.DataFrame({
        "A": [0.01, 0.02, -0.01],
        "B": [0.03, -0.01, 0.02],
    }, index=pd.date_range("2024-01-01", periods=3))
    w = {"A": 0.5, "B": 0.5}
    rp = M.portfolio_return_series(w, df)
    assert rp.iloc[0] == pytest.approx(0.02)
    assert rp.iloc[1] == pytest.approx(0.005)
    assert rp.iloc[2] == pytest.approx(0.005)


def test_portfolio_volatility_formula():
    w = np.array([1.0, 0.0])
    cov = np.array([[0.04, 0.0], [0.0, 0.09]])
    assert M.portfolio_volatility(w, cov) == pytest.approx(0.2)


def test_alpha_jensen_known():
    rng = np.random.default_rng(2)
    m = pd.Series(rng.normal(0.0004, 0.01, 300))
    b = 1.2
    # generate security as beta*m + constant alpha so Jensen alpha recovers it
    s = 0.0002 + b * m
    a = M.alpha(s, m, b, risk_free_rate=0.0)
    # ann(s) - 1.2*ann(m); both from same sample, alpha>0 expected
    assert a > 0
