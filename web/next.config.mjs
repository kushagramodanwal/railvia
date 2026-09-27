/** @type {import('next').NextConfig} */

// Every route in this app is a client component with client-side data
// fetching, so Next can emit plain static files. That lets FastAPI serve the
// UI itself in production: one process, one origin, no Node at runtime, no
// CORS and no proxy. Set STATIC_EXPORT=1 for that build.
const isExport = process.env.STATIC_EXPORT === "1";

const nextConfig = isExport
  ? {
      output: "export",
      // Directory-style URLs, so /plan resolves to plan/index.html when a
      // plain file server handles it.
      trailingSlash: true,
      images: { unoptimized: true },
    }
  : {
      // Development only: two servers, so proxy /api to the Python one.
      async rewrites() {
        const api = process.env.API_ORIGIN ?? "http://127.0.0.1:8077";
        return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
      },
    };

export default nextConfig;
