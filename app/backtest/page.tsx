"use client";

import { useState } from "react";
import { runBacktest, type BacktestResponse } from "@/lib/api";
import { StatTile } from "@/components/StatTile";
import { EquityChart } from "@/components/charts";
import { fmtNum, fmtPct } from "@/lib/format";

const FACTORS = ["momentum", "value", "growth", "quality", "risk"];
const FREQS = ["daily", "weekly", "monthly", "quarterly"];

export default function BacktestPage() {
  const [universe, setUniverse] = useState("AAPL,MSFT,NVDA,GOOGL,AMZN");
  const [factor, setFactor] = useState("momentum");
  const [topN, setTopN] = useState("2");
  const [freq, setFreq] = useState("monthly");
  const [benchmark, setBenchmark] = useState("SPY");
  const [start, setStart] = useState(() => {
    const d = new Date(Date.now() - 3 * 365 * 24 * 3600 * 1000);
    return d.toISOString().slice(0, 10);
  });
  const [end, setEnd] = useState(() => new Date().toISOString().slice(0, 10));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BacktestResponse | null>(null);

  const run = async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(
        await runBacktest({
          universe: universe.split(",").map((t) => t.trim().toUpperCase()).filter(Boolean),
          start,
          end,
          benchmark,
          rebalance_frequency: freq,
          top_n: parseInt(topN, 10) || 1,
          factor,
        })
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <header className="page-head">
        <div>
          <div className="page-kicker">Strategy Validation</div>
          <h1 className="page-title">Backtesting</h1>
          <p className="page-sub">
            Factor backtests with point-in-time scoring: at each rebalance date the
            factor model is recomputed using only data that was public on that date
            (filing-date aware). Execution happens at the next bar — no look-ahead.
          </p>
        </div>
      </header>

      <div className="panel panel-pad" style={{ marginBottom: 14 }}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))", gap: 10, alignItems: "flex-end" }}>
          <div>
            <label className="label">Universe</label>
            <input className="input" value={universe} onChange={(e) => setUniverse(e.target.value)} />
          </div>
          <div>
            <label className="label">Factor</label>
            <select className="input" value={factor} onChange={(e) => setFactor(e.target.value)}>
              {FACTORS.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Top N</label>
            <input className="input num" type="number" min="1" max="10" value={topN} onChange={(e) => setTopN(e.target.value)} />
          </div>
          <div>
            <label className="label">Rebalance</label>
            <select className="input" value={freq} onChange={(e) => setFreq(e.target.value)}>
              {FREQS.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Benchmark</label>
            <input className="input" value={benchmark} onChange={(e) => setBenchmark(e.target.value.toUpperCase())} />
          </div>
          <div>
            <label className="label">Window</label>
            <div style={{ display: "flex", gap: 6 }}>
              <input className="input num" type="date" value={start} onChange={(e) => setStart(e.target.value)} />
              <input className="input num" type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
            </div>
          </div>
          <button className="btn btn-primary" onClick={run} disabled={busy}>
            {busy && <span className="spin" />}
            {busy ? "Running…" : "Run"}
          </button>
        </div>
        <div className="dim" style={{ fontSize: 11, marginTop: 8 }}>
          The engine scores every name at every rebalance date — factor backtests
          are compute-bound. Keep windows reasonable.
        </div>
      </div>

      {error && <div className="err" style={{ marginBottom: 14 }}>{error}</div>}

      {result && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 12, marginBottom: 12 }}>
            <StatTile label="Total return" value={fmtPct(Number(result.stats.total_return ?? 0))} />
            <StatTile label="Ann. return" value={fmtPct(Number(result.stats.annualized_return ?? 0))} />
            <StatTile label="Volatility" value={fmtPct(Number(result.stats.volatility ?? 0))} />
            <StatTile label="Sharpe" value={fmtNum(result.stats.sharpe ?? null)} />
            <StatTile label="Max drawdown" value={fmtPct(-Number(result.stats.max_drawdown ?? 0))} color="var(--red)" />
          </div>

          <div className="panel panel-pad" style={{ marginBottom: 12 }}>
            <div className="panel-title">Strategy vs {result.config.benchmark as string}</div>
            <EquityChart
              height={300}
              series={[
                {
                  label: "Strategy",
                  color: "var(--accent)",
                  points: result.equity_curve.dates.map((d, i) => ({ date: d, value: result.equity_curve.values[i] })),
                },
                {
                  label: result.config.benchmark as string,
                  color: "var(--dim)",
                  points: result.benchmark_curve.dates.map((d, i) => ({ date: d, value: result.benchmark_curve.values[i] })),
                },
              ]}
            />
          </div>

          <div className="split-even">
            <div className="panel panel-pad">
              <div className="panel-title">Performance detail</div>
              <table className="data">
                <tbody>
                  {[
                    ["Benchmark return", fmtPct(Number(result.stats.benchmark_return ?? 0))],
                    ["Excess return", fmtPct(Number(result.stats.excess_return ?? 0))],
                    ["Sortino", fmtNum(result.stats.sortino ?? null)],
                    ["Win rate (days)", fmtPct(Number(result.stats.win_rate ?? 0), 0)],
                    ["Trades", String(result.stats.num_trades ?? "—")],
                    ["Final value", fmtNum(Number(result.stats.final_value ?? 0), 2)],
                    ["Initial capital", fmtNum(Number(result.stats.initial_capital ?? 0), 0)],
                  ].map(([k, v]) => (
                    <tr key={k}>
                      <td className="muted">{k}</td>
                      <td className="num" style={{ textAlign: "right" }}>{v}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="panel panel-pad">
              <div className="panel-title">Trade log (first 50)</div>
              <div style={{ maxHeight: 320, overflowY: "auto" }}>
                <table className="data">
                  <thead>
                    <tr>
                      <th>Signal</th>
                      <th>Executed</th>
                      <th>Holdings</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.trade_log.map((t, i) => {
                      const rec = t as { signal_date?: string; execution_date?: string; executed?: unknown };
                      return (
                        <tr key={i}>
                          <td className="num">{rec.signal_date}</td>
                          <td className="num">{rec.execution_date}</td>
                          <td className="num">
                            {Object.keys((rec.executed ?? {}) as Record<string, number>).join(", ") || "cash"}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          {result.skipped_executions.length > 0 && (
            <div className="info" style={{ marginTop: 12 }}>
              {result.skipped_executions.length} execution(s) skipped for missing
              prices on execution dates — the engine held cash rather than
              fabricating fills.
            </div>
          )}
        </>
      )}
    </div>
  );
}
