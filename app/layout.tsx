import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { Nav } from "@/components/Nav";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains",
  display: "swap",
});

export const metadata: Metadata = {
  title: "In-Depth Quant Stock Analyzer",
  description:
    "Quantitative investment research platform — factors, valuation, risk, backtesting.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${inter.variable} ${mono.variable}`}>
      <body>
        <div style={{ display: "flex", minHeight: "100vh" }}>
          <Nav />
          <main
            style={{
              flex: 1,
              minWidth: 0,
              padding: "28px 32px 48px",
              maxWidth: 1460,
            }}
          >
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
