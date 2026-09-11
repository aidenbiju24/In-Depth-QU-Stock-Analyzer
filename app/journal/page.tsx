"use client";

import { useCallback, useEffect, useState } from "react";
import {
  analyze,
  fetchDecisions,
  fetchQuote,
  ingest,
  recordDecision,
  updateOutcome,
  type DecisionRecord,
} from "@/lib/api";
import { fmtNum, fmtPct, fmtScore, fmtUSD, pctClass, scoreColor } from "@/lib/format";

const DECISIONS = ["BUY", "HOLD", "SELL", "WATCH"];
const OUTCOMES = ["", "OPEN", "WIN", "LOSS", "CLOSED"];

const decisionColor = (d: string) =>
  d === "BUY" ? "var(--green)" : d === "SELL" ? "var(--red)" : "var(--amber)";

export default function JournalPage() {
  const [rows, setRows] = useState<DecisionRecord[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [ok, setOk] = useState<string | null>(null);

  const [ticker, setTicker] = useState("");
  const [decision, setDecision] = useState("BUY");
  const [thesis, setThesis] = useState("");
  const [catalysts, setCatalysts] = useState("");
  const [risks, setRisks] = useState("");
  const [positionSize, setPositionSize] = useState("");

  const load = useCallback(() => {
    fetchDecisions()
      .then((r) => setRows(r))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const record = async () => {
    const t = ticker.trim().toUpperCase();
    if (!t) return;
    setBusy(true);
    setError(null);
    setOk(null);
    try {
      await ingest(t);
      const quote = await fetchQuote(t).catch(() => null);
      const a = await analyze(t);
      // DCF fair value is only recorded when the analyst actually ran a DCF
      // on the research page; the journal never substitutes other numbers.
      const dcfFv: number | null = null;
      const dcfUpside: number | null = null;
      const r = await recordDecision({
        ticker: t,
        decision,
        price: quote?.price ?? null,
        quant_score: a.quant_score,
        value_score: a.factor_scores.value ?? null,
        growth_score: a.factor_scores.growth ?? null,
        quality_score: a.factor_scores.quality ?? null,
        momentum_score: a.factor_scores.momentum ?? null,
        risk_score: a.factor_scores.risk ?? null,
        dcf_fair_value: dcfFv,
        dcf_upside: dcfUpside,
        position_size: positionSize ? parseFloat(positionSize) : null,
        thesis: thesis || null,
        catalysts: catalysts || null,
        risks: risks || null,
      });
      setOk(`Recorded decision #${r.id} for ${t} (QS ${fmtScore(a.quant_score)})`);
      setThesis("");
      setCatalysts("");
      setRisks("");
      setPositionSize("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const setOutcome = async (id: number, outcome: string) => {
    try {
      await updateOutcome(id, outcome);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  return (
    <div>
      <h1 style={{ fontSize: 18, fontWeight: 700, marginBottom: 4 }}>Research Journal</h1>
      <p className="muted" style={{ marginBottom: 16 }}>
        Append-only decision record. Each entry snapshots the full quantitative
        picture at decision time — never overwritten, only outcomes updated.
      </p>

      {error && <div className="err" style={{ marginBottom: 14 }}>{error}</div>}
      {ok && <div className="info" style={{ marginBottom: 14 }}>{ok}</div>}

      <div className="panel panel-pad" style={{ marginBottom: 14 }}>
        <div className="panel-title">Record a decision (auto-snapshots current scores)</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: 12 }}>
          <div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 8 }}>
              <div>
                <label className="label">Ticker</label>
                <input
                  className="input"
                  style={{ textTransform: "uppercase" }}
                  value={ticker}
                  onChange={(e) => setTicker(e.target.value)}
                  placeholder="AAPL"
                />
              </div>
              <div>
                <label className="label">Decision</label>
                <select className="input" value={decision} onChange={(e) => setDecision(e.target.value)}>
                  {DECISIONS.map((d) => <option key={d} value={d}>{d}</option>)}
                </select>
              </div>
            </div>
            <label className="label">Position size (% of book)</label>
            <input
              className="input num"
              value={positionSize}
              onChange={(e) => setPositionSize(e.target.value)}
              type="number"
              step="0.1"
              placeholder="e.g. 5"
            />
            <button
              className="btn btn-primary"
              style={{ marginTop: 10, width: "100%" }}
              onClick={record}
              disabled={busy || !ticker.trim()}
            >
              {busy && <span className="spin" />}
              Record decision
            </button>
          </div>
          <div>
            <label className="label">Investment thesis</label>
            <textarea
              className="input"
              rows={2}
              value={thesis}
              onChange={(e) => setThesis(e.target.value)}
              placeholder="Why this trade, in quantitative terms…"
            />
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginTop: 8 }}>
              <div>
                <label className="label">Catalysts</label>
                <textarea className="input" rows={2} value={catalysts} onChange={(e) => setCatalysts(e.target.value)} />
              </div>
              <div>
                <label className="label">Risks</label>
                <textarea className="input" rows={2} value={risks} onChange={(e) => setRisks(e.target.value)} />
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="panel" style={{ overflowX: "auto" }}>
        <table className="data">
          <thead>
            <tr>
              <th>Date</th>
              <th>Ticker</th>
              <th>Decision</th>
              <th style={{ textAlign: "right" }}>Price</th>
              <th style={{ textAlign: "right" }}>QS</th>
              <th style={{ textAlign: "right" }}>V</th>
              <th style={{ textAlign: "right" }}>G</th>
              <th style={{ textAlign: "right" }}>Q</th>
              <th style={{ textAlign: "right" }}>M</th>
              <th style={{ textAlign: "right" }}>R</th>
              <th style={{ textAlign: "right" }}>Size %</th>
              <th>Thesis</th>
              <th>Outcome</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td className="num dim">{r.decision_date}</td>
                <td style={{ fontWeight: 600 }}>{r.ticker}</td>
                <td style={{ color: decisionColor(r.decision), fontWeight: 700 }}>{r.decision}</td>
                <td className="num" style={{ textAlign: "right" }}>{fmtUSD(r.price)}</td>
                <td className="num" style={{ textAlign: "right", fontWeight: 700, color: scoreColor(r.quant_score) }}>
                  {fmtScore(r.quant_score)}
                </td>
                <td className="num dim" style={{ textAlign: "right" }}>{fmtScore(r.value_score)}</td>
                <td className="num dim" style={{ textAlign: "right" }}>{fmtScore(r.growth_score)}</td>
                <td className="num dim" style={{ textAlign: "right" }}>{fmtScore(r.quality_score)}</td>
                <td className="num dim" style={{ textAlign: "right" }}>{fmtScore(r.momentum_score)}</td>
                <td className="num dim" style={{ textAlign: "right" }}>{fmtScore(r.risk_score)}</td>
                <td className="num" style={{ textAlign: "right" }}>{fmtNum(r.position_size, 1)}</td>
                <td className="muted" style={{ maxWidth: 260, whiteSpace: "normal", fontSize: 12 }}>
                  {r.thesis ?? "—"}
                </td>
                <td>
                  <select
                    className="input"
                    style={{ padding: "3px 6px", fontSize: 12 }}
                    value={r.outcome ?? ""}
                    onChange={(e) => setOutcome(r.id, e.target.value)}
                  >
                    {OUTCOMES.map((o) => (
                      <option key={o} value={o}>{o || "—"}</option>
                    ))}
                  </select>
                </td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={13} className="muted" style={{ textAlign: "center", padding: 24 }}>
                  No decisions recorded yet. Research a stock, then record your
                  first decision with its full score snapshot.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="dim" style={{ fontSize: 11, marginTop: 8 }}>
        Snapshot fields shown: date, ticker, price, QS, V/G/Q/M/R, position size,
        thesis. DCF fair value and upside persist with each record even when not
        displayed. Outcome updates never rewrite the original reasoning.
      </div>
      <div className="dim" style={{ fontSize: 11, marginTop: 2 }}>
        Upside example: a BUY at QS 78 with DCF upside {fmtPct(0.18)} and {pctClass(0.18) ? "positive" : "flat"} momentum.
      </div>
    </div>
  );
}
