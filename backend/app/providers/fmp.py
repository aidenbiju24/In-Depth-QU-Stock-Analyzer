"""Financial Modeling Prep provider (supplementary source).

FMP retired every /api/v3/ "legacy" endpoint for keys created after
2025-08-31 (HTTP 403 "Legacy Endpoint" errors). This provider therefore
speaks the current /stable/ API exclusively:

- /profile?symbol=                          -> company profile
- /historical-price-eod/full                -> daily OHLCV (flat array)
- /historical-price-eod/dividend-adjusted   -> split/dividend-adjusted closes
- /key-metrics-ttm, /ratios-ttm             -> TTM multiples + profitability
- /income-statement, /balance-sheet-statement, /cash-flow-statement (annual)
- /earnings                                 -> EPS/revenue actual vs estimate

Stable API specifics honored here:
- Symbol is a QUERY PARAM (?symbol=...), not a path segment.
- Responses are flat JSON arrays (not {"historical": [...]} wrappers).
- Free tier caps statement lookback at 5 years and rejects limit > 5, so no
  limit parameter is sent (default depth is used).
- The free tier has no request budget to waste: every call goes through the
  shared raw_cache (_fetch), so repeated ingests never re-hit FMP.

Error semantics: HTTP >= 400 raises ProviderError in the base class; some
plans additionally return HTTP 200 with an error body, which we inspect.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .. import schemas as S
from ..config import config
from ..errors import ProviderError
from .base import DataProvider

_BASE = "https://financialmodelingprep.com/stable"

# "full" history depth on the stable free tier (measured 2026-09: a 6-year
# window returns ~1,500 daily bars). Anything beyond this is premium.
_FULL_HISTORY_DAYS = 365 * 6
# Compact window when the caller only needs a recent slice.
_COMPACT_DAYS = 400


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


def _unwrap(payload: Any) -> list[dict]:
    """Stable API responses are flat arrays; be tolerant of legacy wrappers
    and of HTTP-200 error bodies ({\"Error Message\": ...})."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        if "Error Message" in payload:
            # Redact the key in case FMP ever echoes it back (PROJECT_SPEC §7).
            msg = str(payload["Error Message"]).replace(
                config.FMP_API_KEY or "\x00", "[redacted]")[:200]
            raise ProviderError("fmp", msg)
        for key in ("historical", "data"):
            inner = payload.get(key)
            if isinstance(inner, list):
                return [r for r in inner if isinstance(r, dict)]
    return []


class FMPProvider(DataProvider):
    name = "fmp"

    def available(self) -> bool:
        return bool(config.FMP_API_KEY)

    # ------------------------------------------------------------- plumbing
    def _query(self, path: str, params: dict | None = None,
               kind: str = "default") -> list[dict]:
        """Cached GET against the stable API. Raw payloads live in raw_cache
        with a per-kind TTL, so re-ingesting never re-bills the free tier."""
        if not self.available():
            raise ProviderError(self.name, "FMP_API_KEY is not configured")
        p = dict(params or {})
        p["apikey"] = config.FMP_API_KEY
        payload = self._fetch(f"fmp:{path}", p, kind, url=f"{_BASE}{path}")
        return _unwrap(payload)

    # ------------------------------------------------------------- prices
    def get_daily_prices(self, ticker: str, outputsize: str = "full") -> list[S.PriceBar]:
        window = _FULL_HISTORY_DAYS if outputsize == "full" else _COMPACT_DAYS
        to = date.today()
        frm = to - timedelta(days=window)
        rng = {"symbol": ticker, "from": frm.isoformat(), "to": to.isoformat()}

        # Two cached series: unadjusted OHLCV + dividend/split-adjusted closes
        # (merged so backtests and momentum use adjusted prices per spec).
        raw_rows = self._query("/historical-price-eod/full", rng, "prices")
        try:
            adj_rows = self._query(
                "/historical-price-eod/dividend-adjusted", rng, "prices")
        except ProviderError:
            adj_rows = []  # adjusted series is optional; closes still work

        adj_by_date = {
            r["date"]: _f(r.get("adjClose"))
            for r in adj_rows if r.get("date")
        }
        bars: list[S.PriceBar] = []
        for row in raw_rows:
            d = _d(row.get("date"))
            if d is None:
                continue
            close = _f(row.get("close"))
            if close is None:
                continue
            bars.append(S.PriceBar(
                date=d,
                open=_f(row.get("open")), high=_f(row.get("high")),
                low=_f(row.get("low")), close=close,
                adj_close=adj_by_date.get(row["date"]) or close,
                volume=_f(row.get("volume")),
            ))
        bars.sort(key=lambda b: b.date)
        return bars

    def get_benchmark_prices(self, ticker: str, outputsize: str = "full") -> list[S.PriceBar]:
        return self.get_daily_prices(ticker, outputsize)

    # ------------------------------------------------------------- company
    def get_company(self, ticker: str) -> S.Company | None:
        rows = self._query("/profile", {"symbol": ticker}, "profile")
        if not rows:
            return None
        r = rows[0]
        return S.Company(
            ticker=ticker,
            name=r.get("companyName"), exchange=r.get("exchange"),
            sector=r.get("sector"), industry=r.get("industry"),
            currency=r.get("currency"), description=r.get("description"),
        )

    # --------------------------------------------------------- fundamentals
    def get_fundamentals(self, ticker: str) -> S.Fundamentals | None:
        prof = self._query("/profile", {"symbol": ticker}, "profile")
        km = self._query("/key-metrics-ttm", {"symbol": ticker}, "fundamentals")
        ra = self._query("/ratios-ttm", {"symbol": ticker}, "fundamentals")
        if not prof and not km and not ra:
            return None
        p0 = prof[0] if prof else {}
        km0 = km[0] if km else {}
        ra0 = ra[0] if ra else {}
        return S.Fundamentals(
            ticker=ticker,
            as_of=date.today(),
            market_cap=_f(p0.get("marketCap")) or _f(km0.get("marketCap")),
            pe=_f(ra0.get("priceToEarningsRatioTTM")) or _f(km0.get("peRatioTTM")),
            pb=_f(ra0.get("priceToBookRatioTTM")) or _f(km0.get("pbRatioTTM")),
            ps=_f(ra0.get("priceToSalesRatioTTM")) or _f(km0.get("psRatioTTM")),
            ev_ebitda=_f(km0.get("evToEBITDATTM")),
            dividend_yield=_f(ra0.get("dividendYieldTTM")),
            beta_5y=_f(p0.get("beta")),
            # FMP TTM endpoints expose ratios, not absolute dollar amounts;
            # absolute TTM totals come from stored statements (SEC Tier 1).
            revenue_ttm=None,
            net_income_ttm=None,
            ebitda_ttm=None,
            free_cash_flow_ttm=None,
            operating_cash_flow_ttm=None,
            total_debt=_f(km0.get("totalDebtTTM")),
            currency=p0.get("currency") or "USD",
        )

    # ----------------------------------------------------------- statements
    # Annual statements, newest first. No limit param: the free tier rejects
    # limit > 5 and the default already returns the full 5-year history.
    def get_income_statement(self, ticker: str, period: str = "annual") -> list[S.Statement]:
        rows = self._query("/income-statement", {"symbol": ticker}, "statements")
        out = []
        for r in rows:
            fd = _d(r.get("date"))
            if fd is None:
                continue
            out.append(S.Statement(
                ticker=ticker, statement="income", period="annual",
                fiscal_date=fd, filing_date=_d(r.get("filingDate")),
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
        rows = self._query("/balance-sheet-statement", {"symbol": ticker}, "statements")
        out = []
        for r in rows:
            fd = _d(r.get("date"))
            if fd is None:
                continue
            out.append(S.Statement(
                ticker=ticker, statement="balance", period="annual",
                fiscal_date=fd, filing_date=_d(r.get("filingDate")),
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
        rows = self._query("/cash-flow-statement", {"symbol": ticker}, "statements")
        out = []
        for r in rows:
            fd = _d(r.get("date"))
            if fd is None:
                continue
            out.append(S.Statement(
                ticker=ticker, statement="cashflow", period="annual",
                fiscal_date=fd, filing_date=_d(r.get("filingDate")),
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
        rows = self._query("/earnings", {"symbol": ticker}, "earnings")
        out = []
        today = date.today()
        for r in rows:
            fd = _d(r.get("date"))
            if fd is None or fd > today:
                continue  # skip not-yet-reported quarters (estimate only)
            eps_actual = _f(r.get("epsActual"))
            eps_est = _f(r.get("epsEstimated"))
            if eps_actual is None and eps_est is None:
                continue
            out.append(S.EarningsRecord(
                ticker=ticker,
                fiscal_date=fd,
                report_date=fd,
                eps_actual=eps_actual,
                eps_estimated=eps_est,
                revenue_actual=_f(r.get("revenueActual")),
                revenue_estimated=_f(r.get("revenueEstimated")),
            ))
        out.sort(key=lambda e: e.fiscal_date)
        return out
