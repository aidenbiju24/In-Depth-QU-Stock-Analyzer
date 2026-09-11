import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Next 16 dev-origin protection: the app is commonly served from both
  // localhost:3000 and 127.0.0.1:3000; both must be allowed or dev resources
  // (HMR websocket, dev fonts) get blocked and hydration breaks.
  allowedDevOrigins: ["localhost", "127.0.0.1"],
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
