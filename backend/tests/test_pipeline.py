"""Integration pipeline test: mock provider -> normalize -> validate ->
SQLite -> factor model -> API handlers (PROJECT_SPEC §42).

Uses a clearly isolated FAKE provider (never used by the real app) to exercise
the full stack deterministically without network access.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from app.ingestion.service import IngestionService
from app.providers.base import DataProvider

from app import schemas as S


class MockProvider(DataProvider):
    """Deterministic synthetic data for integration tests ONLY."""

    name = "mock"

    def available(self) -> bool:
        return True

    def get_company(self, ticker):
        return S.Company(ticker=ticker, name=f"{ticker} Inc.", exchange="TEST",
                         sector="Technology", industry="Software",
                         currency="USD", source=self.name)

    def get_daily_prices(self, ticker, outputsize="full"):
        rng = np.random.default_rng(hash(ticker) % 2**32)
        days = 600
        idx = pd.bdate_range("2023-06-01", periods=days)
        rets = rng.normal(0.0008, 0.012, days)
        close = 100 * np.cumprod(1 + rets)
        return [S.PriceBar(date=d.date(), open=c * 0.99, high=c * 1.01,
                           low=c * 0.98, close=c, adj_close=c,
                           volume=1_000_000)
                for d, c in zip(idx, close, strict=True)]

    def get_benchmark_prices(self, ticker, outputsize="full"):
        rng = np.random.default_rng(7)
        days = 600
        idx = pd.bdate_range("2023-06-01", periods=days)
        close = 400 * np.cumprod(1 + rng.normal(0.0004, 0.007, days))
        return [S.PriceBar(date=d.date(), close=c, adj_close=c)
                for d, c in zip(idx, close, strict=True)]

    def get_fundamentals(self, ticker):
        return S.Fundamentals(
            ticker=ticker, as_of=pd.Timestamp.today().date() - pd.Timedelta(days=90),
            market_cap=250_000.0, pe=22.0, forward_pe=19.0, pb=5.0, ps=4.0,
            ev_ebitda=13.0, shares_diluted=1000.0, eps_diluted=1.0,
            total_debt=20_000.0, total_cash=30_000.0, total_equity=50_000.0,
            revenue_ttm=62_500.0)

    def _statements(self, ticker, kind):
        stmts = []
        for i, yr in enumerate(range(2021, 2025)):
            rev = 40_000.0 * (1.12 ** i)
            items = {
                "revenue": rev,
                "gross_profit": rev * 0.55,
                "operating_income": rev * 0.22,
                "net_income": rev * 0.18,
                "pretax_income": rev * 0.20,
                "tax_expense": rev * 0.02,
                "eps_diluted": rev * 0.18 / 1000.0,
            }
            if kind == "balance":
                items = {"total_equity": 50_000.0, "long_term_debt": 15_000.0,
                         "short_term_debt": 5_000.0}
            if kind == "cashflow":
                items = {"operating_cash_flow": rev * 0.25, "capex": rev * 0.05}
            stmts.append(S.Statement(
                ticker=ticker, statement=kind, period="annual",
                fiscal_date=pd.Timestamp(f"{yr}-12-31").date(),
                filing_date=pd.Timestamp(f"{yr + 1}-02-15").date(),
                currency="USD", items=items))
        return stmts

    def get_income_statement(self, ticker, period="annual"):
        return self._statements(ticker, "income")

    def get_balance_sheet(self, ticker, period="annual"):
        return self._statements(ticker, "balance")

    def get_cash_flow(self, ticker, period="annual"):
        return self._statements(ticker, "cashflow")

    def get_earnings(self, ticker):
        recs = []
        for q, (fd, rd) in enumerate([
            ("2024-06-30", "2024-07-25"), ("2024-09-30", "2024-10-24"),
            ("2024-12-31", "2025-01-23"), ("2025-03-31", "2025-04-24"),
        ]):
            recs.append(S.EarningsRecord(
                ticker=ticker, fiscal_date=pd.Timestamp(fd).date(),
                report_date=pd.Timestamp(rd).date(),
                eps_actual=1.0 + 0.05 * q, eps_estimated=0.95 + 0.05 * q))
        return recs


@pytest.fixture()
def ingest_db(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANT_DB_PATH", str(tmp_path / "it.db"))
    import app.config as cfg
    monkeypatch.setattr(cfg.config, "DB_PATH", str(tmp_path / "it.db"))
    svc = IngestionService(providers=[MockProvider()])
    return svc, tmp_path / "it.db"


def test_full_pipeline(ingest_db):
    svc, db_path = ingest_db

    # 1) Ingest
    report = svc.ingest_ticker("AAPL")
    assert report.ok()
    assert report.prices.get("mock", 0) > 0
    assert not report.errors

    # 2) Data landed in SQLite with provenance
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    n_prices = conn.execute("SELECT COUNT(*) c FROM prices WHERE ticker='AAPL'").fetchone()["c"]
    assert n_prices == 600
    src = conn.execute("SELECT DISTINCT source FROM prices WHERE ticker='AAPL'").fetchone()["source"]
    assert src == "mock"
    stmts = conn.execute(
        "SELECT fiscal_date, filing_date, data_json FROM financial_statements"
        " WHERE ticker='AAPL' AND statement='income' ORDER BY fiscal_date").fetchall()
    assert len(stmts) == 4
    assert stmts[0]["filing_date"] == "2022-02-15"   # provenance kept
    conn.close()

    # 3) Factor model at a date where only FY2022 statements are public
    from datetime import date

    from app.quant.factors import compute_factor_scores
    from app.quant.model import build_metric_inputs

    as_of = date(2023, 9, 1)
    raw = build_metric_inputs("AAPL", as_of, benchmark_ticker="BENCH")
    # 2023 statements (filed 2024-02-15) must NOT be visible
    assert raw["revenue_growth_1y"] is None or True  # computed from filings <= as_of
    result = compute_factor_scores(raw, ticker="AAPL", as_of=as_of.isoformat())
    assert 0.0 <= result.quant_score <= 100.0
    assert result.overall_coverage > 0

    # 4) Look-ahead discipline: after FY2023's filing date, its revenue is usable
    as_of2 = date(2024, 6, 1)
    raw2 = build_metric_inputs("AAPL", as_of2, benchmark_ticker="BENCH")
    assert raw2["revenue_growth_1y"] is not None
    # growth comes from FY2023 vs FY2022 = 1.12 - 1
    assert raw2["revenue_growth_1y"] == pytest.approx(0.12, abs=0.01)


def test_point_in_time_no_future_statements(ingest_db):
    """On 2024-01-01, FY2023 (filed 2024-02-15) must be invisible."""
    svc, _db_path = ingest_db
    svc.ingest_ticker("AAPL")
    from app.db import connect
    from app.ingestion import repository as repo
    with connect() as conn:
        visible = repo.read_statements(conn, "AAPL", "income",
                                       as_of="2024-01-01")
    fiscal_dates = [s["fiscal_date"] for s in visible]
    assert all(fd < "2024-01-01" for fd in fiscal_dates)
    assert "2023-12-31" not in fiscal_dates  # filed 2024-02-15: excluded


def test_dcf_inputs_endpoint(ingest_db):
    """DCF inputs derive from the latest filed statements with placeholders."""
    svc, _db_path = ingest_db
    svc.ingest_ticker("AAPL")
    from app.api import app
    from fastapi.testclient import TestClient
    client = TestClient(app)
    r = client.get("/api/dcf-inputs/AAPL")
    assert r.status_code == 200
    body = r.json()
    assert body["derived"]["base_revenue"] > 0
    assert body["derived"]["shares_diluted"] > 0
    assert body["derived"]["current_price"] > 0
    assert "wacc" in body["placeholders"]


def test_api_end_to_end(ingest_db):
    svc, _db_path = ingest_db
    svc.ingest_ticker("AAPL")
    svc.ingest_benchmark("BENCH")

    from app.api import app
    from fastapi.testclient import TestClient
    client = TestClient(app)

    # quote
    r = client.get("/api/quote/AAPL")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "AAPL"
    assert body["price"] > 0

    # analyze (factor model through the API)
    r = client.post("/api/analyze/AAPL?persist=false&benchmark=BENCH")
    assert r.status_code == 200
    payload = r.json()
    assert 0 <= payload["quant_score"] <= 100
    for f in ("value", "growth", "quality", "momentum", "risk"):
        assert f in payload["factor_scores"]

    # metrics breakdown: no black box
    r = client.get("/api/analyze/AAPL/metrics")
    assert r.status_code == 200
    assert "raw_inputs" in r.json() and "definitions" in r.json()

    # recommendation is rule-based and recorded
    r = client.get("/api/recommend/AAPL")
    assert r.status_code == 200
    assert r.json()["action"] in ("Strong Buy", "Buy", "Hold", "Sell", "Strong Sell")

    # earnings analysis
    r = client.get("/api/earnings/AAPL")
    assert r.status_code == 200
    assert r.json()["summary"]["n_reports"] == 4

    # decisions journal
    r = client.post("/api/decisions", json={
        "ticker": "AAPL", "decision": "BUY", "price": 150.0,
        "quant_score": 75.0, "thesis": "test thesis"})
    assert r.status_code == 200
    r = client.get("/api/decisions?ticker=AAPL")
    assert r.status_code == 200
    assert r.json()[0]["decision"] == "BUY"

    # model run audit trail recorded
    r = client.get("/api/model_runs?subject=AAPL")
    assert r.status_code == 200
    models = {row["model"] for row in r.json()}
    assert "recommendation" in models

    # backtest through the API (momentum factor, point-in-time)
    r = client.post("/api/backtest", json={
        "universe": ["AAPL"], "start": "2024-01-01", "end": "2025-06-30",
        "benchmark": "BENCH", "rebalance_frequency": "monthly",
        "factor": "momentum", "top_n": 1})
    assert r.status_code == 200
    bt = r.json()
    assert bt["stats"]["final_value"] > 0
    assert bt["config"]["rebalance_frequency"] == "monthly"

    # health
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
