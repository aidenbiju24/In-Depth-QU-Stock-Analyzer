export const fmtNum = (v: number | null | undefined, digits = 2): string => {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
};

export const fmtPct = (v: number | null | undefined, digits = 1): string => {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  const s = (v * 100).toFixed(digits);
  return `${v > 0 ? "+" : ""}${s}%`;
};

export const fmtUSD = (v: number | null | undefined, digits = 2): string => {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return `$${fmtNum(v, digits)}`;
};

export const fmtScore = (v: number | null | undefined): string => {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  return v.toFixed(0);
};

export const scoreColor = (v: number | null | undefined): string => {
  if (v === null || v === undefined || !Number.isFinite(v)) return "var(--dim)";
  if (v >= 70) return "var(--green)";
  if (v >= 45) return "var(--amber)";
  return "var(--red)";
};

export const actionColor = (action: string): string => {
  if (action.startsWith("Strong Buy")) return "var(--green)";
  if (action === "Buy") return "#7dd8b5";
  if (action === "Hold") return "var(--amber)";
  if (action === "Sell") return "#f2a097";
  return "var(--red)";
};

export const pctClass = (v: number | null | undefined): string => {
  if (v === null || v === undefined || !Number.isFinite(v) || v === 0) return "";
  return v > 0 ? "pos" : "neg";
};

export const fmtDate = (iso: string | null | undefined): string => {
  if (!iso) return "—";
  return iso;
};

export const fmtCompact = (v: number | null | undefined): string => {
  if (v === null || v === undefined || !Number.isFinite(v)) return "—";
  const abs = Math.abs(v);
  if (abs >= 1e12) return `${(v / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return v.toFixed(0);
};
