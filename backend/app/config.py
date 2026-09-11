"""Application configuration and model versions.

Secrets come ONLY from environment variables (.env.local is loaded here via
python-dotenv when present). Values are never logged or returned by the API.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load developer secrets. Both locations are honored so the file can live
# beside the frontend (.env.local at the repo root, where Next.js expects it)
# or beside the backend. Files loaded later never override variables already
# set in the OS environment or an earlier file; real OS env always wins.
_BACKEND_DIR = Path(__file__).resolve().parent.parent      # backend/
_REPO_ROOT = _BACKEND_DIR.parent                            # repo root
load_dotenv(_REPO_ROOT / ".env.local")
load_dotenv(_BACKEND_DIR / ".env.local")

# --------------------------------------------------------------------------
# Model versions (METHODOLOGY.md §54). Increment when methodology changes
# materially so historical results stay unambiguous.
# --------------------------------------------------------------------------
FACTOR_MODEL_VERSION = "1.0"
DCF_MODEL_VERSION = "1.0"
RISK_MODEL_VERSION = "1.0"
PORTFOLIO_OPTIMIZER_VERSION = "1.0"
BACKTEST_ENGINE_VERSION = "1.0"
MONTE_CARLO_VERSION = "1.0"


def _db_path() -> str:
    return os.environ.get("QUANT_DB_PATH", str(_BACKEND_DIR / "data" / "quant.db"))


def _clean_secret(raw: str | None) -> str:
    """Trim a secret and treat unfilled placeholders as absent.

    .env.local ships with template values like <PASTE_YOUR_KEY_HERE>; those
    must read as "not configured" (providers then fail fast with a clear
    message) rather than as garbage credentials sent to the provider.
    """
    v = (raw or "").strip().strip('"').strip("'")
    if not v or v.startswith("<"):
        return ""
    return v


class Config:
    """Central, read-only configuration accessor."""

    # --- Credentials (never logged, never serialized) ---
    ALPHA_VANTAGE_API_KEY: str = _clean_secret(os.environ.get("ALPHA_VANTAGE_API_KEY"))
    FMP_API_KEY: str = _clean_secret(os.environ.get("FMP_API_KEY"))
    # SEC EDGAR does NOT use an API key. data.sec.gov requires an identifying
    # User-Agent header like "CompanyName AdminContact@example.com". If the env
    # var is unset OR left as an unfilled template placeholder, fall back to a
    # generic identifying UA so public SEC endpoints stay usable.
    SEC_USER_AGENT: str = (
        _clean_secret(os.environ.get("SEC_USER_AGENT"))
        or "In-Depth-Quant-Stock-Analyzer research@example.com"
    )

    # --- Database ---
    DB_PATH: str = _db_path()

    # --- Provider behaviour ---
    HTTP_TIMEOUT: float = float(os.environ.get("HTTP_TIMEOUT", "20"))
    # Free-tier daily budgets (kept conservative; engine stops early instead of
    # hammering providers through rate limits).
    AV_DAILY_BUDGET: int = int(os.environ.get("AV_DAILY_BUDGET", "20"))

    # --- Financial defaults (configurable; METHODOLOGY.md §7/§30/§43) ---
    RISK_FREE_RATE: float = float(os.environ.get("RISK_FREE_RATE", "0.04"))
    TRADING_DAYS: int = 252
    MONTE_CARLO_DEFAULT_SIMS: int = 10_000


config = Config()


def missing_credentials() -> dict[str, bool]:
    """Report which optional credentials are absent (booleans only, no values)."""
    return {
        "alpha_vantage": not config.ALPHA_VANTAGE_API_KEY,
        "fmp": not config.FMP_API_KEY,
        "sec_user_agent": not config.SEC_USER_AGENT,
    }
