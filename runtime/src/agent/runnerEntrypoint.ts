import { readFile } from "node:fs/promises";

import type { AgentRunRequest, InputMode } from "./commandBuilder.js";
import {
  parseAgentRuntimeConfig,
  runConfiguredAgentCommand,
  type RunConfiguredAgentCommandOptions
} from "./configuredRunner.js";
import {
  normalizeManifestBackedAgentProfiles,
  type AgentManifestSearchRoot
} from "./manifests.js";
import {
  parseAgentsConfig,
  resolveRuntimeRoleProfile,
  type AgentProfile,
  type AgentsConfig
} from "./profiles.js";
import {
  agentRunResultToDict,
  type AgentRunResultPayload
} from "./runArtifacts.js";
import {
  discoverSkills,
  resolveRuntimeSkillResolution,
  type RuntimeSkillResolution,
  type SkillSearchRoot
} from "./skills.js";
import {
  buildPipelineRoleStageResult,
  type PipelineRoleStageKind
} from "../pipeline/roleStages.js";
import {
  pipelineRoleLoopDecision,
  pipelineRoleLoopTransition,
  type PipelineRetryRole
} from "../pipeline/roleLoops.js";
import { stageResultToDict, type StageResult } from "../results.js";

const VALID_INPUT_MODES = new Set(["auto", "file", "arg", "stdin", "positional"]);
const VALID_PIPELINE_STAGE_KINDS = new Set<string>([
  "tester",
  "reviewer",
  "committer",
  "plan_evaluator",
  "final_evaluator"
]);

export type PipelineStageEntrypointPayload = {
  kind: PipelineRoleStageKind;
  report_path?: string | null;
  attempt?: number | null;
  max_iterations?: number | null;
  artifacts?: readonly unknown[] | null;
  metadata?: Readonly<Record<string, unknown>> | null;
};

export type AgentRunnerEntrypointPayload = {
  config?: unknown;
  config_path?: string | null;
  role?: string | null;
  agents?: unknown;
  agent_manifest_search_roots?: AgentManifestSearchRoot[] | null;
  skill_search_roots?: SkillSearchRoot[] | null;
  pipeline_stage?: PipelineStageEntrypointPayload | null;
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
  event_stream?: boolean;
};

export type AgentRunnerEntrypointResultPayload = AgentRunResultPayload & {
  runtime_skills?: RuntimeSkillResolution;
  stage_result?: Record<string, unknown>;
  loop_decision?: Record<string, unknown>;
  loop_transition?: Record<string, unknown>;
};

export type AgentRunnerEntrypointOptions = Omit<
  RunConfiguredAgentCommandOptions,
  "config" | "request" | "logsDir" | "timeoutMs"
>;

