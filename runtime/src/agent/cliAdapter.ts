import { spawn } from "node:child_process";
import { createWriteStream } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { Writable } from "node:stream";
import { finished } from "node:stream/promises";

import { AgentRunRequest, buildCommandPlan, CliCapabilities } from "./commandBuilder.js";
import { parseHelpText } from "./helpParser.js";
import { prependCliIdentity } from "./promptIdentity.js";
import {
  AgentRunResult,
  AgentRunStarted,
  agentRunResultToDict,
  agentRunStartedToDict,
  runMetadataPath,
  runPromptPath,
  runStderrPath,
  runStdoutPath
} from "./runArtifacts.js";

export const CLI_TIMEOUT_MESSAGE_PREFIX = "[dormammu] Agent CLI process timed out after";

export type RunSingleAgentCommandOptions = {
  request: AgentRunRequest;
  capabilities: CliCapabilities;
  logsDir: string;
  workdir?: string | null;
  env?: NodeJS.ProcessEnv;
  runId?: string;
  nowFactory?: () => string;
  timeoutMs?: number | null;
  liveOutput?: Writable | null;
  onStarted?: (started: AgentRunStarted) => void;
};

export type InspectCliCapabilitiesOptions = {
  cwd: string;
  env?: NodeJS.ProcessEnv;
};

export async function inspectCliCapabilities(
  cliPath: string,
  options: InspectCliCapabilitiesOptions
): Promise<CliCapabilities> {
  const completed = await captureCommand([cliPath, "--help"], options);
  const firstHelpText = completed.stdout || completed.stderr;
  const baseCapabilities = parseHelpText(firstHelpText, {
    executableName: cliExecutableName(cliPath),
    helpExitCode: completed.exitCode
  });
  const helpTextParts = [firstHelpText];

  if ((baseCapabilities.commandPrefix ?? []).length) {
    const prefixed = await captureCommand(
      [cliPath, ...(baseCapabilities.commandPrefix ?? []), "--help"],
      options
    );
    const prefixedHelpText = prefixed.stdout || prefixed.stderr;
    if (prefixedHelpText) {
      helpTextParts.push(prefixedHelpText);
    }
  }

  return parseHelpText(helpTextParts.filter(Boolean).join("\n"), {
    executableName: cliExecutableName(cliPath),
    helpExitCode: completed.exitCode
  });
}

export async function runSingleAgentCommand(
  options: RunSingleAgentCommandOptions
): Promise<AgentRunResult> {
  const now = options.nowFactory ?? isoNow;
  const runId = options.runId ?? generatedRunId(options.request.runLabel);
  const logsDir = path.resolve(options.logsDir);
  await mkdir(logsDir, { recursive: true });

  const promptPath = runPromptPath(logsDir, runId);
  const stdoutPath = runStdoutPath(logsDir, runId);
  const stderrPath = runStderrPath(logsDir, runId);
  const metadataPath = runMetadataPath(logsDir, runId);
  const effectiveWorkdir = path.resolve(
    options.workdir ?? options.request.workdir ?? process.cwd()
  );
  const promptText = prependCliIdentity(
    options.request.promptText,
    options.request.cliPath
  );
  const request: AgentRunRequest = {
    ...options.request,
    promptText,
    workdir: effectiveWorkdir
  };
  const commandPlan = buildCommandPlan(request, options.capabilities, promptPath);

  await writeFile(promptPath, promptText, "utf8");
  await writeFile(stdoutPath, "", "utf8");
  await writeFile(stderrPath, "", "utf8");

  const startedAt = now();
  const started: AgentRunStarted = {
    runId,
    cliPath: recordedCliPath(request.cliPath),
    workdir: effectiveWorkdir,
    promptMode: commandPlan.promptMode,
    command: commandPlan.argv,
    startedAt,
    promptPath,
    stdoutPath,
    stderrPath,
    metadataPath,
    capabilities: options.capabilities
  };
  await writeJson(metadataPath, agentRunStartedToDict(started, { includeHelpText: true }));
  options.onStarted?.(started);

  const stdoutStream = createWriteStream(stdoutPath, { flags: "w" });
  const stderrStream = createWriteStream(stderrPath, { flags: "w" });
  let timedOut = false;
  let exitCode = -1;

  try {
    exitCode = await executeCommand({
      argv: commandPlan.argv,
      cwd: effectiveWorkdir,
      env: options.env,
      stdinInput: commandPlan.stdinInput,
      timeoutMs: options.timeoutMs,
      stdoutStream,
      stderrStream,
      liveOutput: options.liveOutput ?? null,
      onTimedOut() {
        timedOut = true;
      }
    });
    if (timedOut) {
      exitCode = -1;
      const message = [
        "",
        `${CLI_TIMEOUT_MESSAGE_PREFIX} ${options.timeoutMs}ms and was forcefully terminated.`,
        ""
      ].join("\n");
      stdoutStream.write(message);
      options.liveOutput?.write(message);
    }
  } finally {
    stdoutStream.end();
    stderrStream.end();
    await Promise.all([finished(stdoutStream), finished(stderrStream)]);
  }

  const completedAt = now();
  const result: AgentRunResult = {
    ...started,
    exitCode,
    completedAt,
    timedOut
  };
  await writeJson(metadataPath, agentRunResultToDict(result, { includeHelpText: true }));
  return result;
}

