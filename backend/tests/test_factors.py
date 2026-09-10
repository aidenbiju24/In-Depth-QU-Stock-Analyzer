"""Factor scoring tests (METHODOLOGY.md §11-22) with hand-checked anchors."""
from __future__ import annotations

import math

import pandas as pd
import pytest
from app.quant.factors import (
    FACTOR_WEIGHTS,
    METRICS_BY_NAME,
    compute_factor_scores,
    quant_score_interpretation,
    score_absolute,
    score_universe,
)


def test_score_absolute_anchors():
    pe = METRICS_BY_NAME["pe"]  # lower better, band [8, 30]
    assert score_absolute(pe, 8.0) == pytest.approx(100.0)
    assert score_absolute(pe, 30.0) == pytest.approx(0.0)
    assert score_absolute(pe, 19.0) == pytest.approx(100 * (30 - 19) / (30 - 8))
    # clamped outside band
    assert score_absolute(pe, 2.0) == pytest.approx(100.0)
    assert score_absolute(pe, 100.0) == pytest.approx(0.0)
    # missing
    assert math.isnan(score_absolute(pe, None))


def test_score_absolute_higher_better():
    roe = METRICS_BY_NAME["roe"]  # higher better, band [0, 0.25]
    assert score_absolute(roe, 0.0) == pytest.approx(0.0)
    assert score_absolute(roe, 0.125) == pytest.approx(50.0)
    assert score_absolute(roe, 0.25) == pytest.approx(100.0)


def test_composite_weighted_mean():
    # All five factors at known scores -> QS must equal weighted mean.
    raw = {
        # value metrics at band midpoints -> ~50 each
        "pe": 19.0, "forward_pe": 22.5, "pb": 4.5, "ps": 5.5,
        "ev_ebitda": 13.0, "fcf_yield": 0.04, "earnings_yield": 0.05,
        # growth at midpoints
        "revenue_growth_1y": 0.10, "revenue_cagr_3y": 0.09,
        "eps_growth_1y": 0.075, "fcf_growth_1y": 0.075,
        "op_income_growth_1y": 0.075, "margin_expansion": 0.005,
        # quality at midpoints
        "roe": 0.125, "roic": 0.10, "gross_margin": 0.35,
        "operating_margin": 0.16, "net_margin": 0.13, "fcf_margin": 0.075,
        "debt_to_equity": 1.125, "interest_coverage": 11.5,
        "earnings_consistency": 0.75,
        # momentum at midpoints
        "momentum_1m": 0.0, "momentum_3m": 0.025, "momentum_6m": 0.05,
        "momentum_12m": 0.05, "momentum_consistency": 0.575,
        "rel_strength_12m": 0.025,
        # risk at midpoints
        "annual_volatility": 0.375, "beta_deviation": 0.40,
        "max_drawdown_mag": 0.325, "sharpe": 0.5,
        "downside_deviation": 0.275,
    }
    r = compute_factor_scores(raw, ticker="TEST", as_of="2025-01-01")
    # every factor should be present with full coverage
    assert set(r.factor_scores) == {"value", "growth", "quality", "momentum", "risk"}
    assert r.coverage["value"] == pytest.approx(1.0)
    qs = sum(FACTOR_WEIGHTS[f] * r.factor_scores[f] for f in FACTOR_WEIGHTS)
    assert r.quant_score == pytest.approx(qs, abs=0.2)
    assert 0.0 <= r.quant_score <= 100.0


def test_missing_metric_weight_redistribution():
    # Provide only half of value metrics -> value factor still scores with
    # reduced coverage; others unchanged.
    full = {
        "pe": 19.0, "forward_pe": 22.5, "pb": 4.5, "ps": 5.5,
        "ev_ebitda": 13.0, "fcf_yield": 0.04, "earnings_yield": 0.05,
    }
    half = {"pe": 19.0, "forward_pe": 22.5, "pb": 4.5, "ps": 5.5}
    r_full = compute_factor_scores(full, ticker="A", as_of="2025-01-01")
    r_half = compute_factor_scores(half, ticker="A", as_of="2025-01-01")
    assert r_half.coverage["value"] < r_full.coverage["value"]
    assert "ev_ebitda" in r_half.missing
    # 'pe' at band midpoint scores 50 in both cases (weight renormalized)
    assert r_half.metric_scores["pe"] == pytest.approx(
        r_full.metric_scores["pe"])


def test_factor_below_min_coverage_excluded():
    raw = {"pe": 19.0}  # only 20% of value weight
    r = compute_factor_scores(raw, ticker="A", as_of="2025-01-01")
    assert "value" not in r.factor_scores
    assert math.isnan(r.quant_score)


def test_never_zero_fill_missing():
    r = compute_factor_scores({}, ticker="A", as_of="2025-01-01")
    assert r.raw_inputs["pe"] is None
    assert math.isnan(r.quant_score)


def test_score_universe_percentile_ranking():
    df = pd.DataFrame(
        {
            "pe": [8.0, 19.0, 30.0, 12.0, 25.0],
            "momentum_12m": [0.40, 0.05, -0.30, 0.20, -0.10],
        },
        index=["CHEAP", "MID", "RICH", "OK1", "OK2"],
    )
    out = score_universe(df)
    # lower pe is better: CHEAP best percentile, RICH worst
    assert out.loc["CHEAP", "pe"] > out.loc["RICH", "pe"]
    # higher momentum better
    assert out.loc["CHEAP", "momentum_12m"] > out.loc["RICH", "momentum_12m"]
    assert out["quant_score"].between(0, 100).all()


def test_interpretation_bands():
    assert quant_score_interpretation(95) == "Exceptional"
    assert quant_score_interpretation(85) == "Strong"
    assert quant_score_interpretation(55) == "Neutral"
    assert quant_score_interpretation(10) == "Poor"
    assert quant_score_interpretation(float("nan")) == "Insufficient data"
