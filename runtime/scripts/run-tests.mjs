import { readdirSync } from "node:fs";
import { join } from "node:path";
import { spawnSync } from "node:child_process";

function collectTests(directory) {
  const tests = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const fullPath = join(directory, entry.name);
    if (entry.isDirectory()) {
      tests.push(...collectTests(fullPath));
    } else if (entry.isFile() && entry.name.endsWith(".test.js")) {
      tests.push(fullPath);
    }
  }
  return tests.sort();
}

const tests = collectTests("dist");
if (!tests.length) {
  console.error("No compiled test files found under dist.");
  process.exit(1);
}

const result = spawnSync(process.execPath, ["--test", ...tests], {
  stdio: "inherit"
});
process.exit(result.status ?? 1);
