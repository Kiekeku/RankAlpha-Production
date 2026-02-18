const path = require('path')

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  images: {
    // Allow Google avatar URLs returned by NextAuth (e.g. lh3.googleusercontent.com)
    domains: ['lh3.googleusercontent.com'],
  },
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:6080',
  },
  async rewrites() {
    return [
      {
        source: '/api/proxy/:path*',
        destination: `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:6080'}/:path*`,
      },
    ];
  },
  webpack(config) {
    // Align Webpack resolution with the tsconfig `@/*` path alias used in the app router
    config.resolve.alias['@'] = config.resolve.alias['@'] || path.join(__dirname, 'src')
    return config
  },
};

module.exports = nextConfig;
