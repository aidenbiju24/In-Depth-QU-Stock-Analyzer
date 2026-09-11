"use client";

import { useCallback, useEffect, useState } from "react";
import {
  addPosition,
  createPortfolio,
  fetchPortfolioAnalytics,
  fetchPortfolios,
  ingest,
  runOptimize,
  type OptimizationResponse,
  type PortfolioAnalytics,
  type PortfolioSummary,
} from "@/lib/api";
import { StatTile } from "@/components/StatTile";
import { EquityChart } from "@/components/charts";
import { fmtNum, fmtPct, fmtScore, fmtUSD } from "@/lib/format";

const OBJECTIVES = [
  { value: "max_sharpe", label: "Max Sharpe" },
  { value: "min_volatility", label: "Min Volatility" },
  { value: "target_return", label: "Target Return" },
];

export default function PortfolioPage() {
  const [portfolios, setPortfolios] = useState<PortfolioSummary[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [analytics, setAnalytics] = useState<PortfolioAnalytics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [newName, setNewName] = useState("");
  const [posTicker, setPosTicker] = useState("");
  const [posQty, setPosQty] = useState("");
  const [posCost, setPosCost] = useState("");

  const [optTickers, setOptTickers] = useState("AAPL,MSFT,NVDA");
  const [objective, setObjective] = useState("max_sharpe");
  const [maxPos, setMaxPos] = useState("0.4");
  const [optResult, setOptResult] = useState<OptimizationResponse | null>(null);

  const refresh = useCallback(
    (id?: string | null) => {
      fetchPortfolios()
        .then((list) => {
          setPortfolios(list);
          const active = id ?? selected ?? (list.length > 0 ? list[0].id : null);
          setSelected(active);
          if (active) {
            fetchPortfolioAnalytics(active)
              .then((a) => setAnalytics(a))
              .catch((e) => setError(e instanceof Error ? e.message : String(e)));
          } else {
            setAnalytics(null);
          }
        })
        .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    },
    [selected]
  );

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const create = async () => {
    if (!newName.trim()) return;
    setError(null);
    try {
      const r = await createPortfolio(newName.trim(), "SPY");
      setNewName("");
      await refresh(r.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const addPos = async () => {
    if (!selected || !posTicker.trim() || !posQty) return;
    setBusy(true);
    setError(null);
    try {
      await ingest(posTicker.trim().toUpperCase());
      await addPosition(
        selected,
        posTicker.trim().toUpperCase(),
        parseFloat(posQty),
        posCost ? parseFloat(posCost) : null
      );
      setPosTicker("");
      setPosQty("");
      setPosCost("");
      await refresh(selected);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const optimize = async () => {
    setBusy(true);
    setError(null);
    setOptResult(null);
    try {
      const tickers = optTickers.split(",").map((t) => t.trim().toUpperCase()).filter(Boolean);
      for (const t of tickers) {
        await ingest(t);
      }
      setOptResult(await runOptimize(tickers, objective, parseFloat(maxPos)));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const corr = analytics?.correlation;

  return (
    <div>
      <h1 style={{ fontSize: 18, fontWeight: 700, marginBottom: 4 }}>Portfolio</h1>
      <p className="muted" style={{ marginBottom: 16 }}>
        Holdings, risk analytics, correlation structure, and optimization — computed
        from stored price history.
      </p>

      {error && <div className="err" style={{ marginBottom: 14 }}>{error}</div>}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 2fr", gap: 12, marginBottom: 14 }}>
        <div className="panel panel-pad">
          <div className="panel-title">Create portfolio</div>
          <div style={{ display: "flex", gap: 8 }}>
            <input
              className="input"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="e.g. Wharton Q1 Book"
            />
            <button className="btn btn-primary" onClick={create} disabled={!newName.trim()}>
              Create
            </button>
          </div>

          {portfolios.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div className="label">Saved portfolios</div>
              {portfolios.map((p) => (
                <button
                  key={p.id}
                  className="btn"
                  style={{
                    width: "100%",
                    justifyContent: "space-between",
                    marginBottom: 6,
                    borderColor: selected === p.id ? "var(--accent)" : undefined,
                  }}
                  onClick={() => refresh(p.id)}
                >
                  <span>{p.name}</span>
                  <span className="dim" style={{ fontSize: 11 }}>{p.positions.length} positions</span>
                </button>
              ))}
            </div>
          )}

          {selected && (
            <div style={{ marginTop: 14, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
              <div className="panel-title">Add position</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 8 }}>
                <input
                  className="input"
                  style={{ textTransform: "uppercase" }}
                  value={posTicker}
                  onChange={(e) => setPosTicker(e.target.value)}
                  placeholder="Ticker"
                />
                <input
                  className="input num"
                  value={posQty}
                  onChange={(e) => setPosQty(e.target.value)}
                  placeholder="Quantity"
                  type="number"
                  step="any"
                />
                <input
                  className="input num"
                  value={posCost}
                  onChange={(e) => setPosCost(e.target.value)}
                  placeholder="Avg cost (optional)"
                  type="number"
                  step="any"
                />
                <button className="btn btn-primary" onClick={addPos} disabled={busy || !posTicker.trim() || !posQty}>
                  Add
                </button>
              </div>
            </div>
          )}
        </div>

        <div>
          {analytics ? (
            <>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 12 }}>
                <StatTile label="Total value" value={fmtUSD(analytics.total_value)} />
                <StatTile
                  label="Sharpe"
                  value={fmtNum(analytics.stats.sharpe ?? null)}
                  sub="rf = 4% annualized"
                />
                <StatTile
                  label="Volatility (ann.)"
                  value={fmtPct(analytics.stats.volatility ?? null)}
                />
                <StatTile
                  label="Max drawdown"
                  value={fmtPct(-(analytics.stats.max_drawdown ?? 0))}
                  color="var(--red)"
                />
              </div>

              <div style={{ display: "grid", gridTemplateColumns: "1.3fr 1fr", gap: 12 }}>
                <div className="panel panel-pad">
                  <div className="panel-title">Growth of $1 vs allocation</div>
                  <EquityChart
                    height={240}
                    series={[
                      {
                        label: "Portfolio",
                        color: "var(--accent)",
                        points: analytics.equity_curve.dates.map((d, i) => ({
                          date: d,
                          value: analytics.equity_curve.values[i],
                        })),
                      },
                    ]}
                  />
                </div>
                <div className="panel panel-pad">
                  <div className="panel-title">Holdings</div>
                  <table className="data">
                    <thead>
                      <tr>
                        <th>Ticker</th>
                        <th style={{ textAlign: "right" }}>Weight</th>
                        <th style={{ textAlign: "right" }}>Value</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(analytics.weights).map(([t, w]) => (
                        <tr key={t}>
                          <td style={{ fontWeight: 600 }}>{t}</td>
                          <td className="num" style={{ textAlign: "right" }}>{fmtPct(w, 1)}</td>
                          <td className="num" style={{ textAlign: "right" }}>
                            {fmtUSD(analytics.positions_value[t] ?? null, 0)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <div className="dim" style={{ fontSize: 11, marginTop: 8 }}>
                    Beta {fmtNum(analytics.stats.beta ?? null)} · Alpha {fmtPct(analytics.stats.alpha ?? null)} ·
                    VaR95 {fmtPct(analytics.stats.var_95_daily ?? null)} /day
                  </div>
                </div>
              </div>

              {corr && (
                <div className="panel panel-pad" style={{ marginTop: 12 }}>
                  <div className="panel-title">Correlation matrix (daily returns)</div>
                  <div style={{ overflowX: "auto" }}>
                    <table className="data">
                      <thead>
                        <tr>
                          <th></th>
                          {Object.keys(corr.matrix).map((t) => (
                            <th key={t} style={{ textAlign: "right" }}>{t}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(corr.matrix).map(([a, row]) => (
                          <tr key={a}>
                            <td style={{ fontWeight: 600 }}>{a}</td>
                            {Object.entries(row).map(([b, v]) => (
                              <td
                                key={b}
                                className="num"
                                style={{
                                  textAlign: "right",
                                  background:
                                    a === b
                                      ? "var(--panel-2)"
                                      : `rgba(248,113,113,${Math.max(0, (v - 0.5) * 0.5)})`,
                                }}
                              >
                                {fmtNum(v, 2)}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {corr.highly_correlated.length > 0 && (
                    <div className="info" style={{ marginTop: 8 }}>
                      Highly correlated (ρ &gt; 0.85):{" "}
                      {corr.highly_correlated.map((p) => `${p.a}/${p.b} (${fmtNum(p.correlation, 2)})`).join(", ")}
                      {" "}— consider diversifying redundant exposure.
                    </div>
                  )}
                </div>
              )}
            </>
          ) : (
            <div className="panel panel-pad muted">
              Create a portfolio and add positions to see analytics.
            </div>
          )}
        </div>
      </div>

      <div className="panel panel-pad">
        <div className="panel-title">Portfolio optimizer — long-only, full allocation, position caps</div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <div style={{ flex: 2, minWidth: 220 }}>
            <label className="label">Universe</label>
            <input className="input" value={optTickers} onChange={(e) => setOptTickers(e.target.value)} />
          </div>
          <div style={{ flex: 1, minWidth: 140 }}>
            <label className="label">Objective</label>
            <select className="input" value={objective} onChange={(e) => setObjective(e.target.value)}>
              {OBJECTIVES.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>
          <div style={{ width: 120 }}>
            <label className="label">Max position</label>
            <input className="input num" value={maxPos} onChange={(e) => setMaxPos(e.target.value)} type="number" step="0.05" min="0.05" max="1" />
          </div>
          <button className="btn btn-primary" onClick={optimize} disabled={busy}>
            {busy && <span className="spin" />}
            Optimize
          </button>
        </div>

        {optResult && (
          <div style={{ marginTop: 14, display: "grid", gridTemplateColumns: "1fr auto", gap: 16 }}>
            <table className="data">
              <thead>
                <tr>
                  <th>Ticker</th>
                  <th style={{ textAlign: "right" }}>Weight</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(optResult.weights)
                  .sort((a, b) => b[1] - a[1])
                  .map(([t, w]) => (
                    <tr key={t}>
                      <td style={{ fontWeight: 600 }}>{t}</td>
                      <td className="num" style={{ textAlign: "right" }}>{fmtPct(w, 1)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
            <div style={{ minWidth: 220 }}>
              <StatTile label="Exp. return (ann.)" value={fmtPct(optResult.expected_return)} />
              <div style={{ height: 8 }} />
              <StatTile label="Exp. volatility" value={fmtPct(optResult.expected_volatility)} />
              <div style={{ height: 8 }} />
              <StatTile label="Exp. Sharpe" value={fmtScore(optResult.expected_sharpe)} />
            </div>
          </div>
        )}
        {optResult && (
          <div className="dim" style={{ fontSize: 11, marginTop: 8 }}>
            Optimizer {optResult.version} · expected inputs from 252-day lookback ·
            constraints validated post-solve.
          </div>
        )}
      </div>
    </div>
  );
}
