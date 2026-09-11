"""SQLite persistence layer.

Design notes (PROJECT_SPEC.md §9, METHODOLOGY.md §55):
- Every row carries provenance: source, retrieval timestamp, and where relevant
  the observation date / fiscal period.
- Normalized (statement-level) facts are keyed by (ticker, statement, fiscal
  period, source). On re-ingest we UPDATE the same row rather than silently
  creating conflicting duplicates; raw API payloads are preserved in raw_cache.
- factor_scores / valuations / risk_metrics rows are immutable model-run output:
  a new run inserts a new row keyed by model_run_id.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from .config import config

_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS companies (
    ticker            TEXT PRIMARY KEY,
    name              TEXT,
    exchange          TEXT,
    sector            TEXT,
    industry          TEXT,
    currency          TEXT,
    description       TEXT,
    source            TEXT NOT NULL,
    retrieved_at      TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prices (
    ticker       TEXT NOT NULL,
    date         TEXT NOT NULL,
    open         REAL, high REAL, low REAL, close REAL,
    adj_close    REAL,
    volume       REAL,
    source       TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    PRIMARY KEY (ticker, date, source)
);
CREATE INDEX IF NOT EXISTS idx_prices_ticker_date ON prices(ticker, date);

CREATE TABLE IF NOT EXISTS financial_statements (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker         TEXT NOT NULL,
    statement      TEXT NOT NULL,          -- income | balance | cashflow
    period          TEXT NOT NULL,          -- annual | quarterly
    fiscal_date     TEXT NOT NULL,          -- fiscal period end date (observation date)
    filing_date     TEXT,                   -- when it became public (SEC accessTime / filing date)
    currency       TEXT,
    data_json      TEXT NOT NULL,          -- normalized line items (JSON object)
    source         TEXT NOT NULL,
    retrieved_at   TEXT NOT NULL,
    UNIQUE (ticker, statement, period, fiscal_date, source)
);
CREATE INDEX IF NOT EXISTS idx_fs_ticker ON financial_statements(ticker, statement, fiscal_date);

CREATE TABLE IF NOT EXISTS fundamentals (
    ticker         TEXT NOT NULL,
    as_of          TEXT NOT NULL,          -- date the snapshot is valid for (public knowledge date)
    market_cap     REAL, pe REAL, forward_pe REAL, pb REAL, ps REAL,
    ev_ebitda      REAL, dividend_yield REAL, beta_5y REAL,
    eps REAL, eps_diluted REAL, shares_diluted REAL, book_value_per_share REAL,
    revenue_ttm REAL, net_income_ttm REAL, ebitda_ttm REAL,
    free_cash_flow_ttm REAL, operating_cash_flow_ttm REAL, capex_ttm REAL,
    total_debt REAL, total_cash REAL, total_equity REAL, total_assets REAL,
    gross_profit_ttm REAL, operating_income_ttm REAL,
    currency       TEXT,
    source         TEXT NOT NULL,
    retrieved_at   TEXT NOT NULL,
    PRIMARY KEY (ticker, as_of, source)
);

CREATE TABLE IF NOT EXISTS earnings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker         TEXT NOT NULL,
    fiscal_date    TEXT NOT NULL,          -- fiscal period end
    report_date    TEXT,                   -- date result became public
    eps_actual     REAL, eps_estimated REAL,
    revenue_actual REAL, revenue_estimated REAL,
    source         TEXT NOT NULL,
    retrieved_at   TEXT NOT NULL,
    UNIQUE (ticker, fiscal_date, source)
);

CREATE TABLE IF NOT EXISTS technical_indicators (
    ticker       TEXT NOT NULL,
    date         TEXT NOT NULL,
    indicator    TEXT NOT NULL,            -- sma_50, sma_200, rsi_14 ...
    value        REAL,
    source       TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    PRIMARY KEY (ticker, date, indicator)
);

CREATE TABLE IF NOT EXISTS model_runs (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    model          TEXT NOT NULL,          -- factor_model | dcf | risk | optimizer | backtest | monte_carlo
    version        TEXT NOT NULL,
    subject        TEXT NOT NULL,          -- ticker or portfolio id
    run_at         TEXT NOT NULL,          -- UTC timestamp
    input_as_of    TEXT,                   -- data cutoff used (point-in-time guarantee)
    parameters     TEXT NOT NULL,          -- JSON
    output         TEXT NOT NULL,          -- JSON (result summary)
    source_data    TEXT                    -- JSON: providers/dates feeding the run
);

CREATE TABLE IF NOT EXISTS factor_scores (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    model_run_id   INTEGER NOT NULL REFERENCES model_runs(id),
    ticker         TEXT NOT NULL,
    as_of          TEXT NOT NULL,
    universe       TEXT,                   -- label of comparison universe
    value_score REAL, growth_score REAL, quality_score REAL,
    momentum_score REAL, risk_score REAL, quant_score REAL,
    components_json TEXT NOT NULL,         -- per-metric inputs + normalization detail
    coverage       REAL,                   -- data coverage fraction 0-1
    version        TEXT NOT NULL,
    UNIQUE (model_run_id, ticker, as_of)
);
CREATE INDEX IF NOT EXISTS idx_fs_scores_ticker ON factor_scores(ticker, as_of);

CREATE TABLE IF NOT EXISTS valuations (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    model_run_id   INTEGER NOT NULL REFERENCES model_runs(id),
    ticker         TEXT NOT NULL,
    as_of          TEXT NOT NULL,
    fair_value     REAL, current_price REAL,
    upside         REAL,                   -- (fv - price) / price
    enterprise_value REAL, equity_value REAL,
    assumptions_json TEXT NOT NULL,
    version        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS risk_metrics (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    model_run_id   INTEGER NOT NULL REFERENCES model_runs(id),
    subject        TEXT NOT NULL,          -- ticker or portfolio id
    as_of          TEXT NOT NULL,
    annual_vol REAL, beta REAL, sharpe REAL, sortino REAL,
    max_drawdown REAL, var_95 REAL, expected_shortfall_95 REAL,
    downside_deviation REAL, win_rate REAL,
    version        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backtests (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    model_run_id   INTEGER NOT NULL REFERENCES model_runs(id),
    name           TEXT NOT NULL,
    strategy       TEXT NOT NULL,
    universe       TEXT NOT NULL,
    start_date     TEXT NOT NULL, end_date TEXT NOT NULL,
    benchmark      TEXT NOT NULL,
    rebalance_freq TEXT NOT NULL,
    initial_capital REAL NOT NULL,
    config_json    TEXT NOT NULL,          -- full parameter record
    result_json    TEXT NOT NULL,          -- performance + equity curve
    version        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolios (
    id             TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    benchmark      TEXT,
    cash           REAL NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS portfolio_positions (
    portfolio_id TEXT NOT NULL REFERENCES portfolios(id),
    ticker       TEXT NOT NULL,
    quantity     REAL NOT NULL,
    avg_cost     REAL,
    added_at     TEXT NOT NULL,
    PRIMARY KEY (portfolio_id, ticker)
);

CREATE TABLE IF NOT EXISTS research_decisions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at     TEXT NOT NULL,
    decision_date  TEXT NOT NULL,
    ticker         TEXT NOT NULL,
    price          REAL,
    quant_score REAL, value_score REAL, growth_score REAL,
    quality_score REAL, momentum_score REAL, risk_score REAL,
    dcf_fair_value REAL, dcf_upside REAL,
    decision       TEXT NOT NULL CHECK (decision IN ('BUY','HOLD','SELL','WATCH')),
    position_size  REAL,
    thesis         TEXT, catalysts TEXT, risks TEXT,
    outcome        TEXT,                   -- filled later; never overwrite prior rows
    model_run_id   INTEGER
);

CREATE TABLE IF NOT EXISTS raw_cache (
    key          TEXT PRIMARY KEY,         -- provider:endpoint:params hash
    source       TEXT NOT NULL,
    endpoint     TEXT NOT NULL,
    params_json  TEXT NOT NULL,
    payload      TEXT NOT NULL,            -- raw provider response (JSON)
    retrieved_at TEXT NOT NULL,
    expires_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_usage (
    day          TEXT NOT NULL,
    source       TEXT NOT NULL,
    calls        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, source)
);
"""


def utcnow() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def connect() -> sqlite3.Connection:
    """Open a connection in autocommit mode with WAL + busy timeout.

    Autocommit is deliberate: ingestion holds a connection across slow provider
    HTTP calls, and an implicit write transaction there would block the
    provider layer's usage-tracking writes ("database is locked"). With
    isolation_level=None each statement commits immediately, so writers only
    contend for milliseconds. WAL lets readers proceed during those writes.
    """
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=10.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    conn.executescript(_SCHEMA)
    return conn


@contextmanager
def db():
    """Transactional connection context; commits on success, rolls back on error."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
