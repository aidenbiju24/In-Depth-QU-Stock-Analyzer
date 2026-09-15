"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import {
  fetchModelRuns,
  fetchModelRun,
  type ModelRun,
  type ModelRunDetail,
} from "@/lib/api";

function fmtRunAt(iso: string): string {
  // Backend timestamps look like "2026-09-14T02:03:21Z" (or without Z).
  if (!iso) return "—";
  return iso.replace("T", " ").replace("Z", "");
}

export default function AuditPage() {
  const [runs, setRuns] = useState<ModelRun[]>([]);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [detail, setDetail] = useState<ModelRunDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    fetchModelRuns()
      .then((r) => setRuns(r))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // The list endpoint returns summary rows only; parameters/output live on
  // the detail endpoint, fetched when a row is expanded.
  const toggle = useCallback(
    (id: number) => {
      if (expanded === id) {
        setExpanded(null);
        setDetail(null);
        return;
      }
      setExpanded(id);
      setDetail(null);
      setDetailLoading(true);
      fetchModelRun(id)
        .then(setDetail)
        .catch((e) => setError(e instanceof Error ? e.message : String(e)))
        .finally(() => setDetailLoading(false));
    },
    [expanded]
  );

  return (
    <div>
      <header className="page-head">
        <div>
          <div className="page-kicker">Audit Trail</div>
          <h1 className="page-title">Model Runs</h1>
          <p className="page-sub">
            Every model execution is recorded — inputs, parameters, outputs, versions,
            and data timestamps — so any conclusion can be audited later.
          </p>
        </div>
      </header>

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
              <Fragment key={r.id}>
                <tr>
                  <td className="dim">{r.id}</td>
                  <td className="num">{fmtRunAt(r.run_at)}</td>
                  <td style={{ fontWeight: 600 }}>{r.model}</td>
                  <td className="dim">{r.version}</td>
                  <td>{r.subject}</td>
                  <td className="num dim">{r.input_as_of ?? "—"}</td>
                  <td>
                    <button
                      className="btn"
                      style={{ padding: "2px 8px", fontSize: 11 }}
                      onClick={() => toggle(r.id)}
                    >
                      {expanded === r.id ? "Hide" : "Inspect"}
                    </button>
                  </td>
                </tr>
                {expanded === r.id && (
                  <tr>
                    <td colSpan={7} style={{ background: "var(--bg)" }}>
                      {detailLoading && (
                        <div className="muted" style={{ padding: 6 }}>
                          Loading detail…
                        </div>
                      )}
                      {detail && detail.id === r.id && (
                        <div
                          style={{
                            display: "grid",
                            gridTemplateColumns: "1fr 1fr",
                            gap: 12,
                            padding: 6,
                          }}
                        >
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
                              {detail.parameters
                                ? JSON.stringify(detail.parameters, null, 2)
                                : "—"}
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
                              {detail.output
                                ? JSON.stringify(detail.output, null, 2)
                                : "—"}
                            </pre>
                          </div>
                        </div>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
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
