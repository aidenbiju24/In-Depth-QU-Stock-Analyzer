"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  analyze,
  fetchHealth,
  fetchQuote,
  fetchRegime,
  ingest,
  type AnalyzeResponse,
  type Health,
  type Quote,
  type RegimeResponse,
} from "@/lib/api";
import { fmtPct, fmtScore, fmtUSD, pctClass, scoreColor } from "@/lib/format";
import { StatTile } from "@/components/StatTile";

interface Row {
  ticker: string;
  quote: Quote | null;
  analysis: AnalyzeResponse | null;
  error: string | null;
}

const DEFAULT_UNIVERSE = "AAPL,MSFT,NVDA,GOOGL,AMZN";

export default function DashboardPage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [regime, setRegime] = useState<RegimeResponse | null>(null);
  const [universe, setUniverse] = useState(DEFAULT_UNIVERSE);
  const [rows, setRows] = useState<Row[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadHealth = useCallback(() => {
    fetchHealth().then(setHealth).catch(() => setHealth(null));
  }, []);

  useEffect(() => {
    loadHealth();
    fetchRegime()
      .then(setRegime)
      .catch(() => setRegime(null));
  }, [loadHealth]);

  const runScan = async () => {
    setBusy(true);
    setError(null);
    setRows([]);
    const tickers = universe
      .split(",")
      .map((t) => t.trim().toUpperCase())
      .filter(Boolean)
      .slice(0, 12);
    try {
      const out: Row[] = [];
      for (const ticker of tickers) {
        let quote: Quote | null = null;
        let analysis: AnalyzeResponse | null = null;
        let rowError: string | null = null;
        try {
          await ingest(ticker);
        } catch (e) {
          rowError = e instanceof Error ? e.message : String(e);
        }
        if (!rowError) {
          try {
            quote = await fetchQuote(ticker);
          } catch {
            /* price data absent; analysis below will surface the reason */
          }
          try {
            analysis = await analyze(ticker);
          } catch (e) {
            rowError = e instanceof Error ? e.message : String(e);
          }
        }
        out.push({ ticker, quote, analysis, error: rowError });
        setRows([...out]);
      }
    } finally {
      setBusy(false);
    }
  };

  const ranked = rows
    .filter((r) => r.analysis)
    .sort((a, b) => (b.analysis!.quant_score ?? 0) - (a.analysis!.quant_score ?? 0));

  return (
    <div>
      <h1 style={{ fontSize: 18, fontWeight: 700, marginBottom: 4 }}>Dashboard</h1>
      <p className="muted" style={{ marginBottom: 16 }}>
        Quantitative ranking across your research universe. Every score is fully
        traceable on the Stock Research page.
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 16 }}>
        <StatTile
          label="Companies"
          value={health?.row_counts.companies ?? "—"}
          sub={health ? `${health.row_counts.prices ?? 0} price rows stored` : "backend offline"}
        />
        <StatTile
          label="Statements"
          value={health?.row_counts.financial_statements ?? "—"}
          sub={health ? `${health.row_counts.fundamentals ?? 0} fundamental snapshots` : ""}
        />
        <StatTile
          label="Model Runs"
          value={health?.row_counts.model_runs ?? "—"}
          sub="audit trail"
        />
        <StatTile
          label="Market Regime"
          value={regime ? regime.primary_regime.replace("_", " ") : "—"}
          sub={regime ? `${regime.trend} · ${regime.volatility_regime.replace("_", " ")} · ${regime.risk_on_off.replace("_", " ")}` : "ingest SPY/TLT to classify"}
          color={regime ? (regime.primary_regime.includes("bear") || regime.primary_regime.includes("high_vol") ? "var(--red)" : "var(--green)") : undefined}
        />
      </div>

      <div className="panel panel-pad" style={{ marginBottom: 16 }}>
        <div className="panel-title">Universe scan</div>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <input
            className="input"
            style={{ maxWidth: 420 }}
            value={universe}
            onChange={(e) => setUniverse(e.target.value)}
            placeholder="Comma-separated tickers, e.g. AAPL,MSFT,NVDA"
          />
          <button className="btn btn-primary" onClick={runScan} disabled={busy}>
            {busy && <span className="spin" />}
            {busy ? "Scanning…" : "Ingest + Analyze"}
          </button>
          <span className="dim" style={{ fontSize: 12 }}>
            Fetches missing data from providers, then scores each name.
          </span>
        </div>
        {error && <div className="err" style={{ marginTop: 10 }}>{error}</div>}
      </div>

      {rows.length > 0 && (
        <div className="panel" style={{ overflowX: "auto" }}>
          <table className="data">
            <thead>
              <tr>
                <th>#</th>
                <th>Ticker</th>
                <th>Company</th>
                <th style={{ textAlign: "right" }}>Price</th>
                <th style={{ textAlign: "right" }}>QS</th>
                <th style={{ textAlign: "right" }}>Value</th>
                <th style={{ textAlign: "right" }}>Growth</th>
                <th style={{ textAlign: "right" }}>Quality</th>
                <th style={{ textAlign: "right" }}>Momentum</th>
                <th style={{ textAlign: "right" }}>Risk</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {ranked.map((r, i) => {
                const fs = r.analysis!.factor_scores;
                return (
                  <tr key={r.ticker}>
                    <td className="dim">{i + 1}</td>
                    <td style={{ fontWeight: 600 }}>{r.ticker}</td>
                    <td className="muted">{r.quote?.name ?? "—"}</td>
                    <td className="num" style={{ textAlign: "right" }}>
                      {fmtUSD(r.quote?.price ?? null)}
                      {r.quote?.change_pct != null && (
                        <span className={pctClass(r.quote.change_pct)} style={{ marginLeft: 6, fontSize: 12 }}>
                          {fmtPct(r.quote.change_pct)}
                        </span>
                      )}
                    </td>
                    <td className="num" style={{ textAlign: "right", fontWeight: 700, color: scoreColor(r.analysis!.quant_score) }}>
                      {fmtScore(r.analysis!.quant_score)}
                    </td>
                    {(["value", "growth", "quality", "momentum", "risk"] as const).map((f) => (
                      <td
                        key={f}
                        className="num"
                        style={{ textAlign: "right", color: scoreColor(fs[f]) }}
                      >
                        {fmtScore(fs[f])}
                      </td>
                    ))}
                    <td>
                      <Link href={`/research?ticker=${r.ticker}`} className="btn" style={{ padding: "3px 10px", fontSize: 12 }}>
                        Research →
                      </Link>
                    </td>
                  </tr>
                );
              })}
              {rows
                .filter((r) => !r.analysis)
                .map((r) => (
                  <tr key={r.ticker}>
                    <td className="dim">–</td>
                    <td style={{ fontWeight: 600 }}>{r.ticker}</td>
                    <td colSpan={8}>
                      <span className="neg" style={{ fontSize: 12 }}>{r.error ?? "analysis unavailable"}</span>
                    </td>
                    <td></td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
