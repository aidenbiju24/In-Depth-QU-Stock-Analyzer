"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  analyze,
  fetchDCFInputs,
  fetchEarnings,
  fetchMetricsBreakdown,
  fetchQuote,
  fetchRecommendation,
  ingest,
  runBacktest,
  runDCF,
  runMonteCarlo,
  runSensitivity,
  type AnalyzeResponse,
  type DCFRequest,
  type DCFResponse,
  type EarningsResponse,
  type MetricsBreakdown,
  type MonteCarloResponse,
  type Quote,
  type RecommendationResponse,
  type SensitivityResponse,
} from "@/lib/api";
import { ScoreBar, StatTile } from "@/components/StatTile";
import { EquityChart } from "@/components/charts";
import {
  actionColor,
  fmtNum,
  fmtPct,
  fmtScore,
  fmtUSD,
  pctClass,
  scoreColor,
} from "@/lib/format";

const FACTOR_META: { key: string; label: string; weight: number }[] = [
  { key: "value", label: "Value", weight: 0.2 },
  { key: "growth", label: "Growth", weight: 0.2 },
  { key: "quality", label: "Quality", weight: 0.25 },
  { key: "momentum", label: "Momentum", weight: 0.2 },
  { key: "risk", label: "Risk", weight: 0.15 },
];

