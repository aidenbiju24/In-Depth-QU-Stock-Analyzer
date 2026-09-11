"""Provider unit tests: FMP stable-API normalization, Alpha Vantage free-tier
caps, and price-source selection in the ingestion service (PROJECT_SPEC §10,
METHODOLOGY §2 source hierarchy).

All providers are exercised through a stubbed _fetch — no network, no keys.
"""
from __future__ import annotations

import json
from datetime import UTC, date, timedelta

import pandas as pd
import pytest
from app.errors import ProviderError
from app.ingestion.service import IngestionService
from app.providers.alpha_vantage import AlphaVantageProvider
from app.providers.base import DataProvider
from app.providers.fmp import FMPProvider

from app import schemas as S


# --------------------------------------------------------------------------
# Stub plumbing: replay canned payloads instead of hitting the network.
# --------------------------------------------------------------------------
class StubFetch:
    """Replaces DataProvider._fetch with canned payload lookup."""

    def __init__(self, responses: dict[str, object]):
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, endpoint, params, kind, headers=None, url=None,
                 validate=None):
        self.calls.append((endpoint, dict(params)))
        payload = None
        for fragment, candidate in self.responses.items():
            if fragment in endpoint:
                payload = candidate
                break
        if payload is None:
            raise ProviderError("stub", f"no canned payload for {endpoint}")
        # Mirror base behavior: validation runs on both cached and fresh
        # payloads so provider notice bodies raise exactly as in production.
        if validate is not None:
            validate(payload)
        return payload


def _stub(provider: DataProvider, responses: dict[str, object]) -> StubFetch:
    stub = StubFetch(responses)
    provider._fetch = stub  # type: ignore[method-assign]
    return stub


def _price_rows(n: int, start: date = date(2026, 1, 1)) -> list[dict]:
    rows = []
    d = start
    px = 100.0
    for _ in range(n):
        while d.weekday() >= 5:  # skip weekends for realism
            d += timedelta(days=1)
        px *= 1.001
        rows.append({"date": d.isoformat(), "open": px, "high": px * 1.01,
                     "low": px * 0.99, "close": px, "volume": 1_000_000})
        d += timedelta(days=1)
    return rows


# --------------------------------------------------------------------------
# FMP stable API
# --------------------------------------------------------------------------
def _fmp_responses(today: date) -> dict[str, object]:
    adj = [{"date": r["date"], "adjClose": r["close"] * 0.98}
           for r in _price_rows(5)]
    return {
        "historical-price-eod/full": _price_rows(5),
        "dividend-adjusted": adj,
        "profile": [{"symbol": "TST", "companyName": "Test Co",
                     "exchange": "NASDAQ", "sector": "Technology",
                     "industry": "Software", "currency": "USD",
                     "beta": 1.2, "marketCap": 5_000_000_000}],
        "key-metrics-ttm": [{"evToEBITDATTM": 12.5, "totalDebtTTM": 1e9}],
        "ratios-ttm": [{"priceToEarningsRatioTTM": 20.0,
                        "priceToBookRatioTTM": 4.0,
                        "priceToSalesRatioTTM": 3.0,
                        "dividendYieldTTM": 0.005}],
        "income-statement": [{"date": "2025-09-27", "revenue": 416.2e9,
                              "netIncome": 112.0e9, "epsdiluted": 7.46,
                              "filingDate": "2025-10-31",
                              "reportedCurrency": "USD"}],
        "earnings": [
            {"date": (today - timedelta(days=30)).isoformat(),
             "epsActual": 1.5, "epsEstimated": 1.4,
             "revenueActual": 9e10, "revenueEstimated": 8.8e10},
            {"date": (today + timedelta(days=30)).isoformat(),
             "epsActual": None, "epsEstimated": 1.6},
        ],
    }


