"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchModelRuns, type ModelRun } from "@/lib/api";

export default function AuditPage() {
  const [runs, setRuns] = useState<ModelRun[]>([]);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    fetchModelRuns()
      .then((r) => setRuns(r))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div>
      <h1 style={{ fontSize: 18, fontWeight: 700, marginBottom: 4 }}>Model Runs</h1>
      <p className="muted" style={{ marginBottom: 16 }}>
        Every model execution is recorded — inputs, parameters, outputs, versions,
        and data timestamps — so any conclusion can be audited later.
      </p>

      {error && <div className="err" style={{ marginBottom: 14 }}>{error}</div>}

      <div className="panel" style={{ overflowX: "auto" }}>
        <table className="data">
          <thead>
            <tr>
              <th>#</th>
              <th>Executed</th>
              <th>Model</th>
              <th>Version</th>
              <th>Subject</th>
              <th>Data as of</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <>
                <tr key={r.id}>
                  <td className="dim">{r.id}</td>
                  <td className="num">{r.executed_at.replace("T", " ").replace("Z", "")}</td>
                  <td style={{ fontWeight: 600 }}>{r.model}</td>
                  <td className="dim">{r.model_version}</td>
                  <td>{r.subject}</td>
                  <td className="num dim">{r.input_as_of ?? "—"}</td>
                  <td>
                    <button
                      className="btn"
                      style={{ padding: "2px 8px", fontSize: 11 }}
                      onClick={() => setExpanded(expanded === r.id ? null : r.id)}
                    >
                      {expanded === r.id ? "Hide" : "Inspect"}
                    </button>
                  </td>
                </tr>
                {expanded === r.id && (
                  <tr key={`${r.id}-detail`}>
                    <td colSpan={7} style={{ background: "var(--bg)" }}>
                      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, padding: 6 }}>
                        <div>
                          <div className="panel-title">Parameters</div>
                          <pre
                            className="num"
                            style={{
                              fontSize: 11,
                              whiteSpace: "pre-wrap",
                              color: "var(--muted)",
                              margin: 0,
                            }}
                          >
                            {JSON.stringify(r.parameters, null, 2) ?? "—"}
                          </pre>
                        </div>
                        <div>
                          <div className="panel-title">Output</div>
                          <pre
                            className="num"
                            style={{
                              fontSize: 11,
                              whiteSpace: "pre-wrap",
                              color: "var(--muted)",
                              margin: 0,
                            }}
                          >
                            {JSON.stringify(r.output, null, 2) ?? "—"}
                          </pre>
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </>
            ))}
            {runs.length === 0 && (
              <tr>
                <td colSpan={7} className="muted" style={{ textAlign: "center", padding: 24 }}>
                  No model runs recorded yet. Running analyses, DCFs, backtests,
                  and optimizations populates the audit trail.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
