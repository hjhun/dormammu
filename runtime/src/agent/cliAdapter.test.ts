import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { chmod, mkdtemp, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { Writable } from "node:stream";

import type { CliCapabilities } from "./commandBuilder.js";
import type { AgentRunStarted } from "./runArtifacts.js";
import { inspectCliCapabilities, runSingleAgentCommand } from "./cliAdapter.js";

const baseCapabilities: CliCapabilities = {
  helpFlag: "--help",
  promptFileFlag: "--prompt-file",
  promptArgFlag: "--prompt",
  workdirFlag: "--cwd",
  helpText: "usage: fake",
  helpExitCode: 0
};

test("runSingleAgentCommand writes prompt, output, and metadata artifacts", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "dormammu-cli-adapter-"));
  const logsDir = path.join(root, ".dev", "logs");
  const fakeCli = await writeFakeCli(root);
  const promptHeader = `[${path.basename(process.execPath)}]`;
  const startedPayloads: unknown[] = [];

  const result = await runSingleAgentCommand({
    request: {
      cliPath: process.execPath,
      promptText: "Write a tiny test plan.",
      repoRoot: root,
      extraArgs: ["--echo-tag", "phase3"],
      runLabel: "phase 3 smoke"
    },
    capabilities: {
      ...baseCapabilities,
      commandPrefix: [fakeCli]
    },
    logsDir,
    runId: "run-file",
    nowFactory: fixedClock([
      "2026-04-25T00:00:00.000Z",
      "2026-04-25T00:00:01.000Z"
    ]),
    onStarted(started: AgentRunStarted) {
      startedPayloads.push(JSON.parse(readFileSyncUtf8(started.metadataPath)));
    }
  });

  assert.equal(result.exitCode, 0);
  assert.equal(result.promptMode, "file");
  assert.deepEqual(result.command, [
    process.execPath,
    fakeCli,
    "--cwd",
    process.cwd(),
    "--prompt-file",
    path.join(logsDir, "run-file.prompt.txt"),
    "--echo-tag",
    "phase3"
  ]);
  assert.equal(
    await readFile(result.promptPath, "utf8"),
    `${promptHeader}\nWrite a tiny test plan.`
  );
  assert.ok(
    (await readFile(result.stdoutPath, "utf8")).includes(
      `PROMPT::${promptHeader}\nWrite a tiny test plan.`
    )
  );
  assert.match(await readFile(result.stdoutPath, "utf8"), /TAG::phase3/);
  assert.match(await readFile(result.stderrPath, "utf8"), /TRACE::stderr/);

  assert.equal(startedPayloads.length, 1);
  assert.equal((startedPayloads[0] as Record<string, unknown>).run_id, "run-file");
  assert.equal(
    (startedPayloads[0] as Record<string, unknown>).started_at,
    "2026-04-25T00:00:00.000Z"
  );
  assert.equal((startedPayloads[0] as Record<string, unknown>).exit_code, undefined);

  const metadata = JSON.parse(await readFile(result.metadataPath, "utf8"));
  assert.equal(metadata.run_id, "run-file");
  assert.equal(metadata.exit_code, 0);
  assert.equal(metadata.completed_at, "2026-04-25T00:00:01.000Z");
  assert.equal(metadata.timed_out, false);
  assert.deepEqual(
    metadata.artifact_refs.map((item: { kind: string }) => item.kind),
    ["prompt", "stdout", "stderr", "metadata"]
  );
});

test("runSingleAgentCommand supports stdin mode and mirrors live output", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "dormammu-cli-adapter-"));
  const logsDir = path.join(root, ".dev", "logs");
  const fakeCli = await writeFakeCli(root);
  const promptHeader = `[${path.basename(process.execPath)}]`;
  const mirror = new MemoryWritable();

  const result = await runSingleAgentCommand({
    request: {
      cliPath: process.execPath,
      promptText: "Mirror this prompt.",
      repoRoot: root,
      inputMode: "stdin"
    },
    capabilities: {
      ...baseCapabilities,
      commandPrefix: [fakeCli]
    },
    logsDir,
    runId: "run-stdin",
    nowFactory: fixedClock([
      "2026-04-25T00:00:00.000Z",
      "2026-04-25T00:00:01.000Z"
    ]),
    liveOutput: mirror
  });

  assert.equal(result.exitCode, 0);
  assert.equal(result.promptMode, "stdin");
  assert.equal(await readFile(result.promptPath, "utf8"), `${promptHeader}\nMirror this prompt.`);
  assert.ok(
    (await readFile(result.stdoutPath, "utf8")).includes(
      `PROMPT::${promptHeader}\nMirror this prompt.`
    )
  );
  assert.match(await readFile(result.stderrPath, "utf8"), /TRACE::stderr/);
  assert.ok(mirror.text().includes(`PROMPT::${promptHeader}\nMirror this prompt.`));
  assert.match(mirror.text(), /TRACE::stderr/);
});

