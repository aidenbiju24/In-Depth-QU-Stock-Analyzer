import type { Metadata } from "next";
import { Nav } from "@/components/Nav";
import "./globals.css";

export const metadata: Metadata = {
  title: "In-Depth Quant Stock Analyzer",
  description:
    "Quantitative investment research platform — factors, valuation, risk, backtesting.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>
        <div style={{ display: "flex", minHeight: "100vh" }}>
          <Nav />
          <main style={{ flex: 1, minWidth: 0, padding: "20px 24px", maxWidth: 1400 }}>
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
