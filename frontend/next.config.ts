import type { NextConfig } from "next";

/**
 * `next dev` and `next build` must never share an output directory.
 *
 * The dev server compiles routes on demand and writes its own chunk ids,
 * while a production build writes a completely different set. When they
 * share a directory, the webpack runtime that survives is the production
 * one, and it points at chunk files the dev server never wrote. Every
 * route then fails with `Cannot find module './NNN.js'` -- and it fails
 * *after* the page appears to compile, which makes it look like a code
 * problem rather than a cache problem.
 *
 * `NODE_ENV` is the signal: Next.js sets it to `development` before it
 * loads this config when running `next dev`, and to `production` for
 * `next build`. (`NEXT_PHASE` is not set on the dev path, so it cannot be
 * used to tell the two apart.)
 */
const isDevServer = process.env.NODE_ENV === "development";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  output: "standalone",
  poweredByHeader: false,
  // Separate directories, so a production build can never poison the dev
  // server (or the other way round).
  distDir: isDevServer ? ".next-dev" : ".next",
};

export default nextConfig;
