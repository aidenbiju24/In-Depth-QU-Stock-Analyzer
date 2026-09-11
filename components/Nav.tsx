"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { fetchHealth, type Health } from "@/lib/api";

const LINKS = [
  { href: "/", label: "Dashboard" },
  { href: "/research", label: "Stock Research" },
  { href: "/portfolio", label: "Portfolio" },
  { href: "/backtest", label: "Backtesting" },
  { href: "/journal", label: "Journal" },
  { href: "/audit", label: "Model Runs" },
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

  return (
    <aside
      style={{
        width: 200,
        minWidth: 200,
        borderRight: "1px solid var(--border)",
        background: "var(--panel)",
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        position: "sticky",
        top: 0,
      }}
    >
      <div style={{ padding: "16px 16px 12px" }}>
        <div style={{ fontWeight: 700, fontSize: 14, letterSpacing: "0.02em" }}>
          Quant Analyzer
        </div>
        <div className="dim" style={{ fontSize: 11, marginTop: 2 }}>
          Wharton Research Platform
        </div>
      </div>

      <nav style={{ display: "flex", flexDirection: "column", gap: 2, padding: "0 8px" }}>
        {LINKS.map((l) => {
          const active =
            l.href === "/" ? pathname === "/" : pathname.startsWith(l.href);
          return (
            <Link
              key={l.href}
              href={l.href}
              style={{
                display: "block",
                padding: "8px 10px",
                borderRadius: 6,
                fontSize: 13,
                fontWeight: active ? 600 : 400,
                color: active ? "var(--text)" : "var(--muted)",
                background: active ? "var(--panel-2)" : "transparent",
                textDecoration: "none",
                border: active ? "1px solid var(--border-strong)" : "1px solid transparent",
              }}
            >
              {l.label}
            </Link>
          );
        })}
      </nav>

      <div style={{ marginTop: "auto", padding: 14, borderTop: "1px solid var(--border)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 12 }}>
          <span
            style={{
              width: 8,
              height: 8,
              borderRadius: 4,
              background: up ? "var(--green)" : "var(--red)",
              display: "inline-block",
            }}
          />
          <span className="muted">{up ? "Backend online" : "Backend offline"}</span>
        </div>
        {health && (
          <div className="dim" style={{ fontSize: 11, marginTop: 6 }}>
            {health.credentials_missing.length === 0
              ? "All provider keys configured"
              : `Missing: ${health.credentials_missing.join(", ")}`}
          </div>
        )}
        {health && (
          <div className="dim" style={{ fontSize: 11, marginTop: 2 }}>
            {health.row_counts.prices ?? 0} price rows · {health.row_counts.companies ?? 0} companies
          </div>
        )}
      </div>
    </aside>
  );
}
