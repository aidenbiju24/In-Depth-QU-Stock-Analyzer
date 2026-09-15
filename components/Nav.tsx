"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { fetchHealth, type Health } from "@/lib/api";

const LINKS = [
  { href: "/", label: "Dashboard", num: "01" },
  { href: "/research", label: "Stock Research", num: "02" },
  { href: "/portfolio", label: "Portfolio", num: "03" },
  { href: "/backtest", label: "Backtesting", num: "04" },
  { href: "/journal", label: "Journal", num: "05" },
  { href: "/audit", label: "Model Runs", num: "06" },
];

export function Nav() {
  const pathname = usePathname();
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = () => {
      fetchHealth()
        .then((h) => alive && setHealth(h))
        .catch(() => alive && setHealth(null));
    };
    tick();
    const id = setInterval(tick, 30_000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  const up = health !== null;
  const missingKeys = health
    ? Object.entries(health.credentials_missing)
        .filter(([, missing]) => missing)
        .map(([key]) => key)
    : [];

  return (
    <aside
      style={{
        width: 216,
        minWidth: 216,
        borderRight: "1px solid var(--border)",
        background: "linear-gradient(180deg, var(--panel), rgba(13, 19, 32, 0.6))",
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        position: "sticky",
        top: 0,
      }}
    >
      {/* brand */}
      <div
        style={{
          padding: "20px 18px 16px",
          borderBottom: "1px solid var(--border)",
          display: "flex",
          alignItems: "center",
          gap: 11,
        }}
      >
        <div
          style={{
            width: 32,
            height: 32,
            borderRadius: 9,
            flex: "none",
            background:
              "linear-gradient(135deg, var(--accent-strong), var(--accent) 55%, #3a63d6)",
            boxShadow: "0 4px 14px rgba(91, 140, 255, 0.35)",
            display: "grid",
            placeItems: "center",
          }}
        >
          {/* simple candlestick mark */}
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <line x1="4" y1="2" x2="4" y2="14" stroke="#04101f" strokeWidth="1.6" strokeLinecap="round" />
            <rect x="2.2" y="5" width="3.6" height="5" rx="1" fill="#04101f" />
            <line x1="11.5" y1="2" x2="11.5" y2="14" stroke="#04101f" strokeWidth="1.6" strokeLinecap="round" />
            <rect x="9.7" y="7" width="3.6" height="4.5" rx="1" fill="#04101f" />
          </svg>
        </div>
        <div>
          <div style={{ fontWeight: 700, fontSize: 13.5, letterSpacing: "-0.01em" }}>
            Quant Analyzer
          </div>
          <div className="dim" style={{ fontSize: 10.5, marginTop: 1 }}>
            Wharton Research Platform
          </div>
        </div>
      </div>

      {/* links */}
      <nav style={{ display: "flex", flexDirection: "column", gap: 3, padding: "14px 10px" }}>
        {LINKS.map((l) => {
          const active =
            l.href === "/" ? pathname === "/" : pathname.startsWith(l.href);
          return (
            <Link
              key={l.href}
              href={l.href}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 9,
                padding: "8px 11px",
                borderRadius: 8,
                fontSize: 13,
                fontWeight: active ? 650 : 450,
                color: active ? "var(--text)" : "var(--muted)",
                background: active
                  ? "linear-gradient(90deg, var(--accent-soft), rgba(91, 140, 255, 0.03))"
                  : "transparent",
                textDecoration: "none",
                boxShadow: active ? "inset 2px 0 0 var(--accent)" : "none",
                transition: "background 0.15s ease, color 0.15s ease",
              }}
            >
              <span
                className="num"
                style={{
                  fontSize: 10,
                  color: active ? "var(--accent)" : "var(--dim)",
                  fontWeight: 600,
                  width: 16,
                }}
              >
                {l.num}
              </span>
              {l.label}
            </Link>
          );
        })}
      </nav>

      {/* status dock */}
      <div
        style={{
          marginTop: "auto",
          padding: 14,
          borderTop: "1px solid var(--border)",
        }}
      >
        <div
          style={{
            background: "var(--panel-2)",
            border: "1px solid var(--border)",
            borderRadius: 10,
            padding: "10px 12px",
            display: "flex",
            flexDirection: "column",
            gap: 7,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: 4,
                background: up ? "var(--green)" : "var(--red)",
                boxShadow: up ? "0 0 8px rgba(61, 220, 151, 0.7)" : "none",
                display: "inline-block",
                flex: "none",
              }}
            />
            <span className="muted" style={{ fontWeight: 600 }}>
              {up ? "Backend online" : "Backend offline"}
            </span>
          </div>
          {health && (
            <div className="dim" style={{ fontSize: 10.5, lineHeight: 1.5 }}>
              {missingKeys.length === 0
                ? "All provider keys configured"
                : `Missing: ${missingKeys.join(", ")}`}
              <br />
              <span className="num">
                {(health.row_counts.prices ?? 0).toLocaleString()} prices ·{" "}
                {health.row_counts.companies ?? 0} companies
              </span>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
