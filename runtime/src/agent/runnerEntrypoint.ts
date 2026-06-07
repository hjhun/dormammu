import type { AgentRunRequest, InputMode } from "./commandBuilder.js";
import {
  parseAgentRuntimeConfig,
  runConfiguredAgentCommand,
  type RunConfiguredAgentCommandOptions
} from "./configuredRunner.js";
import {
  agentRunResultToDict,
  type AgentRunResultPayload
} from "./runArtifacts.js";

const VALID_INPUT_MODES = new Set(["auto", "file", "arg", "stdin", "positional"]);

export type AgentRunnerEntrypointPayload = {
  config?: unknown;
  config_path?: string | null;
  request: {
    cli_path?: string | null;
    prompt_text: string;
    repo_root: string;
    workdir?: string | null;
    input_mode?: InputMode;
    prompt_flag?: string | null;
    extra_args?: string[];
    run_label?: string | null;
  };
  logs_dir: string;
  timeout_ms?: number | null;
  include_help_text?: boolean;
};

export type AgentRunnerEntrypointOptions = Omit<
  RunConfiguredAgentCommandOptions,
  "config" | "request" | "logsDir" | "timeoutMs"
>;

export async function runAgentRunnerEntrypoint(
  payload: AgentRunnerEntrypointPayload,
  options: AgentRunnerEntrypointOptions = {}
): Promise<AgentRunResultPayload> {
  const config = parseAgentRuntimeConfig(payload.config ?? {}, {
    configPath: payload.config_path ?? null
  });
  const result = await runConfiguredAgentCommand({
    ...options,
    config,
    request: parseEntrypointRequest(payload.request),
    logsDir: parseRequiredString(payload.logs_dir, "logs_dir"),
    timeoutMs: payload.timeout_ms
  });
  return agentRunResultToDict(result, {
    includeHelpText: payload.include_help_text ?? true
  });
}

function parseEntrypointRequest(
  payload: AgentRunnerEntrypointPayload["request"]
): Omit<AgentRunRequest, "cliPath"> & { cliPath?: string | null } {
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
    throw new Error("request must be a JSON object");
  }
  const promptText = parseRequiredString(payload.prompt_text, "request.prompt_text");
  const repoRoot = parseRequiredString(payload.repo_root, "request.repo_root");
  const inputMode = payload.input_mode ?? "auto";
  if (!VALID_INPUT_MODES.has(inputMode)) {
    throw new Error(`Unsupported request.input_mode: ${String(inputMode)}`);
  }
  const extraArgs = payload.extra_args ?? [];
  if (!Array.isArray(extraArgs) || extraArgs.some((item) => typeof item !== "string")) {
    throw new Error("request.extra_args must be a JSON array of strings");
  }
  if (payload.prompt_flag !== undefined && payload.prompt_flag !== null) {
    parseRequiredString(payload.prompt_flag, "request.prompt_flag");
  }

  return {
    cliPath: payload.cli_path ?? null,
    promptText,
    repoRoot,
    workdir: payload.workdir ?? null,
    inputMode,
    promptFlag: payload.prompt_flag ?? null,
    extraArgs,
    runLabel: payload.run_label ?? null
  };
}

function parseRequiredString(value: unknown, fieldName: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`${fieldName} must be a non-empty string`);
  }
  return value;
}
