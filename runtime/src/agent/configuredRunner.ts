import os from "node:os";
import path from "node:path";

import type { AgentRunRequest, InputMode } from "./commandBuilder.js";
import {
  runAgentCommand,
  type CliInvocationOptions,
  type FallbackCliOptions,
  type RunAgentCommandOptions
} from "./cliAdapter.js";
import type { AgentProfile } from "./profiles.js";
import type { AgentRunResult } from "./runArtifacts.js";

const DEFAULT_FALLBACK_AGENT_CLIS = ["codex", "claude", "gemini"] as const;
const DEFAULT_TOKEN_EXHAUSTION_PATTERNS = [
  "usage limit",
  "quota exceeded",
  "rate limit exceeded",
  "token limit",
  "insufficient credits",
  "credit balance is too low"
] as const;
const VALID_INPUT_MODES = new Set(["auto", "file", "arg", "stdin", "positional"]);

export type AgentRuntimeConfig = {
  activeAgentCli: string | null;
  fallbackAgentClis: readonly FallbackCliOptions[];
  cliOverrides: Record<string, CliInvocationOptions>;
  tokenExhaustionPatterns: readonly string[];
  processTimeoutMs: number | null;
  fallbackOnNonzeroExit: boolean;
};

export type AgentRuntimeConfigOptions = {
  configPath?: string | null;
};

export type RunConfiguredAgentCommandOptions = Omit<
  RunAgentCommandOptions,
  | "request"
  | "fallbackAgentClis"
  | "cliOverrides"
  | "tokenExhaustionPatterns"
  | "fallbackOnNonzeroExit"
  | "timeoutMs"
> & {
  config: AgentRuntimeConfig;
  request: Omit<AgentRunRequest, "cliPath"> & { cliPath?: string | null };
  profile?: AgentProfile | null;
  timeoutMs?: number | null;
  runner?: typeof runAgentCommand;
};

export function parseAgentRuntimeConfig(
  payload: unknown,
  options: AgentRuntimeConfigOptions = {}
): AgentRuntimeConfig {
  const source = options.configPath ?? "dormammu.json";
  const configDir = options.configPath ? path.dirname(options.configPath) : null;
  const config = asRecord(payload, "Dormammu config file must contain a JSON object", source);
  const fallbackValue = config.fallback_agent_clis;

  return {
    activeAgentCli: parseActiveAgentCli(config.active_agent_cli, source, configDir),
    fallbackAgentClis:
      fallbackValue === undefined
        ? DEFAULT_FALLBACK_AGENT_CLIS.map((cliPath) => ({ path: cliPath }))
        : parseFallbackAgentClis(fallbackValue, source, configDir),
    cliOverrides: parseCliOverrides(config.cli_overrides, source, configDir),
    tokenExhaustionPatterns:
      config.token_exhaustion_patterns === undefined
        ? [...DEFAULT_TOKEN_EXHAUSTION_PATTERNS]
        : nonEmptyOrDefault(
            parseStringList(config.token_exhaustion_patterns, "token_exhaustion_patterns", source),
            DEFAULT_TOKEN_EXHAUSTION_PATTERNS
          ),
    processTimeoutMs: parseProcessTimeoutMs(config.process_timeout_seconds, source),
    fallbackOnNonzeroExit: Boolean(config.fallback_on_nonzero_exit)
  };
}

export async function runConfiguredAgentCommand(
  options: RunConfiguredAgentCommandOptions
): Promise<AgentRunResult> {
  const {
    config,
    request: rawRequest,
    profile,
    runner: injectedRunner,
    timeoutMs,
    ...runOptions
  } = options;
  const cliPath = rawRequest.cliPath ?? profile?.cli_override ?? config.activeAgentCli;
  if (!cliPath) {
    throw new Error("No CLI is configured. Set active_agent_cli or request.cliPath.");
  }
  const runner = injectedRunner ?? runAgentCommand;
  return await runner({
    ...runOptions,
    request: {
      ...rawRequest,
      cliPath
    },
    fallbackAgentClis: config.fallbackAgentClis,
    cliOverrides: config.cliOverrides,
    tokenExhaustionPatterns: config.tokenExhaustionPatterns,
    fallbackOnNonzeroExit: config.fallbackOnNonzeroExit,
    timeoutMs: timeoutMs !== undefined ? timeoutMs : config.processTimeoutMs
  });
}

function parseActiveAgentCli(
  value: unknown,
  source: string,
  configDir: string | null
): string | null {
  if (value === undefined || value === null) {
    return null;
  }
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`active_agent_cli must be a non-empty string in ${source}`);
  }
  return resolveCliPath(value, configDir);
}

