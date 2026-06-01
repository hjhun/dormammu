import { copyFileSync, existsSync, mkdirSync, readdirSync, unlinkSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = dirname(fileURLToPath(import.meta.url));
const frontendRoot = resolve(scriptDir, "..");
const repoRoot = resolve(frontendRoot, "..");
const distDir = resolve(frontendRoot, "dist");
const distAssetsDir = resolve(distDir, "assets");
const staticDir = resolve(repoRoot, "backend", "dormammu", "web", "static");
const staticAssetsDir = resolve(staticDir, "assets");

if (!existsSync(distDir)) {
  throw new Error(`Frontend dist directory is missing: ${distDir}`);
}

mkdirSync(staticAssetsDir, { recursive: true });

for (const entry of readdirSync(staticAssetsDir, { withFileTypes: true })) {
  if (entry.isFile()) {
    unlinkSync(resolve(staticAssetsDir, entry.name));
  }
}

copyFileSync(resolve(distDir, "index.html"), resolve(staticDir, "index.html"));
for (const entry of readdirSync(distAssetsDir, { withFileTypes: true })) {
  if (entry.isFile()) {
    copyFileSync(resolve(distAssetsDir, entry.name), resolve(staticAssetsDir, entry.name));
  }
}

console.log(`Synced ${distDir} -> ${staticDir}`);
