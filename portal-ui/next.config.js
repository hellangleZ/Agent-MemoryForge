const path = require('path');

const apiProxyTarget = process.env.PORTAL_API_PROXY_TARGET || 'http://127.0.0.1:8080';

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  devIndicators: false,
  outputFileTracingRoot: path.join(__dirname),
  // 图片配置
  images: {
    remotePatterns: [
      {
        protocol: 'http',
        hostname: 'localhost',
      },
    ],
    unoptimized: true,
  },
  // API代理配置 - 转发请求到后端网关
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${apiProxyTarget}/api/:path*`,
      },
      {
        source: '/v1/:path*',
        destination: `${apiProxyTarget}/v1/:path*`,
      },
      {
        source: '/portal/v1/:path*',
        destination: `${apiProxyTarget}/portal/v1/:path*`,
      },
    ];
  },
  // 环境变量
  env: {
    // Prefer same-origin relative requests via `rewrites()` for cookie-based auth.
    // You can still override to an absolute backend URL if you need to bypass Next proxy.
    NEXT_PUBLIC_API_BASE: process.env.NEXT_PUBLIC_API_BASE || '',
    NEXT_PUBLIC_PORTAL_PORT: process.env.NEXT_PUBLIC_PORTAL_PORT || '3000',
  },
};

module.exports = nextConfig;
