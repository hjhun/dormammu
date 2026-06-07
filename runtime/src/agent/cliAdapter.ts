import { spawn } from "node:child_process";
import { constants, createWriteStream } from "node:fs";
import { access, mkdir, readFile, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { Writable } from "node:stream";
import { finished } from "node:stream/promises";

import { AgentRunRequest, buildCommandPlan, CliCapabilities, InputMode } from "./commandBuilder.js";
import { parseHelpText } from "./helpParser.js";
import { applyDefaultPresetExtraArgs } from "./presetArgs.js";
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
export const CLI_RETRY_DELAY_MS = 1000;
export const CLI_RETRY_DELAY_MESSAGE =
  "Taking a short break for 1 seconds before the next agent CLI call.";

export type CliInvocationOptions = {
  extraArgs?: readonly string[];
  inputMode?: InputMode | null;
  promptFlag?: string | null;
};

export type FallbackCliOptions = CliInvocationOptions & {
  path: string;
};

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

export type RunAgentCommandOptions = Omit<
  RunSingleAgentCommandOptions,
  "capabilities" | "runId"
> & {
  fallbackAgentClis?: readonly (string | FallbackCliOptions)[];
  cliOverrides?: Record<string, CliInvocationOptions> | null;
  tokenExhaustionPatterns?: readonly string[];
  fallbackOnNonzeroExit?: boolean;
  inspectCapabilities?: typeof inspectCliCapabilities;
  runIdFactory?: (request: AgentRunRequest, attemptIndex: number) => string;
  retryDelayMs?: number;
};

export async function runAgentCommand(
  options: RunAgentCommandOptions
): Promise<AgentRunResult> {
  const request = applyCliOverride(options.request, {
    cliPath: options.request.cliPath,
    cliOverrides: options.cliOverrides
  });
  const candidates = await buildCandidateRequests(request, options);
  const requestedCliPath = recordedCliPath(options.request.cliPath);
  const attemptedCliPaths: string[] = [];
  let fallbackTrigger: string | null = null;

  for (let index = 0; index < candidates.length; index += 1) {
    if (index > 0) {
      await pauseBeforeRetry(options);
    }

    const candidate = candidates[index];
    const cwd = path.resolve(options.workdir ?? candidate.workdir ?? process.cwd());
    const inspect = options.inspectCapabilities ?? inspectCliCapabilities;
    const capabilities = await inspect(candidate.cliPath, { cwd, env: options.env });
    const effectiveRequest = applyDefaultPresetExtraArgs(candidate, capabilities);
    const result = await runSingleAgentCommand({
      ...options,
      request: effectiveRequest,
      capabilities,
      runId: options.runIdFactory?.(effectiveRequest, index)
    });
    attemptedCliPaths.push(result.cliPath);
    const enriched: AgentRunResult = {
      ...result,
      requestedCliPath,
      attemptedCliPaths: [...attemptedCliPaths],
      fallbackTrigger
    };

    let fallbackReason = await detectTokenExhaustion(
      enriched,
      options.tokenExhaustionPatterns ?? []
    );
    if (
      fallbackReason === null &&
      options.fallbackOnNonzeroExit === true &&
      enriched.exitCode !== 0 &&
      !enriched.timedOut
    ) {
      fallbackReason = `non-zero exit code ${enriched.exitCode}`;
    }
    if (fallbackReason === null || index === candidates.length - 1) {
      return {
        ...enriched,
        fallbackTrigger: fallbackReason ?? fallbackTrigger
      };
    }
    fallbackTrigger = fallbackReason;
  }

  throw new Error("No agent CLI candidates were available.");
}

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

async function buildCandidateRequests(
  request: AgentRunRequest,
  options: Pick<RunAgentCommandOptions, "fallbackAgentClis" | "cliOverrides" | "env">
): Promise<AgentRunRequest[]> {
  const candidates = [request];
  const seenPaths = new Set([request.cliPath]);

  for (const fallback of options.fallbackAgentClis ?? []) {
    const candidate = applyFallbackConfig(request, fallback, options.cliOverrides);
    if (
      seenPaths.has(candidate.cliPath) ||
      !(await cliCandidateAvailable(candidate.cliPath, options.env))
    ) {
      continue;
    }
    seenPaths.add(candidate.cliPath);
    candidates.push(candidate);
  }

  return candidates;
}

function applyFallbackConfig(
  request: AgentRunRequest,
  fallback: string | FallbackCliOptions,
  cliOverrides: Record<string, CliInvocationOptions> | null | undefined
): AgentRunRequest {
  const config = typeof fallback === "string" ? { path: fallback } : fallback;
  const fallbackRequest: AgentRunRequest = {
    ...request,
    cliPath: config.path,
    inputMode: config.inputMode ?? "auto",
    promptFlag: config.promptFlag ?? null,
    extraArgs: config.extraArgs ?? []
  };
  return applyCliOverride(fallbackRequest, {
    cliPath: config.path,
    cliOverrides
  });
}

function applyCliOverride(
  request: AgentRunRequest,
  options: {
    cliPath: string;
    cliOverrides?: Record<string, CliInvocationOptions> | null;
  }
): AgentRunRequest {
  const override = resolveCliOverride(options.cliPath, options.cliOverrides);
  if (override === null) {
    return request;
  }

  const inputMode =
    (request.inputMode ?? "auto") === "auto" && override.inputMode != null
      ? override.inputMode
      : request.inputMode;
  return {
    ...request,
    cliPath: options.cliPath,
    inputMode,
    promptFlag: request.promptFlag ?? override.promptFlag ?? null,
    extraArgs: mergeOverrideExtraArgs(override.extraArgs ?? [], request.extraArgs ?? [])
  };
}

function resolveCliOverride(
  cliPath: string,
  cliOverrides: Record<string, CliInvocationOptions> | null | undefined
): CliInvocationOptions | null {
  if (cliOverrides == null) {
    return null;
  }
  for (const key of cliOverrideKeys(cliPath)) {
    const override = cliOverrides[key];
    if (override !== undefined) {
      return override;
    }
  }
  return {};
}

function cliOverrideKeys(cliPath: string): string[] {
  const rawText = cliPath.trim();
  const keys = [rawText.toLowerCase(), path.basename(rawText).toLowerCase()];
  if (path.isAbsolute(rawText) || rawText.includes("/") || rawText.includes("\\")) {
    keys.push(path.resolve(expandUserPath(rawText)).toLowerCase());
  }
  return [...new Set(keys.filter(Boolean))];
}

function mergeOverrideExtraArgs(
  overrideArgs: readonly string[],
  requestArgs: readonly string[]
): string[] {
  if (!overrideArgs.length) {
    return [...requestArgs];
  }
  if (!requestArgs.length) {
    return [...overrideArgs];
  }

  const explicitFlags = new Set(
    requestArgs
      .map((arg) => arg.trim().toLowerCase())
      .filter((arg) => arg.startsWith("-") && arg.length > 0)
  );
  const merged: string[] = [];
  let index = 0;
  while (index < overrideArgs.length) {
    const arg = overrideArgs[index];
    const normalized = arg.trim().toLowerCase();
    if (explicitFlags.has(normalized)) {
      index += 1;
      if (index < overrideArgs.length && !overrideArgs[index].startsWith("-")) {
        index += 1;
      }
      continue;
    }
    merged.push(arg);
    index += 1;
  }
  return [...merged, ...requestArgs];
}

async function cliCandidateAvailable(
  cliPath: string,
  env: NodeJS.ProcessEnv | undefined
): Promise<boolean> {
  if (path.isAbsolute(cliPath) || cliPath.includes("/") || cliPath.includes("\\")) {
    try {
      await access(path.resolve(expandUserPath(cliPath)), constants.X_OK);
      return true;
    } catch {
      return false;
    }
  }

  for (const entry of (env?.PATH ?? process.env.PATH ?? "").split(path.delimiter)) {
    if (!entry) {
      continue;
    }
    try {
      await access(path.join(entry, cliPath), constants.X_OK);
      return true;
    } catch {
      // Keep scanning PATH entries.
    }
  }
  return false;
}

async function detectTokenExhaustion(
  result: AgentRunResult,
  patterns: readonly string[]
): Promise<string | null> {
  if (result.exitCode === 0) {
    return null;
  }

  const combinedOutput = [
    await readFile(result.stdoutPath, "utf8"),
    await readFile(result.stderrPath, "utf8")
  ]
    .join("\n")
    .toLowerCase();
  for (const pattern of patterns) {
    const normalizedPattern = pattern.trim().toLowerCase();
    if (normalizedPattern && combinedOutput.includes(normalizedPattern)) {
      return normalizedPattern;
    }
  }
  return null;
}

async function pauseBeforeRetry(
  options: Pick<RunAgentCommandOptions, "liveOutput" | "retryDelayMs">
): Promise<void> {
  options.liveOutput?.write(`${CLI_RETRY_DELAY_MESSAGE}\n`);
  const delayMs = options.retryDelayMs ?? CLI_RETRY_DELAY_MS;
  if (delayMs <= 0) {
    return;
  }
  await new Promise((resolve) => {
    setTimeout(resolve, delayMs);
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

function expandUserPath(filePath: string): string {
  if (filePath === "~") {
    return os.homedir();
  }
  if (filePath.startsWith("~/") || filePath.startsWith("~\\")) {
    return path.join(os.homedir(), filePath.slice(2));
  }
  return filePath;
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
