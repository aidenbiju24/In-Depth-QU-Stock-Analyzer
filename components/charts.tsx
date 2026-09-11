"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
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
