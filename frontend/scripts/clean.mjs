/**
 * Remove every build artefact.
 *
 * `next dev` and `next build` write to different directories now
 * (see `next.config.ts`), so they cannot corrupt each other. This script
 * is for the case where a directory itself has gone bad -- a half-written
 * build after a crash, or a chunk that never got written.
 */
import { rm } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

const targets = [".next", ".next-dev", "node_modules/.cache"];

for (const target of targets) {
  await rm(join(root, target), { recursive: true, force: true });
  console.log(`removed ${target}`);
}
