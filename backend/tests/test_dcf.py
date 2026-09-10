"""DCF tests (METHODOLOGY.md §24-28) with hand-computed expected values."""
from __future__ import annotations

import pytest
from app.errors import InvalidAssumptionError
from app.valuation.dcf import DCFAssumptions, run_dcf, sensitivity_table


def flat_assumptions(**over):
    base = {
        "base_revenue": 1000.0,
        "revenue_growth": [0.10] * 5,
        "ebit_margin": 0.20,
        "tax_rate": 0.25,
        "capex_pct_revenue": 0.05,
        "depreciation_pct_revenue": 0.03,
        "wc_change_pct_revenue": 0.01,
        "wacc": 0.10,
        "terminal_growth": 0.02,
        "net_debt": 100.0,
        "shares_diluted": 10.0,
        "current_price": 50.0,
    }
    base.update(over)
    return DCFAssumptions(**base)


def hand_computed_case():
    """Fully hand-checkable 2-year DCF.

    Revenue: 1000 -> 1100 -> 1210. EBIT margin 20%, tax 25% => NOPAT = EBIT*.75
    D&A 3% rev, CapEx 5% rev, dWC 1% rev => FCF = rev*(0.20*.75 + .03 - .05 - .01)
                                               = rev * 0.12
    FCF1 = 132.0, FCF2 = 145.2; WACC 10% => PV = 132/1.1 + 145.2/1.21 = 240.0
    TV = 145.2*1.02 / (0.10-0.02) = 1851.3; PV(TV) = 1851.3/1.21 = 1530.0
    EV = 1770.0; Equity = 1670.0; Fair/sh = 167.0
    """
    a = flat_assumptions(revenue_growth=[0.10, 0.10], wacc=0.10,
                         terminal_growth=0.02, net_debt=100.0,
                         shares_diluted=10.0)
    return a, 1670.0, 167.0


def test_dcf_hand_computed():
    a, equity_expected, fair_expected = hand_computed_case()
    r = run_dcf(a, years=2)
    assert r.enterprise_value == pytest.approx(1770.0, rel=1e-9)
    assert r.equity_value == pytest.approx(equity_expected, rel=1e-9)
    assert r.fair_value_per_share == pytest.approx(fair_expected, rel=1e-9)
    # explicit PV check: 132/1.1 + 145.2/1.21
    assert r.pv_explicit == pytest.approx(132.0 / 1.1 + 145.2 / 1.21, rel=1e-9)
    assert r.pv_terminal == pytest.approx(1851.3 / 1.21, rel=1e-9)
    # upside vs price 50: (167-50)/50
    assert r.upside == pytest.approx((167.0 - 50.0) / 50.0, rel=1e-9)


def test_dcf_terminal_growth_must_be_below_wacc():
    with pytest.raises(InvalidAssumptionError):
        run_dcf(flat_assumptions(terminal_growth=0.10), years=2)
    with pytest.raises(InvalidAssumptionError):
        run_dcf(flat_assumptions(terminal_growth=0.12, wacc=0.10), years=2)


def test_dcf_invalid_assumptions_rejected():
    with pytest.raises(InvalidAssumptionError):
        run_dcf(flat_assumptions(base_revenue=0.0))
    with pytest.raises(InvalidAssumptionError):
        run_dcf(flat_assumptions(tax_rate=1.0))
    with pytest.raises(InvalidAssumptionError):
        run_dcf(flat_assumptions(shares_diluted=0))


def test_dcf_negative_net_debt_adds_cash():
    # net debt = -200 (net cash): equity = EV + 200
    a = flat_assumptions(revenue_growth=[0.10, 0.10], net_debt=-200.0)
    r = run_dcf(a, years=2)
    assert r.equity_value == pytest.approx(1770.0 + 200.0, rel=1e-9)


def test_sensitivity_table_rejects_g_ge_wacc():
    a = flat_assumptions(revenue_growth=[0.10, 0.10])
    wacc_axis = [0.06, 0.08, 0.10]
    g_axis = [0.02, 0.05, 0.07]
    table = sensitivity_table(a, wacc_axis, g_axis, years=2)
    # g=0.07 >= wacc=0.06 -> None cell
    assert table["values"][0][2] is None
    # corner check: (wacc=0.10, g=0.02) must equal the hand-computed 167.00
    assert table["values"][2][0] == pytest.approx(167.0, abs=0.01)
    assert (0.06, 0.07) in [tuple(x) for x in table["rejected_cells"]]


def test_sensitivity_center_matches_base_case():
    a = flat_assumptions(revenue_growth=[0.10] * 5)
    table = sensitivity_table(a, [0.08, 0.10, 0.12], [0.01, 0.02, 0.03], years=5)
    center = table["values"][1][1]
    base = run_dcf(flat_assumptions(), years=5)
    assert center == pytest.approx(round(base.fair_value_per_share, 2), abs=0.01)
