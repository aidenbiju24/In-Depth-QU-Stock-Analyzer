"""Normalized internal schemas.

Providers must map their raw responses into these dataclasses. Everything
downstream (quant engine, valuation, portfolio, backtest) consumes ONLY these
types — never provider-specific payload shapes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Company:
    ticker: str
    name: str | None = None
    exchange: str | None = None
    sector: str | None = None
    industry: str | None = None
    currency: str | None = None
    description: str | None = None
    source: str | None = None


@dataclass
class PriceBar:
    date: date
    open: float | None = None
    high: float | None = None
    low: float | None = None
    close: float | None = None
    adj_close: float | None = None
    volume: float | None = None


@dataclass
class Statement:
    """One normalized financial statement (income / balance / cashflow)."""

    ticker: str
    statement: str            # income | balance | cashflow
    period: str               # annual | quarterly
    fiscal_date: date         # fiscal period end (observation date)
    filing_date: date | None  # when it became public (point-in-time rule)
    currency: str | None
    items: dict[str, float | None] = field(default_factory=dict)


@dataclass
class Fundamentals:
    """Point-in-time fundamental snapshot used by factors and DCF."""

    ticker: str
    as_of: date
    market_cap: float | None = None
    pe: float | None = None
    forward_pe: float | None = None
    pb: float | None = None
    ps: float | None = None
    ev_ebitda: float | None = None
    dividend_yield: float | None = None
    beta_5y: float | None = None
    eps: float | None = None
    eps_diluted: float | None = None
    shares_diluted: float | None = None
    book_value_per_share: float | None = None
    revenue_ttm: float | None = None
    net_income_ttm: float | None = None
    ebitda_ttm: float | None = None
    free_cash_flow_ttm: float | None = None
    operating_cash_flow_ttm: float | None = None
    capex_ttm: float | None = None
    total_debt: float | None = None
    total_cash: float | None = None
    total_equity: float | None = None
    total_assets: float | None = None
    gross_profit_ttm: float | None = None
    operating_income_ttm: float | None = None
    currency: str | None = None


@dataclass
class EarningsRecord:
    ticker: str
    fiscal_date: date
    report_date: date | None
    eps_actual: float | None = None
    eps_estimated: float | None = None
    revenue_actual: float | None = None
    revenue_estimated: float | None = None
