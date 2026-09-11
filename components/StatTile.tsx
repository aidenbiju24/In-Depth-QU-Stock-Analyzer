export function StatTile({
  label,
  value,
  sub,
  color,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  color?: string;
}) {
  return (
    <div className="panel panel-pad">
      <div className="panel-title" style={{ marginBottom: 4 }}>
        {label}
      </div>
      <div className="num" style={{ fontSize: 20, fontWeight: 600, color: color ?? "var(--text)" }}>
        {value}
      </div>
      {sub !== undefined && <div className="muted" style={{ fontSize: 12, marginTop: 2 }}>{sub}</div>}
    </div>
  );
}

export function ScoreBar({
  label,
  score,
  weight,
}: {
  label: string;
  score: number | null;
  weight?: number;
}) {
  const clamped = score === null || !Number.isFinite(score) ? 0 : Math.max(0, Math.min(100, score));
  const color =
    clamped >= 70 ? "var(--green)" : clamped >= 45 ? "var(--amber)" : "var(--red)";
  return (
    <div style={{ marginBottom: 10 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: 12,
          marginBottom: 3,
        }}
      >
        <span>
          {label}
          {weight !== undefined && <span className="dim"> · {Math.round(weight * 100)}%</span>}
        </span>
        <span className="num" style={{ color, fontWeight: 600 }}>
          {score === null || !Number.isFinite(score) ? "—" : clamped.toFixed(0)}
        </span>
      </div>
      <div style={{ background: "var(--panel-2)", borderRadius: 3, height: 6 }}>
        <div
          style={{
            width: `${clamped}%`,
            height: "100%",
            borderRadius: 3,
            background: color,
            transition: "width 0.3s ease",
          }}
        />
      </div>
    </div>
  );
}