export async function runAgentRunnerEntrypoint(
  payload: AgentRunnerEntrypointPayload,
  options: AgentRunnerEntrypointOptions = {}
): Promise<AgentRunnerEntrypointResultPayload> {
  const config = parseAgentRuntimeConfig(payload.config ?? {}, {
    configPath: payload.config_path ?? null
  });
  const agentsConfig = parseAgentsConfig(payload.agents, {
    configPath: payload.config_path ?? null
  });
  const pipelineStage = parsePipelineStagePayload(payload.pipeline_stage ?? null);
  const profile = await resolveEntrypointProfile(payload, agentsConfig);
  const result = await runConfiguredAgentCommand({
    ...options,
    config,
    profile,
    request: parseEntrypointRequest(payload.request),
    logsDir: parseRequiredString(payload.logs_dir, "logs_dir"),
    timeoutMs: payload.timeout_ms
  });
  const resultPayload: AgentRunnerEntrypointResultPayload = agentRunResultToDict(result, {
    includeHelpText: payload.include_help_text ?? true
  });
  const runtimeSkills = await resolveEntrypointRuntimeSkills(payload, profile);
  if (runtimeSkills !== null) {
    resultPayload.runtime_skills = runtimeSkills;
  }
  const stageResult = await resolveEntrypointStageResult(pipelineStage, result.stdoutPath);
  if (stageResult !== null) {
    resultPayload.stage_result = stageResultToDict(stageResult);
    const loopDecision = resolveEntrypointLoopDecision(pipelineStage, stageResult);
    if (loopDecision !== null) {
      resultPayload.loop_decision = loopDecision;
    }
    const loopTransition = resolveEntrypointLoopTransition(pipelineStage, stageResult);
    if (loopTransition !== null) {
      resultPayload.loop_transition = loopTransition;
    }
  }
  return resultPayload;
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

async function resolveEntrypointProfile(
  payload: AgentRunnerEntrypointPayload,
  agentsConfig: AgentsConfig | null
): Promise<AgentProfile | null> {
  if (payload.role === undefined || payload.role === null || !payload.role.trim()) {
    return null;
  }
  const manifestResolution = await normalizeManifestBackedAgentProfiles(
    payload.agent_manifest_search_roots ?? [],
    { agentsConfig }
  );
  return resolveRuntimeRoleProfile(payload.role, {
    agentsConfig,
    normalizedProfiles: manifestResolution.profiles
  });
}

async function resolveEntrypointRuntimeSkills(
  payload: AgentRunnerEntrypointPayload,
  profile: AgentProfile | null
): Promise<RuntimeSkillResolution | null> {
  if (profile === null || payload.role === undefined || payload.role === null || !payload.role.trim()) {
    return null;
  }
  if (!payload.skill_search_roots || payload.skill_search_roots.length === 0) {
    return null;
  }
  const discovery = await discoverSkills(payload.skill_search_roots, {
    ignoreInvalid: true
  });
  return resolveRuntimeSkillResolution(discovery, {
    role: payload.role,
    profile
  });
}

async function resolveEntrypointStageResult(
  stagePayload: PipelineStageEntrypointPayload | null,
  stdoutPath: string
): Promise<StageResult | null> {
  if (stagePayload === null) {
    return null;
  }
  const output = await readFile(stdoutPath, "utf8");
  return buildPipelineRoleStageResult({
    kind: stagePayload.kind,
    output,
    reportPath: stagePayload.report_path ?? null,
    artifacts: stagePayload.artifacts ?? [],
    attempt: stagePayload.attempt ?? null,
    metadata: stagePayload.metadata ?? {}
  });
}

function resolveEntrypointLoopDecision(
  stagePayload: PipelineStageEntrypointPayload | null,
  stage: StageResult
): Record<string, unknown> | null {
  if (
    stagePayload === null ||
    stagePayload.max_iterations === undefined ||
    stagePayload.max_iterations === null ||
    !isRetryRole(stagePayload.kind)
  ) {
    return null;
  }
  const attempt = stagePayload.attempt ?? 1;
  return pipelineRoleLoopDecision({
    role: stagePayload.kind,
    stage,
    iteration: Math.max(0, attempt - 1),
    maxIterations: stagePayload.max_iterations
  });
}

function resolveEntrypointLoopTransition(
  stagePayload: PipelineStageEntrypointPayload | null,
  stage: StageResult
): Record<string, unknown> | null {
  if (
    stagePayload === null ||
    stagePayload.max_iterations === undefined ||
    stagePayload.max_iterations === null ||
    !isRetryRole(stagePayload.kind)
  ) {
    return null;
  }
  const attempt = stagePayload.attempt ?? 1;
  return pipelineRoleLoopTransition({
    role: stagePayload.kind,
    stage,
    iteration: Math.max(0, attempt - 1),
    maxIterations: stagePayload.max_iterations
  });
}

function isRetryRole(kind: PipelineRoleStageKind): kind is PipelineRetryRole {
  return kind === "tester" || kind === "reviewer";
}

function parsePipelineStagePayload(
  payload: AgentRunnerEntrypointPayload["pipeline_stage"] | null
): PipelineStageEntrypointPayload | null {
  if (payload === null || payload === undefined) {
    return null;
  }
  if (typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("pipeline_stage must be a JSON object");
  }
  if (typeof payload.kind !== "string" || !VALID_PIPELINE_STAGE_KINDS.has(payload.kind)) {
    throw new Error(`Unsupported pipeline_stage.kind: ${String(payload.kind)}`);
  }
  if (payload.report_path !== undefined && payload.report_path !== null) {
    parseRequiredString(payload.report_path, "pipeline_stage.report_path");
  }
  if (
    payload.attempt !== undefined &&
    payload.attempt !== null &&
    (!Number.isInteger(payload.attempt) || payload.attempt < 0)
  ) {
    throw new Error("pipeline_stage.attempt must be a non-negative integer or null");
  }
  if (
    payload.max_iterations !== undefined &&
    payload.max_iterations !== null &&
    (!Number.isInteger(payload.max_iterations) || payload.max_iterations <= 0)
  ) {
    throw new Error("pipeline_stage.max_iterations must be a positive integer or null");
  }
  if (
    payload.artifacts !== undefined &&
    payload.artifacts !== null &&
    !Array.isArray(payload.artifacts)
  ) {
    throw new Error("pipeline_stage.artifacts must be a JSON array or null");
  }
  if (
    payload.metadata !== undefined &&
    payload.metadata !== null &&
    (typeof payload.metadata !== "object" || Array.isArray(payload.metadata))
  ) {
    throw new Error("pipeline_stage.metadata must be a JSON object or null");
  }
  return payload;
}

function parseRequiredString(value: unknown, fieldName: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error(`${fieldName} must be a non-empty string`);
  }
  return value;
}
