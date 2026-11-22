/** @type {import('next').NextConfig} */
const pagesBuild = process.env.PAGES_BUILD === '1';
const basePath = pagesBuild ? '/AI_Calendar_App_Personal' : '';

if (pagesBuild && !/^https:\/\/[^/]+\/?$/.test(process.env.NEXT_PUBLIC_API_URL ?? '')) {
  throw new Error('PAGES_BUILD requires NEXT_PUBLIC_API_URL to be the HTTPS Funnel origin');
}

const nextConfig = {
  ...(pagesBuild ? {
    output: 'export',
    basePath,
    trailingSlash: true,
    images: { unoptimized: true },
  } : {}),
  env: {
    NEXT_PUBLIC_APP_BASE_PATH: basePath,
  },
};

export default nextConfig;
