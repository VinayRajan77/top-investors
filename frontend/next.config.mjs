/** @type {import('next').NextConfig} */
const apiBase = process.env.API_PROXY_HOST
  ? `http://${process.env.API_PROXY_HOST}`
  : (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000');

export default {
  experimental: { typedRoutes: false },
  async rewrites() {
    return [{ source: '/api/:path*', destination: `${apiBase}/api/:path*` }];
  },
};
