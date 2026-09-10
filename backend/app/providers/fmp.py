"""Financial Modeling Prep provider (supplementary source).

Free-tier endpoints used (apikey query param):
- /profile/{symbol}           -> company profile
- /historical-price-full/{symbol}?serietype=line or full OHLCV (adjclose included)
- /key-metrics-ttm/{symbol}   -> TTM multiples (P/E, P/B, P/S, EV/EBITDA, FCF yield...)
- /ratios-ttm/{symbol}        -> TTM profitability ratios (ROE, margins, ROIC...)
- /income-statement, /balance-sheet-statement, /cash-flow-statement
- /earning surprises + analyst estimates -> EPS/revenue actual vs estimate
"""
from __future__ import annotations

from datetime import date
from typing import Any

from .. import schemas as S
from ..config import config
from ..errors import ProviderError
from .base import DataProvider

_BASE = "https://financialmodelingprep.com/api/v3"


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


class FMPProvider(DataProvider):
    name = "fmp"

    def available(self) -> bool:
        return bool(config.FMP_API_KEY)

    def _query(self, path: str, params: dict | None = None, version: str = "v3") -> Any:
        if not self.available():
            raise ProviderError(self.name, "FMP_API_KEY is not configured")
        p = {"apikey": config.FMP_API_KEY}
        p.update(params or {})
        url = f"https://financialmodelingprep.com/api/{version}/{path}"
        payload = self._http_get(url, params=p)
        # FMP signals errors with {"Error Message": "..."}.
        if isinstance(payload, dict) and "Error Message" in payload:
            raise ProviderError(self.name, str(payload["Error Message"])[:200])
        return payload

    # ------------------------------------------------------------- prices
    def get_daily_prices(self, ticker: str, outputsize: str = "full") -> list[S.PriceBar]:
        params = {"serietype": "line"} if outputsize != "full" else None
        payload = self._query(
            f"historical-price-full/{ticker}",
            params if params else {},
        )
        hist = (payload or {}).get("historical") or []
        bars: list[S.PriceBar] = []
        for row in hist:
            d = _d(row.get("date"))
            if d is None:
                continue
            bars.append(S.PriceBar(
                date=d,
                open=_f(row.get("open")), high=_f(row.get("high")),
                low=_f(row.get("low")), close=_f(row.get("close")),
                adj_close=_f(row.get("adjClose")) or _f(row.get("close")),
                volume=_f(row.get("volume")),
            ))
        bars.sort(key=lambda b: b.date)
        return bars

    def get_benchmark_prices(self, ticker: str, outputsize: str = "full") -> list[S.PriceBar]:
        return self.get_daily_prices(ticker, outputsize)

    # ------------------------------------------------------------- company
    def get_company(self, ticker: str) -> S.Company | None:
        rows = self._query(f"profile/{ticker}") or []
        if not rows:
            return None
        r = rows[0]
        return S.Company(
            ticker=ticker,
            name=r.get("companyName"), exchange=r.get("exchangeShortName"),
            sector=r.get("sector"), industry=r.get("industry"),
            currency=r.get("currency"), description=r.get("description"),
        )

    # --------------------------------------------------------- fundamentals
    def get_fundamentals(self, ticker: str) -> S.Fundamentals | None:
        km = self._query(f"key-metrics-ttm/{ticker}") or []
        ra = self._query(f"ratios-ttm/{ticker}") or []
        prof = self._query(f"profile/{ticker}") or []
        if not km and not ra:
            return None
        km0 = km[0] if km else {}
        ra0 = ra[0] if ra else {}
        p0 = prof[0] if prof else {}
        return S.Fundamentals(
            ticker=ticker,
            as_of=date.today(),
            market_cap=_f(p0.get("mktCap")) or _f(km0.get("marketCap")),
            pe=_f(ra0.get("peRatioTTM")) or _f(km0.get("peRatioTTM")),
            forward_pe=_f(ra0.get("forwardPeRatioTTM")),
            pb=_f(ra0.get("priceToBookRatioTTM")) or _f(km0.get("pbRatioTTM")),
            ps=_f(ra0.get("priceToSalesRatioTTM")) or _f(km0.get("psRatioTTM")),
            ev_ebitda=_f(km0.get("enterpriseValueOverEBITDATTM")),
            dividend_yield=_f(ra0.get("dividendYieldTTM")),
            beta_5y=_f(p0.get("beta")),
            eps=_f(ra0.get("epsTTM")),
            eps_diluted=_f(ra0.get("epsTTM")),
            # FMP TTM key-metrics expose per-share values; keep them out of the
            # absolute-value fields rather than fabricating totals.
            revenue_ttm=None,
            net_income_ttm=None,
            ebitda_ttm=None,
            free_cash_flow_ttm=None,
            operating_cash_flow_ttm=None,
            total_debt=_f(km0.get("totalDebtTTM")),
            total_cash=None,
            total_equity=None,
            currency=p0.get("currency") or "USD",
        )

    # ----------------------------------------------------------- statements
    def get_income_statement(self, ticker: str, period: str = "annual") -> list[S.Statement]:
        rows = self._query(f"income-statement/{ticker}", {"limit": 10}) or []
        out = []
        for r in rows:
            fd = _d(r.get("date"))
            if fd is None:
                continue
            out.append(S.Statement(
                ticker=ticker, statement="income", period="annual",
                fiscal_date=fd, filing_date=_d(r.get("fillingDate")),
                currency=r.get("reportedCurrency"),
                items={
                    "revenue": _f(r.get("revenue")),
                    "cost_of_revenue": _f(r.get("costOfRevenue")),
                    "gross_profit": _f(r.get("grossProfit")),
                    "research_development": _f(r.get("researchAndDevelopmentExpenses")),
                    "operating_income": _f(r.get("operatingIncome")),
                    "ebitda": _f(r.get("ebitda")),
                    "pretax_income": _f(r.get("incomeBeforeTax")),
                    "tax_expense": _f(r.get("incomeTaxExpense")),
                    "net_income": _f(r.get("netIncome")),
                    "eps_diluted": _f(r.get("epsdiluted")) or _f(r.get("eps")),
                    "interest_expense": _f(r.get("interestExpense")),
                },
            ))
        return out

    def get_balance_sheet(self, ticker: str, period: str = "annual") -> list[S.Statement]:
        rows = self._query(f"balance-sheet-statement/{ticker}", {"limit": 10}) or []
        out = []
        for r in rows:
            fd = _d(r.get("date"))
            if fd is None:
                continue
            out.append(S.Statement(
                ticker=ticker, statement="balance", period="annual",
                fiscal_date=fd, filing_date=_d(r.get("fillingDate")),
                currency=r.get("reportedCurrency"),
                items={
                    "total_assets": _f(r.get("totalAssets")),
                    "total_liabilities": _f(r.get("totalLiabilities")),
                    "total_equity": _f(r.get("totalStockholdersEquity")),
                    "cash": _f(r.get("cashAndCashEquivalents")),
                    "short_term_investments": _f(r.get("shortTermInvestments")),
                    "short_term_debt": _f(r.get("shortTermDebt")),
                    "long_term_debt": _f(r.get("longTermDebt")),
                    "retained_earnings": _f(r.get("retainedEarnings")),
                },
            ))
        return out

    def get_cash_flow(self, ticker: str, period: str = "annual") -> list[S.Statement]:
        rows = self._query(f"cash-flow-statement/{ticker}", {"limit": 10}) or []
        out = []
        for r in rows:
            fd = _d(r.get("date"))
            if fd is None:
                continue
            out.append(S.Statement(
                ticker=ticker, statement="cashflow", period="annual",
                fiscal_date=fd, filing_date=_d(r.get("fillingDate")),
                currency=r.get("reportedCurrency"),
                items={
                    "operating_cash_flow": _f(r.get("operatingCashFlow")),
                    "capex": _f(r.get("capitalExpenditure")),
                    "depreciation_amortization": _f(r.get("depreciationAndAmortization")),
                    "dividends_paid": _f(r.get("dividendsPaid")),
                    "share_issuance": _f(r.get("commonStockIssuance")),
                    "share_repurchase": _f(r.get("commonStockRepurchase")),
                },
            ))
        return out

    # ------------------------------------------------------------- earnings
    def get_earnings(self, ticker: str) -> list[S.EarningsRecord]:
        rows = self._query(f"earnings-surprises/{ticker}") or []
        out = []
        for r in rows:
            fd = _d(r.get("date"))
            if fd is None:
                continue
            out.append(S.EarningsRecord(
                ticker=ticker,
                fiscal_date=fd,
                report_date=fd,
                eps_actual=_f(r.get("actualEarningResult")),
                eps_estimated=_f(r.get("estimatedEarning")),
            ))
        return out
