import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The frontend never talks to external data providers; it proxies the local
  // FastAPI service only (PROJECT_SPEC §8).
  async rewrites() {
    const backend =
      process.env.QUANT_API_URL ?? "http://127.0.0.1:8000";
    return [
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
    ];
  },
};

export default nextConfig;