function ResearchInner() {
  const params = useSearchParams();
  const [ticker, setTicker] = useState("");
  const [loaded, setLoaded] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [quote, setQuote] = useState<Quote | null>(null);
  const [analysis, setAnalysis] = useState<AnalyzeResponse | null>(null);
  const [breakdown, setBreakdown] = useState<MetricsBreakdown | null>(null);
  const [earnings, setEarnings] = useState<EarningsResponse | null>(null);
  const [rec, setRec] = useState<RecommendationResponse | null>(null);
  const [dcf, setDcf] = useState<DCFResponse | null>(null);
  const [sens, setSens] = useState<SensitivityResponse | null>(null);
  const [mc, setMc] = useState<MonteCarloResponse | null>(null);
  const [dcfForm, setDcfForm] = useState<DCFRequest | null>(null);
  const [dcfMissing, setDcfMissing] = useState<string[]>([]);
  const [dcfNote, setDcfNote] = useState<string | null>(null);
  const [bt, setBt] = useState<Awaited<ReturnType<typeof runBacktest>> | null>(null);
  const [btBusy, setBtBusy] = useState(false);

  const load = useCallback(async (t: string) => {
    const tk = t.trim().toUpperCase();
    if (!tk) return;
    setBusy(true);
    setError(null);
    setLoaded(null);
    setQuote(null);
    setAnalysis(null);
    setBreakdown(null);
    setEarnings(null);
    setRec(null);
    setDcf(null);
    setSens(null);
    setMc(null);
    setDcfForm(null);
    setDcfMissing([]);
    setDcfNote(null);
    setBt(null);
    try {
      try {
        await ingest(tk);
      } catch {
        /* providers may be unconfigured; stored data may still suffice */
      }
      try {
        const q = await fetchQuote(tk);
        setQuote(q);
      } catch {
        /* covered by analysis error below */
      }
      const a = await analyze(tk);
      setAnalysis(a);
      try {
        setBreakdown(await fetchMetricsBreakdown(tk));
      } catch {
        /* breakdown is supplementary */
      }
      try {
        setEarnings(await fetchEarnings(tk));
      } catch {
        /* earnings optional */
      }
      try {
        setRec(await fetchRecommendation(tk));
      } catch {
        /* recommendation optional */
      }
      try {
        const di = await fetchDCFInputs(tk);
        setDcfForm({
          base_revenue: di.derived.base_revenue ?? 0,
          revenue_growth: [di.derived.revenue_growth_1y ?? 0.05],
          ebit_margin: di.derived.ebit_margin ?? 0.15,
          tax_rate: di.derived.effective_tax_rate ?? 0.21,
          capex_pct_revenue: di.derived.capex_pct_revenue ?? 0.05,
          depreciation_pct_revenue: di.derived.depreciation_pct_revenue ?? 0.03,
          wc_change_pct_revenue: di.placeholders.wc_change_pct_revenue,
          wacc: di.placeholders.wacc,
          terminal_growth: di.placeholders.terminal_growth,
          net_debt: di.derived.net_debt ?? 0,
          shares_diluted: di.derived.shares_diluted ?? 1,
          current_price: di.derived.current_price ?? null,
        });
        setDcfMissing(di.missing);
        setDcfNote(
          `Derived from the ${di.fiscal_date} filing. WACC, terminal growth and ` +
            `working-capital change are analyst placeholders — override them.`
        );
      } catch {
        /* DCF section simply unavailable without statements */
      }
      setLoaded(tk);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    const t = params.get("ticker");
    if (t) {
      // Defer to a microtask: the effect body only reacts to the URL, it
      // never sets state synchronously (React compiler lint rule).
      Promise.resolve().then(() => {
        setTicker(t);
        void load(t);
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const runDcfNow = async () => {
    if (!dcfForm || !loaded) return;
    setError(null);
    try {
      setDcf(await runDCF(loaded, dcfForm));
      setSens(await runSensitivity(loaded, dcfForm));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const runMcNow = async () => {
    if (!loaded) return;
    try {
      setMc(await runMonteCarlo(loaded, 10_000, 42));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const runBtNow = async () => {
    if (!loaded || !analysis) return;
    setBtBusy(true);
    try {
      const end = new Date().toISOString().slice(0, 10);
      const start = new Date(Date.now() - 365 * 24 * 3600 * 1000).toISOString().slice(0, 10);
      setBt(
        await runBacktest({
          universe: [loaded, "SPY"],
          start,
          end,
          benchmark: "SPY",
          rebalance_frequency: "monthly",
          top_n: 1,
          factor: "momentum",
        })
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBtBusy(false);
    }
  };

  const field = (
    key: keyof DCFRequest,
    label: string,
    step = 0.005
  ) => {
    if (!dcfForm) return null;
    const raw = dcfForm[key];
    const isList = Array.isArray(raw);
    return (
      <div>
        <label className="label">{label}</label>
        <input
          className="input num"
          type="number"
          step={step}
          value={isList ? (raw as number[])[0] ?? 0 : String(raw ?? "")}
          onChange={(e) => {
            const v = parseFloat(e.target.value);
            setDcfForm((f) => {
              if (!f) return f;
              if (isList) return { ...f, [key]: [Number.isFinite(v) ? v : 0] };
              return { ...f, [key]: Number.isFinite(v) ? v : 0 };
            });
          }}
        />
      </div>
    );
  };

  return (
    <div>
      <h1 style={{ fontSize: 18, fontWeight: 700, marginBottom: 4 }}>Stock Research</h1>
      <p className="muted" style={{ marginBottom: 16 }}>
        Enter a ticker, ingest data, and inspect every number behind the scores.
      </p>

      <div className="panel panel-pad" style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            className="input"
            style={{ maxWidth: 200, textTransform: "uppercase" }}
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && load(ticker)}
            placeholder="AAPL"
          />
          <button className="btn btn-primary" onClick={() => load(ticker)} disabled={busy || !ticker.trim()}>
            {busy && <span className="spin" />}
            {busy ? "Loading…" : "Analyze"}
          </button>
        </div>
      </div>

      {error && <div className="err" style={{ marginBottom: 14 }}>{error}</div>}

      {analysis && (
        <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr 1fr", gap: 12, marginBottom: 14 }}>
          <div className="panel panel-pad">
            <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
              <span style={{ fontSize: 22, fontWeight: 700 }}>{loaded}</span>
              <span className="muted">{quote?.name ?? ""}</span>
            </div>
            <div style={{ display: "flex", gap: 18, marginTop: 8, fontSize: 13 }}>
              <span>
                <span className="dim">Price </span>
                <span className="num" style={{ fontWeight: 600 }}>{fmtUSD(quote?.price ?? null)}</span>
              </span>
              <span>
                <span className="dim">Chg </span>
                <span className={`num ${pctClass(quote?.change_pct ?? null)}`}>
                  {fmtPct(quote?.change_pct ?? null)}
                </span>
              </span>
              <span>
                <span className="dim">As of </span>
                <span className="num">{quote?.as_of ?? analysis.as_of}</span>
              </span>
            </div>
            {rec && (
              <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 10 }}>
                <span
                  style={{
                    padding: "3px 10px",
                    borderRadius: 5,
                    fontWeight: 700,
                    fontSize: 13,
                    color: actionColor(rec.action),
                    border: `1px solid ${actionColor(rec.action)}`,
                  }}
                >
                  {rec.action}
                </span>
                <span className="dim" style={{ fontSize: 12 }}>
                  rule-based on QS, momentum, earnings, risk
                </span>
              </div>
            )}
            {rec && rec.reasoning.length > 0 && (
              <ul className="muted" style={{ fontSize: 12, margin: "8px 0 0", paddingLeft: 18 }}>
                {rec.reasoning.map((r, i) => (
                  <li key={i}>{r}</li>
                ))}
              </ul>
            )}
          </div>

          <div className="panel panel-pad">
            <div className="panel-title">Quant Score</div>
            <div className="num" style={{ fontSize: 40, fontWeight: 700, color: scoreColor(analysis.quant_score), lineHeight: 1 }}>
              {fmtScore(analysis.quant_score)}
            </div>
            <div className="dim" style={{ fontSize: 11, marginTop: 6 }}>
              model {analysis.model_version} · as of {analysis.as_of}
            </div>
            <div className="dim" style={{ fontSize: 11, marginTop: 2 }}>
              QS = 0.20·V + 0.20·G + 0.25·Q + 0.20·M + 0.15·R
            </div>
          </div>

          <div className="panel panel-pad">
            <div className="panel-title">Factor scores</div>
            {FACTOR_META.map((f) => (
              <ScoreBar
                key={f.key}
                label={f.label}
                score={analysis.factor_scores[f.key] ?? null}
                weight={f.weight}
              />
            ))}
          </div>
        </div>
      )}

      {analysis && (analysis.missing.length > 0 || breakdown) && (
        <div className="panel" style={{ marginBottom: 14 }}>
          <div className="panel-pad" style={{ paddingBottom: 0 }}>
            <div className="panel-title">Metric transparency — every input, its score, and gaps</div>
          </div>
          {breakdown ? (
            <div style={{ overflowX: "auto", padding: "0 16px 12px" }}>
              <table className="data">
                <thead>
                  <tr>
                    <th>Metric</th>
                    <th>Factor</th>
                    <th style={{ textAlign: "right" }}>Raw value</th>
                    <th style={{ textAlign: "right" }}>Score</th>
                    <th>Band (worst→best)</th>
                    <th style={{ textAlign: "right" }}>Weight</th>
                    <th>Direction</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(breakdown.definitions)
                    .sort((a, b) => a[1].factor.localeCompare(b[1].factor) || b[1].weight - a[1].weight)
                    .map(([name, d]) => {
                      const raw = breakdown.raw_inputs[name];
                      const sc = breakdown.metric_scores[name];
                      return (
                        <tr key={name}>
                          <td>{d.label}</td>
                          <td className="muted">{d.factor}</td>
                          <td className="num" style={{ textAlign: "right" }}>
                            {raw === null || raw === undefined ? "—" : fmtNum(raw, raw > 10 ? 1 : 3)}
                          </td>
                          <td className="num" style={{ textAlign: "right", color: scoreColor(sc) }}>
                            {fmtScore(sc)}
                          </td>
                          <td className="dim num">
                            {d.band[0]} → {d.band[1]}
                          </td>
                          <td className="num dim" style={{ textAlign: "right" }}>
                            {Math.round(d.weight * 100)}%
                          </td>
                          <td className="dim">{d.direction === "lower" ? "lower is better" : "higher is better"}</td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
              {analysis.missing.length > 0 && (
                <div className="info" style={{ marginTop: 10 }}>
                  <b>Missing inputs (never fabricated):</b>{" "}
                  {analysis.missing.map((m) => `${m.metric} (${m.reason})`).join("; ")}
                </div>
              )}
            </div>
          ) : (
            <div className="panel-pad muted" style={{ fontSize: 13 }}>
              Metric breakdown unavailable for this ticker.
            </div>
          )}
        </div>
      )}

      {dcfForm && (
        <div className="panel" style={{ marginBottom: 14 }}>
          <div className="panel-pad">
            <div className="panel-title">DCF valuation — assumptions are yours to set</div>
            {dcfNote && <div className="info" style={{ marginBottom: 10 }}>{dcfNote}</div>}
            {dcfMissing.length > 0 && (
              <div className="info" style={{ marginBottom: 10 }}>
                Not derivable from stored filings (defaulting): {dcfMissing.join(", ")}
              </div>
            )}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 10 }}>
              {field("base_revenue", "Base revenue")}
              {field("revenue_growth", "Revenue growth /yr")}
              {field("ebit_margin", "EBIT margin")}
              {field("tax_rate", "Tax rate")}
              {field("capex_pct_revenue", "CapEx % rev")}
              {field("depreciation_pct_revenue", "D&A % rev")}
              {field("wc_change_pct_revenue", "ΔWC % rev")}
              {field("wacc", "WACC")}
              {field("terminal_growth", "Terminal g")}
              {field("net_debt", "Net debt", 1)}
              {field("shares_diluted", "Shares (dil)", 0.1)}
              {field("current_price", "Current price", 0.5)}
            </div>
            <div style={{ marginTop: 12 }}>
              <button className="btn btn-primary" onClick={runDcfNow} disabled={busy}>
                Run DCF + sensitivity
              </button>
            </div>
          </div>

          {dcf && (
            <div className="panel-pad" style={{ borderTop: "1px solid var(--border)" }}>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, margin: "4px 0 12px" }}>
                <StatTile label="Fair value / share" value={fmtUSD(dcf.fair_value_per_share)} />
                <StatTile
                  label="Upside vs current"
                  value={fmtPct(dcf.upside)}
                  color={(dcf.upside ?? 0) >= 0 ? "var(--green)" : "var(--red)"}
                />
                <StatTile label="Enterprise value" value={fmtUSD(dcf.enterprise_value, 0)} />
                <StatTile label="PV explicit / terminal" value={`${fmtUSD(dcf.pv_explicit, 0)} / ${fmtUSD(dcf.pv_terminal, 0)}`} />
              </div>
              {dcf.warnings.length > 0 && (
                <div className="info" style={{ marginBottom: 10 }}>{dcf.warnings.join(" · ")}</div>
              )}
              <div style={{ overflowX: "auto" }}>
                <table className="data">
                  <thead>
                    <tr>
                      <th>Year</th>
                      <th style={{ textAlign: "right" }}>Revenue</th>
                      <th style={{ textAlign: "right" }}>EBIT</th>
                      <th style={{ textAlign: "right" }}>NOPAT</th>
                      <th style={{ textAlign: "right" }}>+D&A</th>
                      <th style={{ textAlign: "right" }}>−CapEx</th>
                      <th style={{ textAlign: "right" }}>−ΔWC</th>
                      <th style={{ textAlign: "right" }}>FCF</th>
                      <th style={{ textAlign: "right" }}>PV(FCF)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {dcf.projected.map((p) => (
                      <tr key={p.year}>
                        <td>Y{p.year}</td>
                        <td className="num" style={{ textAlign: "right" }}>{fmtNum(p.revenue, 0)}</td>
                        <td className="num" style={{ textAlign: "right" }}>{fmtNum(p.ebit, 0)}</td>
                        <td className="num" style={{ textAlign: "right" }}>{fmtNum(p.nopat, 0)}</td>
                        <td className="num" style={{ textAlign: "right" }}>{fmtNum(p.d_and_a, 0)}</td>
                        <td className="num" style={{ textAlign: "right" }}>{fmtNum(p.capex, 0)}</td>
                        <td className="num" style={{ textAlign: "right" }}>{fmtNum(p.wc_change, 0)}</td>
                        <td className="num" style={{ textAlign: "right", fontWeight: 600 }}>{fmtNum(p.fcf, 0)}</td>
                        <td className="num" style={{ textAlign: "right" }}>{fmtNum(p.pv_fcf, 0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {sens && (
                <>
                  <div className="panel-title" style={{ marginTop: 16 }}>WACC × terminal growth — fair value per share</div>
                  <table className="data">
                    <thead>
                      <tr>
                        <th>WACC \\ g</th>
                        {sens.growth_axis.map((g) => (
                          <th key={g} style={{ textAlign: "right" }}>{(g * 100).toFixed(1)}%</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {sens.wacc_axis.map((w, i) => (
                        <tr key={w}>
                          <td className="num dim">{(w * 100).toFixed(1)}%</td>
                          {sens.table[i].map((cell, j) => (
                            <td key={j} className="num" style={{ textAlign: "right" }}>
                              {cell === null ? <span className="dim">rejected</span> : fmtUSD(cell, 0)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </>
              )}
            </div>
          )}
        </div>
      )}

      {analysis && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
          <div className="panel panel-pad">
            <div className="panel-title">Monte Carlo (10,000 sims, seeded)</div>
            <button className="btn" onClick={runMcNow} disabled={mc !== null || busy}>
              {mc ? "Computed" : "Simulate 1y price distribution"}
            </button>
            {mc && (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8, marginTop: 12 }}>
                <StatTile label="Median" value={fmtUSD(mc.median)} />
                <StatTile label="5th pct" value={fmtUSD(mc.p05)} color="var(--red)" />
                <StatTile label="95th pct" value={fmtUSD(mc.p95)} color="var(--green)" />
                <StatTile label="P(gain)" value={fmtPct(mc.prob_gain, 0)} color="var(--green)" />
                <StatTile label="P(loss)" value={fmtPct(mc.prob_loss, 0)} color="var(--red)" />
                <StatTile label="Std dev" value={fmtUSD(mc.std)} />
              </div>
            )}
            {mc && (
              <div className="dim" style={{ fontSize: 11, marginTop: 8 }}>
                Simulation is a scenario tool, not a forecast. Seed {mc.seed}, {mc.n_simulations} paths,
                {mc.days} trading days.
              </div>
            )}
          </div>

          <div className="panel panel-pad">
            <div className="panel-title">Earnings history (actual vs expected)</div>
            {earnings && earnings.records.length > 0 ? (
              <div style={{ overflowX: "auto" }}>
                <table className="data">
                  <thead>
                    <tr>
                      <th>Fiscal</th>
                      <th style={{ textAlign: "right" }}>EPS act</th>
                      <th style={{ textAlign: "right" }}>EPS est</th>
                      <th style={{ textAlign: "right" }}>Surprise</th>
                      <th style={{ textAlign: "right" }}>Reaction</th>
                    </tr>
                  </thead>
                  <tbody>
                    {earnings.records.slice(0, 8).map((r) => (
                      <tr key={r.fiscal_date}>
                        <td className="num">{r.fiscal_date}</td>
                        <td className="num" style={{ textAlign: "right" }}>{fmtNum(r.eps_actual, 2)}</td>
                        <td className="num" style={{ textAlign: "right" }}>{fmtNum(r.eps_estimated, 2)}</td>
                        <td className={`num ${pctClass(r.eps_surprise_pct)}`} style={{ textAlign: "right" }}>
                          {fmtPct(r.eps_surprise_pct, 1)}
                        </td>
                        <td className={`num ${pctClass(r.market_reaction)}`} style={{ textAlign: "right" }}>
                          {fmtPct(r.market_reaction, 1)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="muted" style={{ fontSize: 13 }}>
                No earnings records stored (requires provider earnings data).
              </div>
            )}
          </div>
        </div>
      )}

      {analysis && (
        <div className="panel panel-pad" style={{ marginBottom: 14 }}>
          <div className="panel-title">
            1-year factor backtest — {loaded} vs SPY (momentum, monthly rebalance, top 1)
          </div>
          <button className="btn" onClick={runBtNow} disabled={btBusy || bt !== null}>
            {btBusy && <span className="spin" />}
            {bt ? "Computed" : "Run backtest"}
          </button>
          {bt && (
            <>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8, margin: "12px 0" }}>
                <StatTile label="Total return" value={fmtPct(Number(bt.stats.total_return ?? 0))} />
                <StatTile label="Benchmark" value={fmtPct(Number(bt.stats.benchmark_return ?? 0))} />
                <StatTile label="Excess" value={fmtPct(Number(bt.stats.excess_return ?? 0))} />
                <StatTile label="Max DD" value={fmtPct(Number(bt.stats.max_drawdown ?? 0))} />
              </div>
              <EquityChart
                height={220}
                series={[
                  {
                    label: "Strategy",
                    color: "var(--accent)",
                    points: bt.equity_curve.dates.map((d, i) => ({ date: d, value: bt.equity_curve.values[i] })),
                  },
                  {
                    label: "SPY",
                    color: "var(--dim)",
                    points: bt.benchmark_curve.dates.map((d, i) => ({ date: d, value: bt.benchmark_curve.values[i] })),
                  },
                ]}
              />
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default function ResearchPage() {
  return (
    <Suspense fallback={<div className="muted">Loading…</div>}>
      <ResearchInner />
    </Suspense>
  );
}
