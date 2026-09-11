"""DataProvider abstraction and shared plumbing.

Every provider:
- fetches raw payloads (via _http_get),
- caches raw responses in raw_cache with a TTL (PROJECT_SPEC.md §38),
- reports usage into api_usage so we can respect free-tier budgets,
- normalizes into internal schemas (schemas.py) — the rest of the app never
  sees provider-specific shapes.

SEC EDGAR intentionally has no API key: data.sec.gov requires only an
identifying User-Agent header (PROJECT_SPEC.md §8).
"""
from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from typing import Any

import requests

from ..config import config
from ..db import connect, today, utcnow
from ..errors import ProviderError, RateLimitError

_TTL_SECONDS = {
    "quote": 300,
    "prices": 12 * 3600,
    "profile": 24 * 3600,
    "fundamentals": 6 * 3600,
    "statements": 24 * 3600,
    "earnings": 6 * 3600,
    "sec_facts": 24 * 3600,
    "default": 3600,
}


# Query parameters that must never be persisted to raw_cache (PROJECT_SPEC §7:
# no credentials in storage, logs, or API responses). Cache identity is
# computed on the sanitized params — safe because a credential is constant
# for a given provider configuration, so it carries no extra distinction.
_SECRET_PARAMS = frozenset({"apikey", "api_key", "token", "access_token"})


def _sanitize_params(params: dict) -> dict:
    return {k: v for k, v in params.items()
            if str(k).lower() not in _SECRET_PARAMS}


class DataProvider(ABC):
    """Common interface for financial data providers."""

    name: str = "base"

    # ---------------- HTTP ----------------
    def _http_get(self, url: str, params: dict | None = None,
                  headers: dict | None = None) -> Any:
        try:
            resp = requests.get(
                url, params=params or {}, headers=headers or {},
                timeout=config.HTTP_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise ProviderError(self.name, f"network error: {exc}") from exc
        if resp.status_code == 429:
            raise RateLimitError(self.name, "HTTP 429 rate limited")
        if resp.status_code >= 400:
            raise ProviderError(self.name, f"HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError as exc:
            raise ProviderError(self.name, "non-JSON response") from exc

    # ---------------- Cache + usage ----------------
    @staticmethod
    def _cache_key(endpoint: str, params: dict) -> str:
        flat = json.dumps(_sanitize_params(params), sort_keys=True, default=str)
        digest = hashlib.sha256(f"{endpoint}|{flat}".encode()).hexdigest()[:32]
        return f"{digest}"

    def _cache_get(self, endpoint: str, params: dict, kind: str) -> Any | None:
        key = self._cache_key(endpoint, params)
        with connect() as conn:
            row = conn.execute(
                "SELECT payload, expires_at FROM raw_cache WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        if row["expires_at"] <= utcnow():
            return None
        return json.loads(row["payload"])

    def _cache_put(self, endpoint: str, params: dict, payload: Any, kind: str) -> None:
        key = self._cache_key(endpoint, params)
        ttl = _TTL_SECONDS.get(kind, _TTL_SECONDS["default"])
        expires = (
            datetime.now(UTC) + timedelta(seconds=ttl)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Credentials are stripped before anything touches the database.
        # Upsert: an expired row keeps its (unique) key until replaced, so a
        # re-fetch after expiry must overwrite it — a plain INSERT would raise
        # IntegrityError on every refresh and 500 the request.
        with connect() as conn:
            conn.execute(
                "INSERT INTO raw_cache (key, source, endpoint, params_json, payload,"
                " retrieved_at, expires_at) VALUES (?,?,?,?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET source = excluded.source,"
                " endpoint = excluded.endpoint, params_json = excluded.params_json,"
                " payload = excluded.payload, retrieved_at = excluded.retrieved_at,"
                " expires_at = excluded.expires_at",
                (key, self.name, endpoint,
                 json.dumps(_sanitize_params(params), default=str),
                 json.dumps(payload), utcnow(), expires),
            )

    def _record_usage(self) -> None:
        with connect() as conn:
            conn.execute(
                "INSERT INTO api_usage (day, source, calls) VALUES (?,?,1) "
                "ON CONFLICT(day, source) DO UPDATE SET calls = calls + 1",
                (today(), self.name),
            )

    def calls_today(self) -> int:
        with connect() as conn:
            row = conn.execute(
                "SELECT calls FROM api_usage WHERE day = ? AND source = ?",
                (today(), self.name),
            ).fetchone()
        return int(row["calls"]) if row else 0

    def _fetch(self, endpoint: str, params: dict, kind: str,
               headers: dict | None = None, url: str | None = None,
               validate: Any | None = None) -> Any:
        """Cached fetch: DB first, then live request. Records usage on live calls.

        `validate(payload)` may raise (e.g. ProviderError) to reject a payload:
        rejected payloads are NEVER cached, so provider error bodies — which
        sometimes echo the apikey — cannot persist to the database.
        """
        cached = self._cache_get(endpoint, params, kind)
        if cached is not None:
            if validate is not None:
                validate(cached)  # legacy rows must not silently serve garbage
            return cached
        payload = self._http_get(url or endpoint, params=params, headers=headers)
        if validate is not None:
            validate(payload)
        self._record_usage()
        self._cache_put(endpoint, params, payload, kind)
        return payload

    # ---------------- Public interface ----------------
    @abstractmethod
    def available(self) -> bool:
        """Whether this provider is configured (credentials present, if any)."""

    @abstractmethod
    def get_daily_prices(self, ticker: str, outputsize: str = "full") -> list:
        """Adjusted daily price history (oldest -> newest)."""

    @abstractmethod
    def get_company(self, ticker: str):
        """Normalized Company profile."""

    @abstractmethod
    def get_fundamentals(self, ticker: str):
        """Point-in-time fundamental snapshot."""

    @abstractmethod
    def get_income_statement(self, ticker: str, period: str = "annual") -> list:
        """Normalized income statements, newest first."""

    @abstractmethod
    def get_balance_sheet(self, ticker: str, period: str = "annual") -> list:
        """Normalized balance sheets, newest first."""

    @abstractmethod
    def get_cash_flow(self, ticker: str, period: str = "annual") -> list:
        """Normalized cash-flow statements, newest first."""

    @abstractmethod
    def get_earnings(self, ticker: str) -> list:
        """Earnings history with actual vs estimated EPS."""

    @abstractmethod
    def get_benchmark_prices(self, ticker: str, outputsize: str = "full") -> list:
        """Daily prices for a benchmark index/ETF (same normalization)."""
