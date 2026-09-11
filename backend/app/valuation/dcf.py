"""DCF valuation engine (METHODOLOGY.md §24-28).

Model: unlevered FCFF DCF with a Gordon-growth terminal value.

  FCF_t = Revenue_t * EBIT_margin_t * (1 - tax) + D&A_t - CapEx_t - ΔWC_t
  PV(FCF)  = sum FCF_t / (1+WACC)^t
  TV       = FCF_{n+1} / (WACC - g),  FCF_{n+1} = FCF_n * (1+g)     (§24)
  EV       = PV(FCF) + PV(TV)
  Equity   = EV - Debt + Cash                                      (§24)
  Fair/sh  = Equity / diluted shares                                (§24)
  Upside   = (Fair - Price) / Price                                 (§28)

Rejects g >= WACC (§26) and non-positive projected FCF paths that would make
the Gordon formula financially meaningless (flagged, not silently scored).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..errors import InvalidAssumptionError

DCF_MODEL_VERSION = "1.0"


@dataclass
class DCFAssumptions:
    base_revenue: float
    revenue_growth: list[float]            # one per explicit year
    ebit_margin: list[float] | float       # per explicit year (or scalar)
    tax_rate: float
    capex_pct_revenue: list[float] | float
    depreciation_pct_revenue: list[float] | float
    wc_change_pct_revenue: list[float] | float
    wacc: float
    terminal_growth: float
    net_debt: float                        # total debt - cash
    shares_diluted: float
    current_price: float | None = None

    def validate(self) -> None:
        if self.base_revenue <= 0:
            raise InvalidAssumptionError("base_revenue must be positive")
        if not (0 <= self.tax_rate < 1):
            raise InvalidAssumptionError("tax_rate must be in [0, 1)")
        if self.wacc <= 0:
            raise InvalidAssumptionError("WACC must be positive")
        if self.terminal_growth >= self.wacc:
            raise InvalidAssumptionError(
                f"terminal growth ({self.terminal_growth:.3f}) must be below "
                f"WACC ({self.wacc:.3f}) — Gordon growth is invalid otherwise")
        if self.shares_diluted <= 0:
            raise InvalidAssumptionError("shares_diluted must be positive")


@dataclass
class DCFResult:
    fair_value_per_share: float
    enterprise_value: float
    equity_value: float
    pv_explicit: float
    pv_terminal: float
    terminal_value: float
    projected: list[dict] = field(default_factory=list)
    upside: float | None = None
    warnings: list[str] = field(default_factory=list)


def run_dcf(a: DCFAssumptions, years: int = 5) -> DCFResult:
    a.validate()
    years = max(1, int(years))
    warnings: list[str] = []

    growth = a.revenue_growth[:years]
    margin = (a.ebit_margin if isinstance(a.ebit_margin, list)
              else [a.ebit_margin] * years)
    capex = (a.capex_pct_revenue if isinstance(a.capex_pct_revenue, list)
             else [a.capex_pct_revenue] * years)
    dep = (a.depreciation_pct_revenue if isinstance(a.depreciation_pct_revenue, list)
           else [a.depreciation_pct_revenue] * years)
    dwc = (a.wc_change_pct_revenue if isinstance(a.wc_change_pct_revenue, list)
           else [a.wc_change_pct_revenue] * years)

    projected: list[dict] = []
    pv_explicit = 0.0
    revenue = a.base_revenue
    for t in range(years):
        revenue *= (1 + growth[t])
        ebit = revenue * margin[t]
        nopat = ebit * (1 - a.tax_rate)
        da = revenue * dep[t]
        capex_t = revenue * capex[t]
        dwc_t = revenue * dwc[t]
        fcf = nopat + da - capex_t - dwc_t
        disc = (1 + a.wacc) ** (t + 1)
        pv = fcf / disc
        pv_explicit += pv
        projected.append({
            "year": t + 1, "revenue": revenue, "ebit": ebit, "nopat": nopat,
            "d_and_a": da, "capex": capex_t, "wc_change": dwc_t,
            "fcf": fcf, "discount_factor": disc, "pv_fcf": pv,
        })

    final_fcf = projected[-1]["fcf"]
    if final_fcf <= 0:
        warnings.append(
            "final explicit-year FCF is non-positive; terminal value is not "
            "economically meaningful — treat output as invalid")
    fcf_n1 = final_fcf * (1 + a.terminal_growth)
    tv = fcf_n1 / (a.wacc - a.terminal_growth)
    pv_tv = tv / (1 + a.wacc) ** years
    ev = pv_explicit + pv_tv
    equity = ev - a.net_debt
    fair = equity / a.shares_diluted

    upside = None
    if a.current_price:
        upside = (fair - a.current_price) / a.current_price

    return DCFResult(
        fair_value_per_share=fair,
        enterprise_value=ev,
        equity_value=equity,
        pv_explicit=pv_explicit,
        pv_terminal=pv_tv,
        terminal_value=tv,
        projected=projected,
        upside=upside,
        warnings=warnings,
    )


def sensitivity_table(a: DCFAssumptions, wacc_range: list[float],
                      growth_range: list[float], years: int = 5) -> dict:
    """WACC x terminal-growth fair-value table (METHODOLOGY §27).

    Cells where g >= WACC return None (rejected combinations, per §26).
    """
    table: list[list[float | None]] = []
    rejected: list[tuple[float, float]] = []
    for w in wacc_range:
        row: list[float | None] = []
        for g in growth_range:
            if g >= w:
                row.append(None)
                rejected.append((round(w, 4), round(g, 4)))
                continue
            a2 = DCFAssumptions(
                base_revenue=a.base_revenue, revenue_growth=a.revenue_growth,
                ebit_margin=a.ebit_margin, tax_rate=a.tax_rate,
                capex_pct_revenue=a.capex_pct_revenue,
                depreciation_pct_revenue=a.depreciation_pct_revenue,
                wc_change_pct_revenue=a.wc_change_pct_revenue,
                wacc=w, terminal_growth=g, net_debt=a.net_debt,
                shares_diluted=a.shares_diluted, current_price=None,
            )
            row.append(round(run_dcf(a2, years).fair_value_per_share, 2))
        table.append(row)
    return {"wacc_axis": wacc_range, "growth_axis": growth_range,
            "values": table, "rejected_cells": rejected}
