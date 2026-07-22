/** @type {import('next').NextConfig} */
const apiBase = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";
// Strip trailing slash so we can safely concatenate `/api/...`.
const apiOrigin = apiBase.replace(/\/+$/, "");

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiOrigin}/api/:path*`,
      },
      {
        // Proxy /v1/* to FastAPI so SSE / cross-origin calls work in dev.
        source: "/v1/:path*",
        destination: `${apiOrigin}/v1/:path*`,
      },
    ];
  },
  transpilePackages: ["react-plotly.js", "plotly.js-dist-min"],
};

export default nextConfig;