@pytest.fixture()
def fmp_stub(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANT_DB_PATH", str(tmp_path / "prov.db"))
    import app.config as cfg
    monkeypatch.setattr(cfg.config, "DB_PATH", str(tmp_path / "prov.db"))
    provider = FMPProvider()
    return provider, _stub(provider, _fmp_responses(date.today()))


def test_fmp_prices_use_symbol_param_and_merge_adjusted(fmp_stub):
    prov, stub = fmp_stub
    bars = prov.get_daily_prices("TST")
    assert len(bars) == 5
    dates = [b.date for b in bars]
    assert dates == sorted(dates)                       # oldest -> newest
    assert bars[-1].adj_close == pytest.approx(bars[-1].close * 0.98)
    # Stable API: symbol is a query param, not a path segment.
    eps = [p for ep, p in stub.calls if "full" in ep]
    assert eps and eps[0]["symbol"] == "TST"
    assert "from" in eps[0] and "to" in eps[0]


def test_fmp_prices_survive_missing_adjusted_series(fmp_stub):
    prov, stub = fmp_stub
    stub.responses["dividend-adjusted"] = ProviderError("fmp", "gone")
    bars = prov.get_daily_prices("TST")
    assert len(bars) == 5
    assert all(b.adj_close == pytest.approx(b.close) for b in bars)


def test_fmp_fundamentals_merge_profiles_and_metrics(fmp_stub):
    prov, _ = fmp_stub
    f = prov.get_fundamentals("TST")
    assert f is not None
    assert f.market_cap == 5_000_000_000.0              # from profile
    assert f.pe == 20.0 and f.pb == 4.0 and f.ps == 3.0  # from ratios-ttm
    assert f.ev_ebitda == 12.5                          # from key-metrics-ttm
    # Absolute TTM totals are deliberately None (ratios only — no fabrication).
    assert f.revenue_ttm is None and f.net_income_ttm is None


def test_fmp_statements_and_earnings_normalize(fmp_stub):
    prov, _ = fmp_stub
    inc = prov.get_income_statement("TST")
    assert len(inc) == 1
    assert inc[0].fiscal_date == date(2025, 9, 27)
    assert inc[0].filing_date == date(2025, 10, 31)     # point-in-time usable
    assert inc[0].items["revenue"] == pytest.approx(416.2e9)

    recs = prov.get_earnings("TST")
    assert len(recs) == 1                               # future quarter skipped
    assert recs[0].eps_actual == 1.5
    assert recs[0].revenue_actual == 9e10


def test_fmp_error_body_raises_provider_error(fmp_stub):
    prov, stub = fmp_stub
    stub.responses["profile"] = {"Error Message": "plan quota exceeded"}
    with pytest.raises(ProviderError):
        prov.get_company("TST")


# --------------------------------------------------------------------------
# Alpha Vantage free tier
# --------------------------------------------------------------------------
def _av_daily_payload() -> dict:
    series = {
        "2026-09-10": {"1. open": "10.0", "2. high": "11.0", "3. low": "9.5",
                       "4. close": "10.5", "6. volume": "123456"},
        "2026-09-09": {"1. open": "10.1", "2. high": "11.1", "3. low": "9.6",
                       "4. close": "10.4", "5. volume": "111111"},
    }
    return {"Time Series (Daily)": series}


def test_av_free_tier_uses_compact_unadjusted_series(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANT_DB_PATH", str(tmp_path / "av.db"))
    import app.config as cfg
    monkeypatch.setattr(cfg.config, "DB_PATH", str(tmp_path / "av.db"))
    prov = AlphaVantageProvider()
    stub = _stub(prov, {"TIME_SERIES_DAILY": _av_daily_payload()})

    bars = prov.get_daily_prices("TST", outputsize="full")  # request ignored
    assert len(bars) == 2
    assert bars[0].date == date(2026, 9, 9)
    assert bars[0].adj_close is None                    # honest: unadjusted
    assert bars[0].volume == 111111.0                   # 5. key handled
    # The premium variants must never be requested.
    asked = {p.get("function"): p for _, p in stub.calls}
    assert "TIME_SERIES_DAILY" in asked
    assert asked["TIME_SERIES_DAILY"]["outputsize"] == "compact"
    assert "TIME_SERIES_DAILY_ADJUSTED" not in asked


def test_av_information_notice_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANT_DB_PATH", str(tmp_path / "av.db"))
    import app.config as cfg
    monkeypatch.setattr(cfg.config, "DB_PATH", str(tmp_path / "av.db"))
    prov = AlphaVantageProvider()
    _stub(prov, {"TIME_SERIES_DAILY": {"Information": "premium endpoint notice"}})
    with pytest.raises(ProviderError):
        prov.get_daily_prices("TST")


def test_av_error_messages_redact_the_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANT_DB_PATH", str(tmp_path / "av.db"))
    import app.config as cfg
    monkeypatch.setattr(cfg.config, "DB_PATH", str(tmp_path / "av.db"))
    monkeypatch.setattr(cfg.config, "ALPHA_VANTAGE_API_KEY", "SECRETKEY123")
    prov = AlphaVantageProvider()
    notice = {"Information": "We have detected your API key as SECRETKEY123 "
                              "and our standard API rate limit is 25 requests."}
    _stub(prov, {"TIME_SERIES_DAILY": notice})
    with pytest.raises(ProviderError) as excinfo:
        prov.get_daily_prices("TST")
    assert "SECRETKEY123" not in str(excinfo.value)
    assert "[redacted]" in str(excinfo.value)


def test_fmp_error_messages_redact_the_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANT_DB_PATH", str(tmp_path / "fmp.db"))
    import app.config as cfg
    monkeypatch.setattr(cfg.config, "DB_PATH", str(tmp_path / "fmp.db"))
    monkeypatch.setattr(cfg.config, "FMP_API_KEY", "SECRETKEY456")
    prov = FMPProvider()
    _stub(prov, {"profile": {"Error Message": "bad key SECRETKEY456 for plan"}})
    with pytest.raises(ProviderError) as excinfo:
        prov.get_company("TST")
    assert "SECRETKEY456" not in str(excinfo.value)


# --------------------------------------------------------------------------
# Cache expiry refresh: re-fetching after expiry must overwrite, not crash
# --------------------------------------------------------------------------
def test_cache_refresh_after_expiry_upserts_instead_of_crashing(tmp_path, monkeypatch):
    """Regression: raw_cache.key is UNIQUE and _cache_put used a plain INSERT,
    so the first re-fetch after any cache entry expired raised
    sqlite3.IntegrityError and 500'd every provider-backed request."""
    monkeypatch.setenv("QUANT_DB_PATH", str(tmp_path / "cache.db"))
    import app.config as cfg
    monkeypatch.setattr(cfg.config, "DB_PATH", str(tmp_path / "cache.db"))

    class _PayloadFixed(DataProvider):
        def __init__(self, name: str):
            self.name = name

        def available(self):
            return True

        def get_daily_prices(self, ticker, outputsize="full"):
            return []

        def get_company(self, ticker):
            return None

        def get_fundamentals(self, ticker):
            return None

        def get_income_statement(self, ticker, period="annual"):
            return []

        def get_balance_sheet(self, ticker, period="annual"):
            return []

        def get_cash_flow(self, ticker, period="annual"):
            return []

        def get_earnings(self, ticker):
            return []

        def get_benchmark_prices(self, ticker, outputsize="full"):
            return []

    prov = _PayloadFixed("stub-provider")
    calls = {"n": 0}

    def fake_http_get(url, params=None, headers=None):
        calls["n"] += 1
        return {"n": calls["n"]}  # payload changes each call

    monkeypatch.setattr(prov, "_http_get", fake_http_get)

    # First fetch: live call, cached.
    p1 = prov._fetch("stub-endpoint", {"symbol": "TST"}, "default")
    assert calls["n"] == 1 and p1 == {"n": 1}

    # Simulate expiry of the cached row (backdate it).
    import sqlite3
    from datetime import datetime, timedelta
    con = sqlite3.connect(tmp_path / "cache.db")
    try:
        con.execute(
            "UPDATE raw_cache SET expires_at = ?",
            ((datetime.now(UTC) - timedelta(minutes=1))
             .strftime("%Y-%m-%dT%H:%M:%SZ"),),
        )
        con.commit()
    finally:
        con.close()

    # Second fetch: cached row is expired, so _fetch goes live again and must
    # OVERWRITE the stale row. Pre-fix this raised IntegrityError.
    p2 = prov._fetch("stub-endpoint", {"symbol": "TST"}, "default")
    assert calls["n"] == 2
    assert p2 == {"n": 2}

    # Exactly one row remains, refreshed with the new payload.
    rows = _raw_cache_rows(tmp_path / "cache.db")
    assert len(rows) == 1
    assert json.loads(rows[0][2]) == {"n": 2}


# --------------------------------------------------------------------------
# Credential hygiene in the shared raw_cache (PROJECT_SPEC §7)
# --------------------------------------------------------------------------
def _raw_cache_rows(db_path):
    import sqlite3
    con = sqlite3.connect(db_path)
    try:
        return con.execute("SELECT key, params_json, payload FROM raw_cache").fetchall()
    finally:
        con.close()


def test_raw_cache_never_stores_credentials(svc_db):
    from app.db import connect
    prov = FixedPriceProvider("any", 5)
    # params_json as stored must be sanitized; cache identity must be computed
    # on the sanitized params so sanitized lookups still hit the same row.
    prov._cache_put("ep", {"symbol": "X", "apikey": "SECRETVALUE"},
                    {"payload": 1}, "default")
    rows = _raw_cache_rows(svc_db)
    assert rows, "expected one cache row"
    _, params_json, payload = rows[0]
    assert "SECRETVALUE" not in params_json
    assert "SECRETVALUE" not in payload
    assert "apikey" not in params_json
    with connect() as conn:  # silence unused-import linters if refactored
        assert conn.execute("SELECT COUNT(*) FROM raw_cache").fetchone()[0] == 1
    hit = prov._cache_get("ep", {"symbol": "X"}, "default")
    assert hit == {"payload": 1}


def test_rejected_payloads_are_never_cached(svc_db):
    prov = FixedPriceProvider("any", 5)
    calls = {"n": 0}

    def fake_http_get(url, params=None, headers=None):
        calls["n"] += 1
        return {"Error Message": "key SECRETVALUE invalid"}

    prov._http_get = fake_http_get  # type: ignore[method-assign]

    def reject(payload):
        raise ProviderError("any", "rejected notice")

    with pytest.raises(ProviderError):
        prov._fetch("ep", {"symbol": "X"}, "default", validate=reject)
    assert calls["n"] == 1
    assert _raw_cache_rows(svc_db) == []  # error body must not persist
    with pytest.raises(ProviderError):           # retry hits the network again
        prov._fetch("ep", {"symbol": "X"}, "default", validate=reject)
    assert calls["n"] == 2


# --------------------------------------------------------------------------
# Price-source selection in the ingestion service
# --------------------------------------------------------------------------
class FixedPriceProvider(DataProvider):
    """Returns a synthetic price series of a fixed length."""

    def __init__(self, name: str, n_bars: int):
        self.name = name
        self._n = n_bars

    def available(self) -> bool:
        return True

    def _series(self):
        idx = pd.bdate_range("2024-01-01", periods=self._n)
        return [S.PriceBar(date=d.date(), close=100.0 + i, adj_close=100.0 + i)
                for i, d in enumerate(idx)]

    def get_daily_prices(self, ticker, outputsize="full"):
        return self._series()

    def get_benchmark_prices(self, ticker, outputsize="full"):
        return self._series()

    def get_company(self, ticker):
        return None

    def get_fundamentals(self, ticker):
        return None

    def get_income_statement(self, ticker, period="annual"):
        return []

    def get_balance_sheet(self, ticker, period="annual"):
        return []

    def get_cash_flow(self, ticker, period="annual"):
        return []

    def get_earnings(self, ticker):
        return []


@pytest.fixture()
def svc_db(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANT_DB_PATH", str(tmp_path / "svc.db"))
    import app.config as cfg
    monkeypatch.setattr(cfg.config, "DB_PATH", str(tmp_path / "svc.db"))
    return tmp_path / "svc.db"


def test_deepest_price_series_wins_over_shorter_first_provider(svc_db):
    shallow = FixedPriceProvider("shallow", 100)   # injected first
    deep = FixedPriceProvider("deep", 400)         # injected second
    report = IngestionService(providers=[shallow, deep]).ingest_ticker("AAPL")
    assert report.prices == {"deep": 400}


def test_short_series_kept_with_honest_validation_note(svc_db):
    shallow = FixedPriceProvider("shallow", 100)   # below MIN_PRICE_BARS
    svc = IngestionService(providers=[shallow])
    report = svc.ingest_ticker("AAPL")
    assert report.prices == {"shallow": 100}       # stored, not discarded
    assert any("short price series" in v for v in report.validation)


def test_no_prices_at_all_is_reported_not_fabricated(svc_db):
    empty = FixedPriceProvider("empty", 0)
    report = IngestionService(providers=[empty]).ingest_ticker("AAPL")
    assert not report.prices
    assert not report.ok()


def test_benchmark_uses_deepest_series(svc_db):
    shallow = FixedPriceProvider("shallow", 100)
    deep = FixedPriceProvider("deep", 400)
    svc = IngestionService(providers=[shallow, deep])
    assert svc.ingest_benchmark("SPY") == 400
