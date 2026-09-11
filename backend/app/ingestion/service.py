"""Ingestion service: providers -> normalize -> validate -> SQLite.

Implements the source hierarchy (METHODOLOGY.md §2):
  Tier 1 SEC (authoritative statements/facts)
  Tier 2 Alpha Vantage (prices, overview, earnings)
  Tier 3 FMP (supplementary: prices, statements, earnings surprises)

Every step degrades gracefully: if one provider fails, we keep what succeeded
and report which sources are missing. No fabricated data.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..db import connect
from ..errors import ProviderError
from ..providers.alpha_vantage import AlphaVantageProvider
from ..providers.base import DataProvider
from ..providers.fmp import FMPProvider
from ..providers.sec import SECProvider
from . import repository as repo
from .validator import check_price_series, check_statement, validate_ticker


@dataclass
class IngestReport:
    ticker: str
    companies: list[str] = field(default_factory=list)
    prices: dict[str, int] = field(default_factory=dict)
    statements: dict[str, int] = field(default_factory=dict)
    fundamentals: list[str] = field(default_factory=list)
    earnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    validation: list[str] = field(default_factory=list)

    def ok(self) -> bool:
        return bool(self.prices or self.statements)


class IngestionService:
    """Fetch + store data for tickers using all configured providers."""

    # Price sources in preference order. Note (2026-09): Alpha Vantage's free
    # tier now caps TIME_SERIES_DAILY at ~100 bars (outputsize=compact; the
    # adjusted and full-history series moved to premium), while FMP's /stable/
    # API returns ~6 years of dividend-adjusted bars — deep enough for the
    # 12-1 momentum metrics in METHODOLOGY.md §11. FMP therefore leads for
    # PRICES when configured. Statements remain SEC-first (Tier 1); this
    # reordering is a deliberate response to the free-tier change, not a
    # methodology edit.
    PRICE_ORDER = ("fmp", "alpha_vantage")
    # ~6 trading months: floor for meaningful 3M/6M momentum and consistency.
    MIN_PRICE_BARS = 120

    def __init__(self, providers: list[DataProvider] | None = None):
        if providers is None:
            providers = [SECProvider(), AlphaVantageProvider(), FMPProvider()]
        self.providers = providers
        self._by_name = {p.name: p for p in providers}

    # ------------------------------------------------------------ prices
    def _pick_price_bars(self, ticker: str, report: IngestReport,
                         benchmark: bool = False):
        """Choose the deepest usable price series across price providers.

        A series shorter than MIN_PRICE_BARS is held only as a fallback (the
        longest short series wins, with a validation note) so a degraded
        history is still honest about being degraded.
        """
        getter_name = "get_benchmark_prices" if benchmark else "get_daily_prices"
        # PRICE_ORDER leads; any other configured providers (custom or test
        # mocks) keep their chance, in injection order.
        ordered = [self._by_name[n] for n in self.PRICE_ORDER
                   if n in self._by_name]
        ordered += [p for p in self.providers
                    if p.name not in self.PRICE_ORDER and p not in ordered]
        fallback = None  # (prov_name, bars, reason)
        for prov in ordered:
            try:
                bars = getattr(prov, getter_name)(ticker)
            except ProviderError as exc:
                report.errors.append(str(exc))
                continue
            if not bars:
                continue
            if len(bars) < self.MIN_PRICE_BARS:
                if fallback is None or len(bars) > len(fallback[1]):
                    fallback = (prov.name, bars,
                                f"only {len(bars)} bars (< {self.MIN_PRICE_BARS})")
                continue
            vr = check_price_series(bars)
            if not vr.ok:
                report.validation.append(f"{prov.name}: {vr.summary()}")
                continue
            return prov.name, bars
        if fallback is not None:
            name, bars, reason = fallback
            report.validation.append(
                f"{name}: using short price series ({reason})")
            return name, bars
        return None

    # ----------------------------------------------------------------- api
    def ingest_ticker(self, ticker: str, with_prices: bool = True,
                      with_statements: bool = True) -> IngestReport:
        ticker = validate_ticker(ticker)
        report = IngestReport(ticker=ticker)
        with connect() as conn:
            currency: str | None = None

            # -- Company profile: first provider that succeeds wins; SEC data
            #    is authoritative for the name (Tier 1).
            for prov in self.providers:
                try:
                    company = prov.get_company(ticker)
                except ProviderError as exc:
                    report.errors.append(str(exc))
                    continue
                if company:
                    company.source = prov.name
                    repo.upsert_company(conn, company)
                    report.companies.append(prov.name)
                    currency = company.currency
                    break

            # -- Prices: deepest usable series wins (FMP stable leads while
            #    AV free tier caps at ~100 bars; see PRICE_ORDER note).
            if with_prices:
                picked = self._pick_price_bars(ticker, report)
                if picked is not None:
                    prov_name, bars = picked
                    n = repo.upsert_prices(conn, ticker, bars, prov_name)
                    report.prices[prov_name] = n

            # -- Statements: SEC first (Tier 1), then FMP; keep BOTH sources
            #    in the DB (never overwrite one with the other silently).
            if with_statements:
                for prov in self.providers:
                    for kind, getter in (
                        ("income", prov.get_income_statement),
                        ("balance", prov.get_balance_sheet),
                        ("cashflow", prov.get_cash_flow),
                    ):
                        try:
                            statements = getter(ticker)
                        except ProviderError as exc:
                            report.errors.append(str(exc))
                            continue
                        kept = 0
                        for st in statements:
                            vr = check_statement(st, currency)
                            if not vr.ok:
                                report.validation.append(
                                    f"{prov.name} {kind} {st.fiscal_date}: {vr.summary()}")
                            repo.upsert_statement(conn, st, prov.name)
                            kept += 1
                        if kept:
                            report.statements[f"{kind}:{prov.name}"] = kept

            # -- Fundamentals snapshot: FMP/AV provide multiples; store under
            #    their own source key.
            for prov in self.providers:
                try:
                    fund = prov.get_fundamentals(ticker)
                except ProviderError as exc:
                    report.errors.append(str(exc))
                    continue
                if fund:
                    repo.upsert_fundamentals(conn, fund, prov.name)
                    report.fundamentals.append(prov.name)

            # -- Earnings: collect from every provider that has them.
            for prov in self.providers:
                try:
                    records = prov.get_earnings(ticker)
                except ProviderError as exc:
                    report.errors.append(str(exc))
                    continue
                if records:
                    repo.upsert_earnings(conn, records, prov.name)
                    report.earnings.append(prov.name)

        return report

    def ingest_benchmark(self, ticker: str) -> int:
        """Fetch benchmark price history only (e.g. SPY)."""
        ticker = validate_ticker(ticker)
        report = IngestReport(ticker=ticker)
        picked = self._pick_price_bars(ticker, report, benchmark=True)
        if picked is None:
            return 0
        prov_name, bars = picked
        with connect() as conn:
            return repo.upsert_prices(conn, ticker, bars, prov_name)
