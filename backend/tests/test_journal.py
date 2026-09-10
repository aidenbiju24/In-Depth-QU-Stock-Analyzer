"""Research journal + audit trail tests (PROJECT_SPEC §35, METHODOLOGY §55)."""
from __future__ import annotations

import pytest

from app.research import journal


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setenv("QUANT_DB_PATH", str(tmp_path / "test.db"))
    # config.DB_PATH was computed at import; patch it directly too
    import app.config as cfg
    monkeypatch.setattr(cfg.config, "DB_PATH", str(tmp_path / "test.db"))
    yield tmp_path / "test.db"


def test_decision_roundtrip(tmp_db):
    did = journal.record_decision(
        ticker="AAPL", decision="BUY", price=180.0, quant_score=78.5,
        value_score=60, growth_score=80, quality_score=90, momentum_score=70,
        risk_score=65, dcf_fair_value=195.0, dcf_upside=0.083,
        position_size=0.05, thesis="Durable growth at fair price",
        catalysts="New product cycle", risks="Valuation compression")
    rows = journal.list_decisions("AAPL")
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == did
    assert row["decision"] == "BUY"
    assert row["quant_score"] == pytest.approx(78.5)
    assert row["outcome"] is None


def test_decision_rejects_invalid_action(tmp_db):
    with pytest.raises(ValueError):
        journal.record_decision(ticker="AAPL", decision="MAYBE")


def test_decisions_are_append_only(tmp_db):
    journal.record_decision(ticker="MSFT", decision="WATCH", price=400.0)
    journal.record_decision(ticker="MSFT", decision="BUY", price=410.0)
    rows = journal.list_decisions("MSFT")
    assert len(rows) == 2          # history kept, never overwritten
    assert {r["decision"] for r in rows} == {"WATCH", "BUY"}


def test_outcome_update_only_touches_outcome(tmp_db):
    did = journal.record_decision(ticker="NVDA", decision="HOLD", price=900.0,
                                  thesis="Original thesis")
    journal.update_outcome(did, "closed at +12%")
    row = journal.list_decisions("NVDA")[0]
    assert row["outcome"] == "closed at +12%"
    assert row["thesis"] == "Original thesis"


def test_model_run_audit_trail(tmp_db):
    rid = journal.record_model_run(
        model="factor_model", version="1.0", subject="AAPL",
        parameters={"benchmark": "SPY"}, output_summary={"quant_score": 81.2},
        input_as_of="2025-06-30", source_data={"prices": "db"})
    run = journal.get_model_run(rid)
    assert run["model"] == "factor_model"
    assert run["version"] == "1.0"
    assert run["input_as_of"] == "2025-06-30"
    assert run["parameters"]["benchmark"] == "SPY"
    assert run["output"]["quant_score"] == pytest.approx(81.2)
    runs = journal.list_model_runs(subject="AAPL", model="factor_model")
    assert any(r["id"] == rid for r in runs)


def test_portfolio_persistence(tmp_db):
    pid = journal.create_portfolio("Core", benchmark="SPY", cash=1000.0)
    journal.add_position(pid, "AAPL", 10, avg_cost=180.0)
    journal.add_position(pid, "MSFT", 5, avg_cost=400.0)
    p = journal.get_portfolio(pid)
    assert p["name"] == "Core"
    assert len(p["positions"]) == 2
    tickers = {pos["ticker"]: pos for pos in p["positions"]}
    assert tickers["AAPL"]["quantity"] == 10
    # upsert same ticker replaces quantity rather than duplicating
    journal.add_position(pid, "AAPL", 12, avg_cost=182.0)
    p2 = journal.get_portfolio(pid)
    assert len(p2["positions"]) == 2
    assert {pos["ticker"]: pos["quantity"] for pos in p2["positions"]}["AAPL"] == 12
