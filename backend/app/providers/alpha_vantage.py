"""Alpha Vantage provider.

Endpoints used (all free tier, apikey query param):
- TIME_SERIES_DAILY_ADJUSTED  -> daily OHLCV + adjusted close + split/dividend factors
- GLOBAL_QUOTE                -> latest quote
- OVERVIEW                    -> company profile + TTM fundamental snapshot
- INCOME_STATEMENT / BALANCE_SHEET / CASH_FLOW -> annual + quarterly statements
- EARNINGS                    -> EPS actual vs estimate history

Error semantics: AV returns HTTP 200 with a JSON body for errors, so we inspect
payload keys ("Error Message", "Note", "Information") rather than status alone.
"""
from __future__ import annotations

from datetime import date
from typing import ClassVar

from .. import schemas as S
from ..config import config
from ..errors import ProviderError, RateLimitError
from .base import DataProvider

_BASE = "https://www.alphavantage.co/query"


def _f(x) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v


def _d(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


class AlphaVantageProvider(DataProvider):
    name = "alpha_vantage"

    def available(self) -> bool:
        return bool(config.ALPHA_VANTAGE_API_KEY)

    # ------------------------------------------------------------- helpers
    def _query(self, function: str, params: dict | None = None) -> dict:
        if not self.available():
            raise ProviderError(self.name, "ALPHA_VANTAGE_API_KEY is not configured")
        if self.calls_today() >= config.AV_DAILY_BUDGET:
            raise RateLimitError(self.name, "local daily budget exhausted")
        p = {"function": function, "apikey": config.ALPHA_VANTAGE_API_KEY,
             "datatype": "json"}
        p.update(params or {})
        payload = self._http_get(_BASE, params=p)
        if isinstance(payload, dict):
            for key in ("Error Message", "Note", "Information"):
                if key in payload:
                    raise ProviderError(self.name, f"{key}: {payload[key][:200]}")
        return payload

    # ------------------------------------------------------------- prices
    def get_daily_prices(self, ticker: str, outputsize: str = "full") -> list[S.PriceBar]:
        payload = self._query("TIME_SERIES_DAILY_ADJUSTED",
                              {"symbol": ticker, "outputsize": outputsize})
        series = payload.get("Time Series (Daily)") or {}
        bars: list[S.PriceBar] = []
        for ds, row in series.items():
            d = _d(ds)
            if d is None:
                continue
            bars.append(S.PriceBar(
                date=d,
                open=_f(row.get("1. open")),
                high=_f(row.get("2. high")),
                low=_f(row.get("3. low")),
                close=_f(row.get("4. close")),
                adj_close=_f(row.get("5. adjusted close")),
                volume=_f(row.get("6. volume")),
            ))
        bars.sort(key=lambda b: b.date)
        return bars

    def get_benchmark_prices(self, ticker: str, outputsize: str = "full") -> list[S.PriceBar]:
        return self.get_daily_prices(ticker, outputsize)

    # ------------------------------------------------------------- company
    def get_company(self, ticker: str) -> S.Company | None:
        payload = self._query("OVERVIEW", {"symbol": ticker})
        if not payload or payload.get("Symbol") is None:
            return None
        return S.Company(
            ticker=ticker,
            name=payload.get("Name") or None,
            exchange=payload.get("Exchange") or None,
            sector=payload.get("Sector") or None,
            industry=payload.get("Industry") or None,
            currency=payload.get("FinancialCurrency") or "USD",
            description=payload.get("Description") or None,
        )

    # --------------------------------------------------------- fundamentals
    def get_fundamentals(self, ticker: str) -> S.Fundamentals | None:
        payload = self._query("OVERVIEW", {"symbol": ticker})
        if not payload or payload.get("Symbol") is None:
            return None
        return S.Fundamentals(
            ticker=ticker,
            as_of=date.today(),
            market_cap=_f(payload.get("MarketCapitalization")),
            pe=_f(payload.get("PERatio")),
            forward_pe=_f(payload.get("ForwardPE")),
            pb=_f(payload.get("PriceToBookRatio")),
            ps=_f(payload.get("PriceToSalesRatioTTM")),
            ev_ebitda=_f(payload.get("EVToEBITDA")),
            dividend_yield=_f(payload.get("DividendYield")),
            beta_5y=_f(payload.get("Beta")),
            eps=_f(payload.get("EPS")),
            eps_diluted=_f(payload.get("EPS")),
            revenue_ttm=_f(payload.get("RevenueTTM")),
            gross_profit_ttm=_f(payload.get("GrossProfitTTM")),
            operating_income_ttm=_f(payload.get("OperatingIncomeTTM")),
            ebitda_ttm=_f(payload.get("EBITDA")),
        )

    # ----------------------------------------------------------- statements
    def get_income_statement(self, ticker: str, period: str = "annual") -> list[S.Statement]:
        payload = self._query("INCOME_STATEMENT", {"symbol": ticker})
        return self._normalize_reports(ticker, "income", payload, period)

    def get_balance_sheet(self, ticker: str, period: str = "annual") -> list[S.Statement]:
        payload = self._query("BALANCE_SHEET", {"symbol": ticker})
        return self._normalize_reports(ticker, "balance", payload, period)

    def get_cash_flow(self, ticker: str, period: str = "annual") -> list[S.Statement]:
        payload = self._query("CASH_FLOW", {"symbol": ticker})
        return self._normalize_reports(ticker, "cashflow", payload, period)

    _INCOME_MAP: ClassVar[dict[str, str]] = {
        "totalRevenue": "revenue", "costOfRevenue": "cost_of_revenue",
        "grossProfit": "gross_profit", "researchAndDevement": "research_development",
        "researchAndDevelopment": "research_development",
        "operatingIncome": "operating_income", "ebit": "ebit",
        "netIncome": "net_income", "ebitda": "ebitda",
        "incomeBeforeTax": "pretax_income", "incomeTaxExpense": "tax_expense",
        "interestExpense": "interest_expense", "interestIncome": "interest_income",
    }
    _BALANCE_MAP: ClassVar[dict[str, str]] = {
        "totalAssets": "total_assets", "totalCurrentAssets": "total_current_assets",
        "cashAndCashEquivalentsAtCarryingValue": "cash",
        "shortTermInvestments": "short_term_investments",
        "totalLiabilities": "total_liabilities",
        "totalCurrentLiabilities": "total_current_liabilities",
        "currentDebt": "short_term_debt", "longTermDebt": "long_term_debt",
        "totalShareholderEquity": "total_equity",
        "retainedEarnings": "retained_earnings",
        "commonStockSharesOutstanding": "shares_outstanding",
    }
    _CASHFLOW_MAP: ClassVar[dict[str, str]] = {
        "operatingCashflow": "operating_cash_flow",
        "capitalExpenditures": "capex",
        "cashflowFromInvestment": "investing_cash_flow",
        "cashflowFromFinancing": "financing_cash_flow",
        "dividendPayout": "dividends_paid",
        "depreciationDepletionAndAmortization": "depreciation_amortization",
    }

    def _normalize_reports(self, ticker: str, statement: str, payload: dict,
                           period: str) -> list[S.Statement]:
        key = {"income": "annualReports", "balance": "annualReports",
               "cashflow": "annualReports"}[statement]
        reports = payload.get(key) or []
        out: list[S.Statement] = []
        for rep in reports:
            fd = _d(rep.get("fiscalDateEnding"))
            if fd is None:
                continue
            mapping = {"income": self._INCOME_MAP, "balance": self._BALANCE_MAP,
                       "cashflow": self._CASHFLOW_MAP}[statement]
            items = {to: _f(rep.get(frm)) for frm, to in mapping.items()}
            out.append(S.Statement(
                ticker=ticker, statement=statement, period="annual",
                fiscal_date=fd,
                filing_date=None,   # AV does not expose filing dates
                currency=rep.get("reportedCurrency"),
                items=items,
            ))
        return out

    # ------------------------------------------------------------- earnings
    def get_earnings(self, ticker: str) -> list[S.EarningsRecord]:
        payload = self._query("EARNINGS", {"symbol": ticker})
        out: list[S.EarningsRecord] = []
        for rep in payload.get("quarterlyEarnings") or []:
            fd = _d(rep.get("fiscalDateEnding"))
            if fd is None:
                continue
            out.append(S.EarningsRecord(
                ticker=ticker,
                fiscal_date=fd,
                report_date=_d(rep.get("reportedDate")),
                eps_actual=_f(rep.get("reportedEPS")),
                eps_estimated=_f(rep.get("estimate")),
                revenue_actual=None,
                revenue_estimated=None,
            ))
        return out
