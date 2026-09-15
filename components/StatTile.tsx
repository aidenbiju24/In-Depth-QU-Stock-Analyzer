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
    <div className="panel panel-pad" style={{ position: "relative", overflow: "hidden" }}>
      <div
        aria-hidden
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          right: 0,
          height: 2,
          background: color
            ? `linear-gradient(90deg, ${color}, transparent)`
            : "linear-gradient(90deg, var(--accent), transparent)",
          opacity: 0.7,
        }}
      />
      <div className="panel-title" style={{ marginBottom: 6 }}>
        {label}
      </div>
      <div
        className="num"
        style={{
          fontSize: 22,
          fontWeight: 700,
          color: color ?? "var(--text)",
          lineHeight: 1.1,
        }}
      >
        {value}
      </div>
      {sub !== undefined && (
        <div className="muted" style={{ fontSize: 11.5, marginTop: 4 }}>
          {sub}
        </div>
      )}
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
    <div style={{ marginBottom: 12 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          fontSize: 12,
          marginBottom: 4,
        }}
      >
        <span style={{ fontWeight: 500 }}>
          {label}
          {weight !== undefined && <span className="dim"> · {Math.round(weight * 100)}%</span>}
        </span>
        <span className="num" style={{ color, fontWeight: 700 }}>
          {score === null || !Number.isFinite(score) ? "—" : clamped.toFixed(0)}
        </span>
      </div>
      <div
        style={{
          background: "var(--panel-2)",
          border: "1px solid var(--border)",
          borderRadius: 99,
          height: 8,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            width: `${clamped}%`,
            height: "100%",
            borderRadius: 99,
            background: `linear-gradient(90deg, ${color}88, ${color})`,
            boxShadow: `0 0 8px ${color}55`,
            transition: "width 0.4s ease",
          }}
        />
      </div>
    </div>
  );
}
