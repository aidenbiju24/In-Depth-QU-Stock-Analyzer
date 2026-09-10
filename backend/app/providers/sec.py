"""SEC EDGAR provider (Tier 1 source for company-reported data).

SEC public endpoints require NO API key — only an identifying User-Agent
header ("Company Name AdminContact@example.com"). Requests are throttled to a
conservative 8 req/min (SEC asks <= 10 req/s; we stay well under).

Endpoints:
- https://www.sec.gov/files/company_tickers.json  -> CIK lookup
- https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json  -> XBRL facts
- https://data.sec.gov/api/xbrl/companyconcept/...               -> single concepts

Filing-date discipline (METHODOLOGY.md §3): every fact carries the SEC "end"
(fiscal period end) plus "filed" (publication date) so historical analysis can
enforce point-in-time availability.
"""
from __future__ import annotations

import time
from datetime import date

from .. import schemas as S
from ..config import config
from ..errors import MissingDataError, ProviderError
from .base import DataProvider

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_COMPANYFACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:0>10}.json"

# Minimal XBRL concept -> normalized item map (USD units only).
_CONCEPTS = {
    "Revenues": "revenue", "RevenueFromContractWithCustomerExcludingAssessedTax": "revenue",
    "NetIncomeLoss": "net_income", "GrossProfit": "gross_profit",
    "OperatingIncomeLoss": "operating_income", "CostOfRevenue": "cost_of_revenue",
    "ResearchAndDevelopmentExpense": "research_development",
    "Assets": "total_assets", "Liabilities": "total_liabilities",
    "StockholdersEquity": "total_equity", "AssetsCurrent": "total_current_assets",
    "LiabilitiesCurrent": "total_current_liabilities",
    "CashAndCashEquivalentsAtCarryingValue": "cash",
    "LongTermDebtNoncurrent": "long_term_debt", "LongTermDebt": "long_term_debt",
    "ShortTermBorrowings": "short_term_debt", "DebtCurrent": "short_term_debt",
    "DepreciationDepletionAndAmortization": "depreciation_amortization",
    "NetCashProvidedByUsedInOperatingActivities": "operating_cash_flow",
    "PaymentsToAcquirePropertyPlantAndEquipment": "capex",
    "EarningsPerShareDiluted": "eps_diluted",
    "WeightedAverageNumberOfDilutedSharesOutstanding": "shares_diluted",
    "InterestExpense": "interest_expense",
    "IncomeTaxExpenseBenefit": "tax_expense",
    "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest": "pretax_income",
}