test("runSingleAgentCommand terminates timed out processes", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "dormammu-cli-adapter-"));
  const logsDir = path.join(root, ".dev", "logs");
  const slowCli = await writeSlowCli(root);

  const result = await runSingleAgentCommand({
    request: {
      cliPath: process.execPath,
      promptText: "This should time out.",
      repoRoot: root,
      inputMode: "stdin"
    },
    capabilities: {
      ...baseCapabilities,
      commandPrefix: [slowCli]
    },
    logsDir,
    runId: "run-timeout",
    timeoutMs: 50,
    nowFactory: fixedClock([
      "2026-04-25T00:00:00.000Z",
      "2026-04-25T00:00:01.000Z"
    ])
  });

  assert.equal(result.exitCode, -1);
  assert.equal(result.timedOut, true);
  assert.match(await readFile(result.stdoutPath, "utf8"), /timed out after 50ms/);

  const metadata = JSON.parse(await readFile(result.metadataPath, "utf8"));
  assert.equal(metadata.exit_code, -1);
  assert.equal(metadata.timed_out, true);
});

test("inspectCliCapabilities parses help output and prefixed help output", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "dormammu-cli-adapter-"));
  const fakeCodex = await writeFakeCodexCli(root);

  const capabilities = await inspectCliCapabilities(fakeCodex, { cwd: root });

  assert.equal(capabilities.presetKey, "codex");
  assert.equal(capabilities.presetSource, "executable_name");
  assert.deepEqual(capabilities.commandPrefix, ["exec"]);
  assert.equal(capabilities.promptPositional, true);
  assert.equal(capabilities.helpExitCode, 0);
  assert.match(capabilities.helpText, /usage: codex/);
  assert.match(capabilities.helpText, /--skip-git-repo-check/);
});

test("inspectCliCapabilities parses generic prompt and workdir flags", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "dormammu-cli-adapter-"));
  const fakeAgent = await writeFakeHelpCli(root);

  const capabilities = await inspectCliCapabilities(fakeAgent, { cwd: root });

  assert.equal(capabilities.promptFileFlag, "--prompt-file");
  assert.equal(capabilities.promptArgFlag, "--prompt");
  assert.equal(capabilities.workdirFlag, "--workdir");
  assert.equal(capabilities.presetKey, null);
});

async function writeFakeCli(root: string): Promise<string> {
  const script = path.join(root, "fake-cli.cjs");
  await writeFile(
    script,
    `
const fs = require("node:fs");

const args = process.argv.slice(2);
let prompt = "";
if (args.includes("--prompt-file")) {
  prompt = fs.readFileSync(args[args.indexOf("--prompt-file") + 1], "utf8");
} else if (args.includes("--prompt")) {
  prompt = args[args.indexOf("--prompt") + 1];
} else {
  prompt = fs.readFileSync(0, "utf8");
}

let tag = "";
if (args.includes("--echo-tag")) {
  tag = args[args.indexOf("--echo-tag") + 1];
}

console.log("PROMPT::" + prompt.trim());
console.log("TAG::" + tag);
console.error("TRACE::stderr");
`,
    "utf8"
  );
  return script;
}

async function writeSlowCli(root: string): Promise<string> {
  const script = path.join(root, "slow-cli.cjs");
  await writeFile(
    script,
    `
process.stdin.resume();
setTimeout(() => {
  console.log("late output");
}, 1000);
`,
    "utf8"
  );
  return script;
}

async function writeFakeCodexCli(root: string): Promise<string> {
  const script = path.join(root, "codex");
  await writeFile(
    script,
    `#!${process.execPath}
const args = process.argv.slice(2);
if (args[0] === "exec" && args.includes("--help")) {
  console.log("usage: codex exec [OPTIONS]");
  console.log("  --skip-git-repo-check");
  process.exit(0);
}
if (args.includes("--help")) {
  console.log("usage: codex [OPTIONS]");
  console.log("  codex exec");
  process.exit(0);
}
process.exit(0);
`,
    "utf8"
  );
  await chmod(script, 0o755);
  return script;
}

async function writeFakeHelpCli(root: string): Promise<string> {
  const script = path.join(root, "fake-help-agent");
  await writeFile(
    script,
    `#!${process.execPath}
if (process.argv.includes("--help")) {
  console.log("usage: fake-help-agent");
  console.log("  --prompt-file PATH");
  console.log("  --prompt TEXT");
  console.log("  --workdir PATH");
  process.exit(0);
}
process.exit(0);
`,
    "utf8"
  );
  await chmod(script, 0o755);
  return script;
}

function fixedClock(values: string[]): () => string {
  let index = 0;
  return () => values[Math.min(index++, values.length - 1)];
}

function readFileSyncUtf8(filePath: string): string {
  return readFileSync(filePath, "utf8");
}

class MemoryWritable extends Writable {
  private chunks: Buffer[] = [];

  _write(
    chunk: Buffer | string,
    _encoding: BufferEncoding,
    callback: (error?: Error | null) => void
  ): void {
    this.chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
    callback();
  }

  text(): string {
    return Buffer.concat(this.chunks).toString("utf8");
  }
}
