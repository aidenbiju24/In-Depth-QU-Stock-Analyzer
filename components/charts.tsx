"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ComposedChart,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fmtNum } from "@/lib/format";

interface Series {
  label: string;
  color: string;
  points: { date: string; value: number }[];
}

type ChartRow = Record<string, string | number | null>;

function toChartData(series: Series[]): ChartRow[] {
  const byDate = new Map<string, ChartRow>();
  for (const s of series) {
    for (const p of s.points) {
      const row: ChartRow = byDate.get(p.date) ?? { date: p.date };
      row[s.label] = p.value;
      byDate.set(p.date, row);
    }
  }
  return [...byDate.values()].sort((a, b) => String(a.date).localeCompare(String(b.date)));
}

export function EquityChart({
  series,
  height = 280,
}: {
  series: Series[];
  height?: number;
}) {
  const data = toChartData(series);
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <defs>
          {series.map((s) => (
            <linearGradient key={s.label} id={`g-${s.label}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={s.color} stopOpacity={0.18} />
              <stop offset="100%" stopColor={s.color} stopOpacity={0.02} />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="date"
          tick={{ fill: "var(--dim)", fontSize: 11 }}
          tickLine={false}
          axisLine={{ stroke: "var(--border)" }}
          minTickGap={48}
        />
        <YAxis
          tick={{ fill: "var(--dim)", fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          width={54}
          domain={["auto", "auto"]}
        />
        <Tooltip
          contentStyle={{
            background: "var(--panel-2)",
            border: "1px solid var(--border-strong)",
            borderRadius: 6,
            fontSize: 12,
          }}
          labelStyle={{ color: "var(--muted)" }}
          formatter={(value) => fmtNum(Number(value), 2)}
        />
        {series.map((s) => (
          <Area
            key={s.label}
            type="monotone"
            dataKey={s.label}
            stroke={s.color}
            strokeWidth={1.5}
            fill={`url(#g-${s.label})`}
            dot={false}
            connectNulls
          />
        ))}
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function SimpleLineChart({
  data,
  dataKey,
  height = 220,
  color = "var(--accent)",
  yFormat = (v: number) => fmtNum(v, 0),
}: {
  data: Record<string, unknown>[];
  dataKey: string;
  height?: number;
  color?: string;
  yFormat?: (v: number) => string;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="date"
          tick={{ fill: "var(--dim)", fontSize: 11 }}
          tickLine={false}
          axisLine={{ stroke: "var(--border)" }}
          minTickGap={48}
        />
        <YAxis
          tick={{ fill: "var(--dim)", fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          width={54}
          tickFormatter={(v) => yFormat(Number(v))}
        />
        <Tooltip
          contentStyle={{
            background: "var(--panel-2)",
            border: "1px solid var(--border-strong)",
            borderRadius: 6,
            fontSize: 12,
          }}
          formatter={(value) => fmtNum(Number(value), 2)}
        />
        <Line
          type="monotone"
          dataKey={dataKey}
          stroke={color}
          strokeWidth={1.5}
          dot={false}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

/**
 * Monte Carlo percentile fan: shaded p5-p95 and p25-p75 bands around the
 * median path, plus a dashed reference line at the current price.
 *
 * Recharts has no native band primitive; the standard trick stacks each
 * band's LOWER bound (invisible) with its DELTA (filled), which spans
 * exactly [lower, upper]. The tooltip is custom so band deltas never show.
 */
interface McRow {
  day: number;
  p5: number;
  p25: number;
  p50: number;
  p75: number;
  p95: number;
}

export function MonteCarloFanChart({
  data,
  currentPrice,
  height = 260,
}: {
  data: McRow[];
  currentPrice: number;
  height?: number;
}) {
  const rows = data.map((r) => ({
    day: r.day,
    p5: r.p5,
    dOuter: r.p95 - r.p5, // stacked on p5 -> spans [p5, p95]
    p25: r.p25,
    dInner: r.p75 - r.p25, // stacked on p25 -> spans [p25, p75]
    p50: r.p50,
    ref: currentPrice,
  }));

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="mc-band-outer" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.14} />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity={0.03} />
          </linearGradient>
          <linearGradient id="mc-band-inner" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.32} />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity={0.1} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="day"
          tick={{ fill: "var(--dim)", fontSize: 11 }}
          tickLine={false}
          axisLine={{ stroke: "var(--border)" }}
          minTickGap={48}
          tickFormatter={(d) => `+${d}d`}
        />
        <YAxis
          tick={{ fill: "var(--dim)", fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          width={58}
          domain={["auto", "auto"]}
          tickFormatter={(v) => fmtNum(Number(v), 0)}
        />
        <Tooltip
          cursor={{ stroke: "var(--border-strong)" }}
          content={({ active, payload, label }) => {
            if (!active || !payload?.length) return null;
            const row = payload[0]?.payload as (typeof rows)[number] | undefined;
            if (!row) return null;
            return (
              <div
                style={{
                  background: "var(--panel-2)",
                  border: "1px solid var(--border-strong)",
                  borderRadius: 6,
                  fontSize: 12,
                  padding: "6px 10px",
                }}
              >
                <div style={{ color: "var(--muted)", marginBottom: 2 }}>Day +{label}</div>
                <div>Median: {fmtNum(row.p50, 2)}</div>
                <div style={{ color: "var(--dim)" }}>50% band: {fmtNum(row.p25, 2)} – {fmtNum(row.p25 + row.dInner, 2)}</div>
                <div style={{ color: "var(--dim)" }}>80% band: {fmtNum(row.p5, 2)} – {fmtNum(row.p5 + row.dOuter, 2)}</div>
              </div>
            );
          }}
        />
        {/* Outer 80% band: p5 base (invisible) + delta (filled). */}
        <Area type="monotone" dataKey="p5" stackId="o" stroke="none" fill="transparent" activeDot={false} legendType="none" />
        <Area type="monotone" dataKey="dOuter" stackId="o" stroke="none" fill="url(#mc-band-outer)" activeDot={false} legendType="none" />
        {/* Inner 50% band: p25 base (invisible) + delta (filled). */}
        <Area type="monotone" dataKey="p25" stackId="i" stroke="none" fill="transparent" activeDot={false} legendType="none" />
        <Area type="monotone" dataKey="dInner" stackId="i" stroke="none" fill="url(#mc-band-inner)" activeDot={false} legendType="none" />
        <Line type="monotone" dataKey="p50" stroke="var(--accent)" strokeWidth={2} dot={false} />
        <Line
          type="monotone"
          dataKey="ref"
          stroke="var(--muted)"
          strokeDasharray="5 4"
          strokeWidth={1}
          dot={false}
          activeDot={false}
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
