import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { chmod, mkdtemp, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { Writable } from "node:stream";

import type { CliCapabilities } from "./commandBuilder.js";
import type { AgentRunStarted } from "./runArtifacts.js";
import {
  AgentCommandAbortedError,
  inspectCliCapabilities,
  runAgentCommand,
  runSingleAgentCommand
} from "./cliAdapter.js";

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

test("runSingleAgentCommand aborts running processes on shutdown signal", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "dormammu-cli-adapter-"));
  const logsDir = path.join(root, ".dev", "logs");
  const hanging = await writeHangingAgent(root);
  const controller = new AbortController();
  const mirror = new MemoryWritable();

  await assert.rejects(
    runSingleAgentCommand({
      request: {
        cliPath: hanging,
        promptText: "Stop this process.",
        repoRoot: root,
        inputMode: "file"
      },
      capabilities: baseCapabilities,
      logsDir,
      runId: "run-abort",
      abortSignal: controller.signal,
      liveOutput: mirror,
      onStarted() {
        controller.abort();
      }
    }),
    AgentCommandAbortedError
  );

  const shutdownPattern = /interrupted by daemon shutdown request/;
  assert.match(
    await readFile(path.join(logsDir, "run-abort.stdout.log"), "utf8"),
    shutdownPattern
  );
  assert.match(mirror.text(), shutdownPattern);
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

test("runAgentCommand falls back across token-exhausted CLI candidates", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "dormammu-cli-adapter-"));
  const logsDir = path.join(root, ".dev", "logs");
  const primary = await writeExecutableAgent(root, "primary-agent", {
    exitCode: 1,
    message: "usage limit exceeded"
  });
  const fallbackOne = await writeExecutableAgent(root, "fallback-one", {
    exitCode: 1,
    message: "quota exceeded"
  });
  const fallbackTwo = await writeExecutableAgent(root, "fallback-two", {
    exitCode: 0,
    message: "done"
  });

  const result = await runAgentCommand({
    request: {
      cliPath: primary,
      promptText: "Write a tiny test plan.",
      repoRoot: root
    },
    fallbackAgentClis: [fallbackOne, fallbackTwo],
    tokenExhaustionPatterns: ["usage limit exceeded", "quota exceeded"],
    logsDir,
    retryDelayMs: 0,
    runIdFactory: (_request, index) => `attempt-${index}`,
    nowFactory: fixedClock([
      "2026-04-25T00:00:00.000Z",
      "2026-04-25T00:00:01.000Z",
      "2026-04-25T00:00:02.000Z",
      "2026-04-25T00:00:03.000Z",
      "2026-04-25T00:00:04.000Z",
      "2026-04-25T00:00:05.000Z"
    ])
  });

  assert.equal(result.exitCode, 0);
  assert.equal(result.requestedCliPath, path.resolve(primary));
  assert.equal(result.cliPath, path.resolve(fallbackTwo));
  assert.deepEqual(result.attemptedCliPaths, [
    path.resolve(primary),
    path.resolve(fallbackOne),
    path.resolve(fallbackTwo)
  ]);
  assert.equal(result.fallbackTrigger, "quota exceeded");
  assert.match(
    await readFile(result.stdoutPath, "utf8"),
    /\[fallback-two\]\nWrite a tiny test plan\./
  );
});

test("runAgentCommand supports nonzero fallback but not timeout fallback", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "dormammu-cli-adapter-"));
  const logsDir = path.join(root, ".dev", "logs");
  const failing = await writeExecutableAgent(root, "failing-agent", {
    exitCode: 2,
    message: "plain failure"
  });
  const fallback = await writeExecutableAgent(root, "fallback-agent", {
    exitCode: 0,
    message: "done"
  });
  const hanging = await writeHangingAgent(root);

  const nonzero = await runAgentCommand({
    request: {
      cliPath: failing,
      promptText: "Retry this failure.",
      repoRoot: root
    },
    fallbackAgentClis: [fallback],
    fallbackOnNonzeroExit: true,
    logsDir,
    retryDelayMs: 0,
    runIdFactory: (_request, index) => `nonzero-${index}`
  });
  assert.equal(nonzero.exitCode, 0);
  assert.equal(nonzero.fallbackTrigger, "non-zero exit code 2");
  assert.deepEqual(nonzero.attemptedCliPaths, [
    path.resolve(failing),
    path.resolve(fallback)
  ]);

  const timeout = await runAgentCommand({
    request: {
      cliPath: hanging,
      promptText: "Do not retry this timeout.",
      repoRoot: root
    },
    fallbackAgentClis: [fallback],
    fallbackOnNonzeroExit: true,
    logsDir,
    timeoutMs: 50,
    retryDelayMs: 0,
    runIdFactory: (_request, index) => `timeout-${index}`
  });
  assert.equal(timeout.exitCode, -1);
  assert.equal(timeout.timedOut, true);
  assert.equal(timeout.fallbackTrigger, null);
  assert.deepEqual(timeout.attemptedCliPaths, [path.resolve(hanging)]);
});

test("runAgentCommand applies CLI overrides without replacing explicit request flags", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "dormammu-cli-adapter-"));
  const logsDir = path.join(root, ".dev", "logs");
  const cline = await writeExecutableAgent(root, "cline", {
    exitCode: 0,
    message: "done"
  });

  const result = await runAgentCommand({
    request: {
      cliPath: cline,
      promptText: "Summarize the repository.",
      repoRoot: root,
      extraArgs: ["--timeout", "30"]
    },
    cliOverrides: {
      cline: {
        inputMode: "arg",
        promptFlag: "--prompt",
        extraArgs: ["-y", "--timeout", "1200", "--verbose"]
      }
    },
    logsDir,
    runIdFactory: () => "override-run"
  });

  assert.equal(result.exitCode, 0);
  assert.deepEqual(result.command, [
    cline,
    "--workdir",
    path.resolve(process.cwd()),
    "--prompt",
    "[cline]\nSummarize the repository.",
    "-y",
    "--verbose",
    "--timeout",
    "30"
  ]);
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

async function writeExecutableAgent(
  root: string,
  name: string,
  options: { exitCode: number; message: string }
): Promise<string> {
  const script = path.join(root, name);
  await writeFile(
    script,
    `#!${process.execPath}
const fs = require("node:fs");
const args = process.argv.slice(2);
if (args.includes("--help")) {
  console.log("usage: ${name} [OPTIONS]");
  console.log("  --prompt-file PATH");
  console.log("  --prompt TEXT");
  console.log("  --workdir PATH");
  process.exit(0);
}
let prompt = "";
if (args.includes("--prompt-file")) {
  prompt = fs.readFileSync(args[args.indexOf("--prompt-file") + 1], "utf8");
} else if (args.includes("--prompt")) {
  prompt = args[args.indexOf("--prompt") + 1];
} else {
  prompt = fs.readFileSync(0, "utf8");
}
console.log("PROMPT::" + prompt.trim());
console.error(${JSON.stringify(options.message)});
process.exit(${options.exitCode});
`,
    "utf8"
  );
  await chmod(script, 0o755);
  return script;
}

async function writeHangingAgent(root: string): Promise<string> {
  const script = path.join(root, "hanging-agent");
  await writeFile(
    script,
    `#!${process.execPath}
if (process.argv.includes("--help")) {
  console.log("usage: hanging-agent [OPTIONS]");
  console.log("  --prompt-file PATH");
  process.exit(0);
}
setInterval(() => {}, 1000);
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