def _f(x) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _d(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except (TypeError, ValueError):
        return None


class SECProvider(DataProvider):
    name = "sec"

    def __init__(self):
        self._cik_cache: dict[str, int] = {}
        self._last_request_ts: float = 0.0

    def available(self) -> bool:
        # SEC needs no key; a descriptive User-Agent is required and defaulted.
        return bool(config.SEC_USER_AGENT)

    # ------------------------------------------------------------- plumbing
    def _sec_get(self, url: str) -> dict:
        # Throttle to <= 8 requests/minute against SEC infrastructure.
        elapsed = time.monotonic() - self._last_request_ts
        wait = max(0.0, 7.5 - elapsed)
        if wait > 0:
            time.sleep(wait)
        payload = self._http_get(url, headers={"User-Agent": config.SEC_USER_AGENT,
                                               "Accept-Encoding": "gzip, deflate"})
        self._last_request_ts = time.monotonic()
        self._record_usage()
        return payload

    def _cik_for(self, ticker: str) -> int:
        t = ticker.upper().strip()
        if t in self._cik_cache:
            return self._cik_cache[t]
        mapping = self._sec_get(_TICKERS_URL)
        for row in mapping.values():
            if str(row.get("ticker", "")).upper() == t:
                cik = int(row["cik_str"])
                self._cik_cache[t] = cik
                return cik
        raise MissingDataError(f"SEC CIK for ticker {ticker}", "not in SEC ticker map")

    # ------------------------------------------------------------- company
    def get_company(self, ticker: str) -> S.Company | None:
        cik = self._cik_for(ticker)
        payload = self._sec_get(_COMPANYFACTS.format(cik=cik))
        return S.Company(
            ticker=ticker,
            name=payload.get("entityName"),
            exchange=None,
            sector=None,
            industry=None,
            currency="USD",
            description=None,
        )

    # ------------------------------------------------------------- prices
    def get_daily_prices(self, ticker: str, outputsize: str = "full") -> list:
        raise ProviderError(self.name, "SEC does not provide market prices")

    def get_benchmark_prices(self, ticker: str, outputsize: str = "full") -> list:
        raise ProviderError(self.name, "SEC does not provide market prices")

    # ------------------------------------------------------------- facts
    def get_annual_facts(self, ticker: str) -> list[S.Statement]:
        """All mapped annual XBRL facts as pseudo-statements (one per fiscal
        year), each carrying its filing date for point-in-time use."""
        cik = self._cik_for(ticker)
        payload = self._sec_get(_COMPANYFACTS.format(cik=cik))
        gaap = payload.get("facts", {}).get("us-gaap", {})
        # Collect (fiscal_date, item, value, filed) tuples per concept.
        per_year: dict[date, dict[str, float]] = {}
        filed_map: dict[date, str] = {}
        for concept, item in _CONCEPTS.items():
            node = gaap.get(concept)
            if not node:
                continue
            for unit_key, entries in node.get("units", {}).items():
                if not unit_key.upper().startswith("USD"):
                    continue
                for e in entries:
                    if e.get("fp") != "FY" or e.get("form") not in ("10-K", "10-K/A"):
                        continue
                    end = _d(e.get("end"))
                    filed = _d(e.get("filed"))
                    val = _f(e.get("val"))
                    if end is None or filed is None or val is None:
                        continue
                    # Keep the most recently filed value per (year, item).
                    if filed_map.get(end) is None or str(filed) >= filed_map[end]:
                        per_year.setdefault(end, {})[item] = val
                        filed_map[end] = str(filed)
        out: list[S.Statement] = []
        for fy, items in sorted(per_year.items()):
            out.append(S.Statement(
                ticker=ticker, statement="sec_facts", period="annual",
                fiscal_date=fy, filing_date=_d(filed_map[fy]), currency="USD",
                items=items,
            ))
        return out

    def get_income_statement(self, ticker: str, period: str = "annual") -> list[S.Statement]:
        facts = self.get_annual_facts(ticker)
        income_items = {
            "revenue", "net_income", "gross_profit", "operating_income",
            "cost_of_revenue", "research_development", "eps_diluted",
            "shares_diluted", "interest_expense", "tax_expense", "pretax_income",
        }
        return [S.Statement(
            ticker=f.ticker, statement="income", period="annual",
            fiscal_date=f.fiscal_date, filing_date=f.filing_date,
            currency=f.currency,
            items={k: v for k, v in f.items.items() if k in income_items},
        ) for f in facts]

    def get_balance_sheet(self, ticker: str, period: str = "annual") -> list[S.Statement]:
        facts = self.get_annual_facts(ticker)
        bs_items = {
            "total_assets", "total_liabilities", "total_equity",
            "total_current_assets", "total_current_liabilities", "cash",
            "long_term_debt", "short_term_debt",
        }
        return [S.Statement(
            ticker=f.ticker, statement="balance", period="annual",
            fiscal_date=f.fiscal_date, filing_date=f.filing_date,
            currency=f.currency,
            items={k: v for k, v in f.items.items() if k in bs_items},
        ) for f in facts]

    def get_cash_flow(self, ticker: str, period: str = "annual") -> list[S.Statement]:
        facts = self.get_annual_facts(ticker)
        cf_items = {
            "operating_cash_flow", "capex", "depreciation_amortization",
        }
        return [S.Statement(
            ticker=f.ticker, statement="cashflow", period="annual",
            fiscal_date=f.fiscal_date, filing_date=f.filing_date,
            currency=f.currency,
            items={k: v for k, v in f.items.items() if k in cf_items},
        ) for f in facts]

    # ------------------------------------------------------------- stubs
    def get_fundamentals(self, ticker: str) -> S.Fundamentals | None:
        return None  # SEC has no point-in-time price/multiple data

    def get_earnings(self, ticker: str) -> list[S.EarningsRecord]:
        # EPS diluted per fiscal year from XBRL (estimates not available).
        facts = self.get_annual_facts(ticker)
        return [
            S.EarningsRecord(
                ticker=ticker, fiscal_date=f.fiscal_date,
                report_date=f.filing_date,
                eps_actual=f.items.get("eps_diluted"),
            )
            for f in facts
            if "eps_diluted" in f.items
        ]