async function executeCommand(options: {
  argv: string[];
  cwd: string;
  env?: NodeJS.ProcessEnv;
  stdinInput: string | null;
  timeoutMs?: number | null;
  stdoutStream: Writable;
  stderrStream: Writable;
  liveOutput: Writable | null;
  onTimedOut: () => void;
}): Promise<number> {
  if (!options.argv.length) {
    throw new Error("Cannot execute an empty agent command.");
  }

  const child = spawn(options.argv[0], options.argv.slice(1), {
    cwd: options.cwd,
    env: options.env ? { ...process.env, ...options.env } : process.env,
    stdio: [options.stdinInput === null ? "ignore" : "pipe", "pipe", "pipe"]
  });

  child.stdout?.on("data", (chunk: Buffer) => {
    options.stdoutStream.write(chunk);
    options.liveOutput?.write(chunk);
  });
  child.stderr?.on("data", (chunk: Buffer) => {
    options.stderrStream.write(chunk);
    options.liveOutput?.write(chunk);
  });

  if (child.stdin && options.stdinInput !== null) {
    child.stdin.end(options.stdinInput);
  }

  return await new Promise<number>((resolve, reject) => {
    let timeout: NodeJS.Timeout | null = null;
    let settled = false;

    const settle = (callback: () => void): void => {
      if (settled) {
        return;
      }
      settled = true;
      if (timeout !== null) {
        clearTimeout(timeout);
      }
      callback();
    };

    child.once("error", (error) => {
      settle(() => reject(error));
    });
    child.once("close", (code) => {
      settle(() => resolve(code ?? -1));
    });

    if (options.timeoutMs !== null && options.timeoutMs !== undefined) {
      timeout = setTimeout(() => {
        options.onTimedOut();
        child.kill("SIGKILL");
      }, options.timeoutMs);
    }
  });
}

async function captureCommand(
  argv: string[],
  options: InspectCliCapabilitiesOptions
): Promise<{ stdout: string; stderr: string; exitCode: number }> {
  if (!argv.length) {
    throw new Error("Cannot execute an empty agent command.");
  }

  const child = spawn(argv[0], argv.slice(1), {
    cwd: options.cwd,
    env: options.env ? { ...process.env, ...options.env } : process.env,
    stdio: ["ignore", "pipe", "pipe"]
  });

  const stdoutChunks: Buffer[] = [];
  const stderrChunks: Buffer[] = [];
  child.stdout?.on("data", (chunk: Buffer) => {
    stdoutChunks.push(chunk);
  });
  child.stderr?.on("data", (chunk: Buffer) => {
    stderrChunks.push(chunk);
  });

  return await new Promise((resolve, reject) => {
    child.once("error", reject);
    child.once("close", (code) => {
      resolve({
        stdout: Buffer.concat(stdoutChunks).toString("utf8"),
        stderr: Buffer.concat(stderrChunks).toString("utf8"),
        exitCode: code ?? -1
      });
    });
  });
}

async function writeJson(filePath: string, payload: unknown): Promise<void> {
  await writeFile(filePath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

function recordedCliPath(cliPath: string): string {
  if (path.isAbsolute(cliPath) || cliPath.includes("/") || cliPath.includes("\\")) {
    return path.resolve(cliPath);
  }
  return cliPath;
}

function cliExecutableName(cliPath: string): string {
  const normalized = cliPath.replace(/\\/g, "/");
  const index = normalized.lastIndexOf("/");
  return index === -1 ? normalized : normalized.slice(index + 1);
}

function generatedRunId(label: string | null | undefined): string {
  return `${runTimestamp(new Date())}-${safeLabel(label)}`;
}

function runTimestamp(date: Date): string {
  const pad = (value: number, width = 2): string => String(value).padStart(width, "0");
  return [
    date.getFullYear(),
    pad(date.getMonth() + 1),
    pad(date.getDate()),
    "-",
    pad(date.getHours()),
    pad(date.getMinutes()),
    pad(date.getSeconds()),
    "-",
    pad(date.getMilliseconds() * 1000, 6)
  ].join("");
}

function safeLabel(label: string | null | undefined): string {
  const normalized = (label ?? "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/gi, "-")
    .replace(/^-+|-+$/g, "");
  return normalized || "agent-run";
}

function isoNow(): string {
  const date = new Date();
  const offsetMinutes = -date.getTimezoneOffset();
  const localTimestamp = new Date(date.getTime() + offsetMinutes * 60_000)
    .toISOString()
    .slice(0, 19);
  return `${localTimestamp}${timezoneOffsetSuffix(offsetMinutes)}`;
}

function timezoneOffsetSuffix(offsetMinutes: number): string {
  const sign = offsetMinutes >= 0 ? "+" : "-";
  const absolute = Math.abs(offsetMinutes);
  const hours = Math.floor(absolute / 60);
  const minutes = absolute % 60;
  return `${sign}${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}