function parseFallbackAgentClis(
  value: unknown,
  source: string,
  configDir: string | null
): FallbackCliOptions[] {
  if (value === null) {
    return [];
  }
  if (!Array.isArray(value)) {
    throw new Error(`fallback_agent_clis must be a JSON array in ${source}`);
  }
  return value.map((item) => parseFallbackCliEntry(item, source, configDir));
}

function parseFallbackCliEntry(
  value: unknown,
  source: string,
  configDir: string | null
): FallbackCliOptions {
  if (typeof value === "string") {
    return { path: resolveCliPath(value, configDir) };
  }
  const payload = asRecord(
    value,
    `fallback_agent_clis entries must be strings or objects in ${source}`,
    source
  );
  const rawPath = payload.path;
  if (typeof rawPath !== "string" || !rawPath.trim()) {
    throw new Error(`fallback_agent_clis entries must include a non-empty 'path' in ${source}`);
  }
  return {
    ...parseCliInvocationSettings(payload, "fallback_agent_clis", source),
    path: resolveCliPath(rawPath, configDir)
  };
}

function parseCliOverrides(
  value: unknown,
  source: string,
  configDir: string | null
): Record<string, CliInvocationOptions> {
  if (value === undefined || value === null) {
    return {};
  }
  const payload = asRecord(value, `cli_overrides must be a JSON object in ${source}`, source);
  const overrides: Record<string, CliInvocationOptions> = {};
  for (const [rawKey, rawValue] of Object.entries(payload)) {
    if (!rawKey.trim()) {
      throw new Error("cli_overrides keys must be non-empty strings");
    }
    const rawOverride = asRecord(rawValue, "cli_overrides values must be JSON objects", source);
    overrides[normalizeCliOverrideKey(rawKey, configDir)] = parseCliInvocationSettings(
      rawOverride,
      "cli_overrides",
      source
    );
  }
  return overrides;
}

function parseCliInvocationSettings(
  payload: Record<string, unknown>,
  fieldPrefix: string,
  source: string
): CliInvocationOptions {
  const inputMode = payload.input_mode;
  if (inputMode !== undefined && inputMode !== null) {
    if (typeof inputMode !== "string" || !VALID_INPUT_MODES.has(inputMode)) {
      throw new Error(`Unsupported ${fieldPrefix}.input_mode: ${String(inputMode)}`);
    }
  }

  const promptFlag = payload.prompt_flag;
  if (promptFlag !== undefined && promptFlag !== null && typeof promptFlag !== "string") {
    throw new Error(`${fieldPrefix}.prompt_flag must be a string when provided`);
  }

  return {
    extraArgs: parseStringList(payload.extra_args ?? [], `${fieldPrefix}.extra_args`, source),
    inputMode: (inputMode ?? null) as InputMode | null,
    promptFlag: (promptFlag ?? null) as string | null
  };
}

function parseStringList(value: unknown, fieldName: string, source: string): string[] {
  if (value === null) {
    return [];
  }
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new Error(`${fieldName} must be a JSON array of strings in ${source}`);
  }
  return [...value];
}

function nonEmptyOrDefault(
  values: readonly string[],
  defaults: readonly string[]
): readonly string[] {
  return values.length ? [...values] : [...defaults];
}

function parseProcessTimeoutMs(value: unknown, source: string): number | null {
  if (value === undefined || value === null) {
    return null;
  }
  const seconds = Number(value);
  if (!Number.isFinite(seconds)) {
    throw new Error(`process_timeout_seconds must be an integer in ${source}`);
  }
  return Math.trunc(seconds) * 1000;
}

function asRecord(value: unknown, message: string, source: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(message.includes(source) ? message : `${message}: ${source}`);
  }
  return value as Record<string, unknown>;
}

function resolveCliPath(rawPath: string, configDir: string | null): string {
  const expanded = expandUserPath(rawPath);
  if (path.isAbsolute(expanded)) {
    return path.resolve(expanded);
  }
  if (configDir !== null && (rawPath.includes("/") || rawPath.startsWith("."))) {
    return path.resolve(configDir, expanded);
  }
  return expanded;
}

function normalizeCliOverrideKey(rawKey: string, configDir: string | null): string {
  const expanded = expandUserPath(rawKey);
  if (path.isAbsolute(expanded) || rawKey.includes("/") || rawKey.startsWith(".")) {
    const resolved = path.isAbsolute(expanded)
      ? path.resolve(expanded)
      : path.resolve(configDir ?? process.cwd(), expanded);
    return resolved.toLowerCase();
  }
  return rawKey.trim().toLowerCase();
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
