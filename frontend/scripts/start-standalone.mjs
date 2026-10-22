/**
 * Start the production build.
 *
 * `next build` with `output: "standalone"` produces a self-contained server
 * in `.next/standalone`, but it deliberately leaves out the two directories
 * that have to be served alongside it: `public/` and the hashed static
 * assets. This script copies them in and then runs the server.
 *
 * The Docker image does the same copy at build time, so the container and
 * a local `pnpm start` behave identically.
 */
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { cp, mkdir } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const standalone = join(root, ".next", "standalone");

if (!existsSync(standalone)) {
  console.error("No production build found. Run `pnpm build` before `pnpm start`.");
  process.exit(1);
}

await mkdir(join(standalone, ".next"), { recursive: true });

for (const [from, to] of [
  [join(root, "public"), join(standalone, "public")],
  [join(root, ".next", "static"), join(standalone, ".next", "static")],
]) {
  if (!existsSync(from)) continue;
  await cp(from, to, { recursive: true });
}

const server = spawn(process.execPath, [join(standalone, "server.js")], {
  stdio: "inherit",
  env: process.env,
});

server.on("exit", (code) => process.exit(code ?? 0));
