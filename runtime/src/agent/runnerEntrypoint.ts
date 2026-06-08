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
import {
  listGoalFiles,
  listGoalQueueCandidates,
  type GoalFileEntry,
  type GoalQueueCandidate
} from "../goals/discovery.js";
import {
  daemonPendingDecision,
  type DaemonPendingDecision
} from "../daemon/runner.js";
import {
  projectQueuedGoalPrompt,
  type GoalQueueProjection
} from "../goals/queue.js";
import {
  projectGoalsRoleDocument,
  type GoalsRoleDocumentProjection
} from "../goals/roleDocuments.js";
import {
  nextGoalsRoleStep,
  type GoalsPreludeRole,
  type GoalsRoleStep
} from "../goals/roleSequence.js";
import {
  goalsProcessDecision,
  goalsSingleGoalDecision,
  goalsTimerDecision,
  goalsTimerFiredDecision,
  goalsTriggerDecision,
  goalsWatcherStartDecision,
  goalsWatcherStopDecision,
  goalsWatchLoopDecision,
  type GoalsProcessDecision,
  type GoalsSingleGoalDecision,
  type GoalsTimerDecision,
  type GoalsTimerFiredDecision,
  type GoalsTriggerDecision,
  type GoalsWatcherStartDecision,
  type GoalsWatcherStopDecision,
  type GoalsWatchLoopDecision
} from "../goals/scheduler.js";
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

export type GoalsQueueEntrypointPayload = {
  entrypoint: "goals_queue";
  goals_path: string;
  prompt_path?: string | null;
  date_text?: string | null;
};

export type GoalsQueueEntrypointResultPayload = {
  entrypoint: "goals_queue";
  goal_files: GoalFileEntry[];
  candidates?: GoalQueueCandidate[];
};

export type GoalsPromptProjectionEntrypointPayload = {
  entrypoint: "goals_prompt_projection";
  goal_file_path: string;
  generated_prompt: string;
  date_text: string;
};

export type GoalsPromptProjectionEntrypointResultPayload = GoalQueueProjection & {
  entrypoint: "goals_prompt_projection";
};

export type GoalsRoleDocumentProjectionEntrypointPayload = {
  entrypoint: "goals_role_document_projection";
  logs_dir: string;
  date_text: string;
  role: string;
  stem: string;
  output: string;
};

export type GoalsRoleDocumentProjectionEntrypointResultPayload =
  GoalsRoleDocumentProjection & {
    entrypoint: "goals_role_document_projection";
  };

export type GoalsRoleSequenceEntrypointPayload = {
  entrypoint: "goals_role_sequence";
  goal_text: string;
  analysis_text?: string | null;
  plan_text?: string | null;
  design_text?: string | null;
  roles?: Partial<
    Record<GoalsPreludeRole, { cli?: string | null; model?: string | null }>
  > | null;
};

export type GoalsRoleSequenceEntrypointResultPayload = {
  entrypoint: "goals_role_sequence";
  next_step: GoalsRoleStep | null;
};

export type GoalsTimerDecisionEntrypointPayload = {
  entrypoint: "goals_timer_decision";
  has_goal_files: boolean;
  timer_active: boolean;
  interval_minutes: number;
};

export type GoalsTimerDecisionEntrypointResultPayload = GoalsTimerDecision & {
  entrypoint: "goals_timer_decision";
};

export type GoalsTriggerDecisionEntrypointPayload = {
  entrypoint: "goals_trigger_decision";
  stop_requested: boolean;
  has_goal_files: boolean;
};

export type GoalsTriggerDecisionEntrypointResultPayload =
  GoalsTriggerDecision & {
    entrypoint: "goals_trigger_decision";
  };

export type GoalsProcessDecisionEntrypointPayload = {
  entrypoint: "goals_process_decision";
  stop_requested: boolean;
  goal_file_count: number;
};

export type GoalsProcessDecisionEntrypointResultPayload =
  GoalsProcessDecision & {
    entrypoint: "goals_process_decision";
  };

export type GoalsTimerFiredDecisionEntrypointPayload = {
  entrypoint: "goals_timer_fired_decision";
  stop_requested: boolean;
};

export type GoalsTimerFiredDecisionEntrypointResultPayload =
  GoalsTimerFiredDecision & {
    entrypoint: "goals_timer_fired_decision";
  };

export type GoalsSingleGoalDecisionEntrypointPayload = {
  entrypoint: "goals_single_goal_decision";
  prompt_exists: boolean;
};

export type GoalsSingleGoalDecisionEntrypointResultPayload =
  GoalsSingleGoalDecision & {
    entrypoint: "goals_single_goal_decision";
  };

export type GoalsWatcherStartDecisionEntrypointPayload = {
  entrypoint: "goals_watcher_start_decision";
  watcher_active: boolean;
};

export type GoalsWatcherStartDecisionEntrypointResultPayload =
  GoalsWatcherStartDecision & {
    entrypoint: "goals_watcher_start_decision";
  };

export type GoalsWatcherStopDecisionEntrypointPayload = {
  entrypoint: "goals_watcher_stop_decision";
  timer_active: boolean;
};

export type GoalsWatcherStopDecisionEntrypointResultPayload =
  GoalsWatcherStopDecision & {
    entrypoint: "goals_watcher_stop_decision";
  };

export type GoalsWatchLoopDecisionEntrypointPayload = {
  entrypoint: "goals_watch_loop_decision";
  stop_requested: boolean;
  poll_seconds: number;
};

export type GoalsWatchLoopDecisionEntrypointResultPayload =
  GoalsWatchLoopDecision & {
    entrypoint: "goals_watch_loop_decision";
  };

export type DaemonPendingDecisionEntrypointPayload = {
  entrypoint: "daemon_pending_decision";
  processed_count: number;
  ready_prompt_paths: string[];
  retry_after_seconds?: number | null;
};

export type DaemonPendingDecisionEntrypointResultPayload =
  DaemonPendingDecision & {
    entrypoint: "daemon_pending_decision";
  };

export type RunnerCliPayload =
  | AgentRunnerEntrypointPayload
  | DaemonPendingDecisionEntrypointPayload
  | GoalsQueueEntrypointPayload
  | GoalsPromptProjectionEntrypointPayload
  | GoalsRoleDocumentProjectionEntrypointPayload
  | GoalsRoleSequenceEntrypointPayload
  | GoalsTimerDecisionEntrypointPayload
  | GoalsTriggerDecisionEntrypointPayload
  | GoalsProcessDecisionEntrypointPayload
  | GoalsTimerFiredDecisionEntrypointPayload
  | GoalsSingleGoalDecisionEntrypointPayload
  | GoalsWatcherStartDecisionEntrypointPayload
  | GoalsWatcherStopDecisionEntrypointPayload
  | GoalsWatchLoopDecisionEntrypointPayload;
export type RunnerCliResultPayload =
  | AgentRunnerEntrypointResultPayload
  | DaemonPendingDecisionEntrypointResultPayload
  | GoalsQueueEntrypointResultPayload
  | GoalsPromptProjectionEntrypointResultPayload
  | GoalsRoleDocumentProjectionEntrypointResultPayload
  | GoalsRoleSequenceEntrypointResultPayload
  | GoalsTimerDecisionEntrypointResultPayload
  | GoalsTriggerDecisionEntrypointResultPayload
  | GoalsProcessDecisionEntrypointResultPayload
  | GoalsTimerFiredDecisionEntrypointResultPayload
  | GoalsSingleGoalDecisionEntrypointResultPayload
  | GoalsWatcherStartDecisionEntrypointResultPayload
  | GoalsWatcherStopDecisionEntrypointResultPayload
  | GoalsWatchLoopDecisionEntrypointResultPayload;

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

export function runDaemonPendingDecisionEntrypoint(
  payload: DaemonPendingDecisionEntrypointPayload
): DaemonPendingDecisionEntrypointResultPayload {
  return {
    entrypoint: "daemon_pending_decision",
    ...daemonPendingDecision({
      processedCount: parseNumber(payload.processed_count, "processed_count"),
      readyPromptPaths: parseStringArray(
        payload.ready_prompt_paths,
        "ready_prompt_paths"
      ),
      retryAfterSeconds: parseOptionalNumber(
        payload.retry_after_seconds ?? null,
        "retry_after_seconds"
      )
    })
  };
}

export async function runGoalsQueueEntrypoint(
  payload: GoalsQueueEntrypointPayload
): Promise<GoalsQueueEntrypointResultPayload> {
  const goalsPath = parseRequiredString(payload.goals_path, "goals_path");
  const promptPath = payload.prompt_path ?? null;
  const dateText = payload.date_text ?? null;
  const goalFiles = await listGoalFiles(goalsPath);
  const result: GoalsQueueEntrypointResultPayload = {
    entrypoint: "goals_queue",
    goal_files: goalFiles
  };
  if (promptPath !== null && dateText !== null) {
    result.candidates = await listGoalQueueCandidates(goalsPath, promptPath, dateText);
  }
  return result;
}

export function runGoalsPromptProjectionEntrypoint(
  payload: GoalsPromptProjectionEntrypointPayload
): GoalsPromptProjectionEntrypointResultPayload {
  return {
    entrypoint: "goals_prompt_projection",
    ...projectQueuedGoalPrompt({
      goalFilePath: parseRequiredString(payload.goal_file_path, "goal_file_path"),
      generatedPrompt: parseRequiredString(payload.generated_prompt, "generated_prompt"),
      dateText: parseRequiredString(payload.date_text, "date_text")
    })
  };
}

export function runGoalsRoleDocumentProjectionEntrypoint(
  payload: GoalsRoleDocumentProjectionEntrypointPayload
): GoalsRoleDocumentProjectionEntrypointResultPayload {
  return {
    entrypoint: "goals_role_document_projection",
    ...projectGoalsRoleDocument({
      logsDir: parseRequiredString(payload.logs_dir, "logs_dir"),
      dateText: parseRequiredString(payload.date_text, "date_text"),
      role: parseRequiredString(payload.role, "role"),
      stem: parseRequiredString(payload.stem, "stem"),
      output: parseString(payload.output, "output")
    })
  };
}

export function runGoalsRoleSequenceEntrypoint(
  payload: GoalsRoleSequenceEntrypointPayload
): GoalsRoleSequenceEntrypointResultPayload {
  return {
    entrypoint: "goals_role_sequence",
    next_step: nextGoalsRoleStep({
      goalText: parseRequiredString(payload.goal_text, "goal_text"),
      analysisText: parseOptionalString(payload.analysis_text, "analysis_text"),
      planText: parseOptionalString(payload.plan_text, "plan_text"),
      designText: parseOptionalString(payload.design_text, "design_text"),
      roles: parseGoalsRoleAvailability(payload.roles ?? null)
    })
  };
}

export function runGoalsTimerDecisionEntrypoint(
  payload: GoalsTimerDecisionEntrypointPayload
): GoalsTimerDecisionEntrypointResultPayload {
  return {
    entrypoint: "goals_timer_decision",
    ...goalsTimerDecision({
      hasGoalFiles: parseBoolean(payload.has_goal_files, "has_goal_files"),
      timerActive: parseBoolean(payload.timer_active, "timer_active"),
      intervalMinutes: parseNumber(payload.interval_minutes, "interval_minutes")
    })
  };
}

export function runGoalsTriggerDecisionEntrypoint(
  payload: GoalsTriggerDecisionEntrypointPayload
): GoalsTriggerDecisionEntrypointResultPayload {
  return {
    entrypoint: "goals_trigger_decision",
    ...goalsTriggerDecision({
      stopRequested: parseBoolean(payload.stop_requested, "stop_requested"),
      hasGoalFiles: parseBoolean(payload.has_goal_files, "has_goal_files")
    })
  };
}

export function runGoalsProcessDecisionEntrypoint(
  payload: GoalsProcessDecisionEntrypointPayload
): GoalsProcessDecisionEntrypointResultPayload {
  return {
    entrypoint: "goals_process_decision",
    ...goalsProcessDecision({
      stopRequested: parseBoolean(payload.stop_requested, "stop_requested"),
      goalFileCount: parseNumber(payload.goal_file_count, "goal_file_count")
    })
  };
}

export function runGoalsTimerFiredDecisionEntrypoint(
  payload: GoalsTimerFiredDecisionEntrypointPayload
): GoalsTimerFiredDecisionEntrypointResultPayload {
  return {
    entrypoint: "goals_timer_fired_decision",
    ...goalsTimerFiredDecision({
      stopRequested: parseBoolean(payload.stop_requested, "stop_requested")
    })
  };
}

export function runGoalsSingleGoalDecisionEntrypoint(
  payload: GoalsSingleGoalDecisionEntrypointPayload
): GoalsSingleGoalDecisionEntrypointResultPayload {
  return {
    entrypoint: "goals_single_goal_decision",
    ...goalsSingleGoalDecision({
      promptExists: parseBoolean(payload.prompt_exists, "prompt_exists")
    })
  };
}

export function runGoalsWatcherStartDecisionEntrypoint(
  payload: GoalsWatcherStartDecisionEntrypointPayload
): GoalsWatcherStartDecisionEntrypointResultPayload {
  return {
    entrypoint: "goals_watcher_start_decision",
    ...goalsWatcherStartDecision({
      watcherActive: parseBoolean(payload.watcher_active, "watcher_active")
    })
  };
}

export function runGoalsWatcherStopDecisionEntrypoint(
  payload: GoalsWatcherStopDecisionEntrypointPayload
): GoalsWatcherStopDecisionEntrypointResultPayload {
  return {
    entrypoint: "goals_watcher_stop_decision",
    ...goalsWatcherStopDecision({
      timerActive: parseBoolean(payload.timer_active, "timer_active")
    })
  };
}

export function runGoalsWatchLoopDecisionEntrypoint(
  payload: GoalsWatchLoopDecisionEntrypointPayload
): GoalsWatchLoopDecisionEntrypointResultPayload {
  return {
    entrypoint: "goals_watch_loop_decision",
    ...goalsWatchLoopDecision({
      stopRequested: parseBoolean(payload.stop_requested, "stop_requested"),
      pollSeconds: parseNumber(payload.poll_seconds, "poll_seconds")
    })
  };
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

function parseString(value: unknown, fieldName: string): string {
  if (typeof value !== "string") {
    throw new Error(`${fieldName} must be a string`);
  }
  return value;
}

function parseBoolean(value: unknown, fieldName: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`${fieldName} must be a boolean`);
  }
  return value;
}

function parseNumber(value: unknown, fieldName: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${fieldName} must be a finite number`);
  }
  return value;
}

function parseOptionalNumber(value: unknown, fieldName: string): number | null {
  if (value === null || value === undefined) {
    return null;
  }
  return parseNumber(value, fieldName);
}

function parseStringArray(value: unknown, fieldName: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new Error(`${fieldName} must be a JSON array of strings`);
  }
  return value;
}

function parseOptionalString(
  value: unknown,
  fieldName: string
): string | null | undefined {
  if (value === undefined) {
    return undefined;
  }
  if (value === null) {
    return null;
  }
  if (typeof value !== "string") {
    throw new Error(`${fieldName} must be a string or null`);
  }
  return value;
}

function parseGoalsRoleAvailability(
  value: unknown
): GoalsRoleSequenceEntrypointPayload["roles"] {
  if (value === null || value === undefined) {
    return null;
  }
  if (typeof value !== "object" || Array.isArray(value)) {
    throw new Error("roles must be a JSON object or null");
  }
  const roles: GoalsRoleSequenceEntrypointPayload["roles"] = {};
  for (const role of ["analyzer", "planner", "designer"] as const) {
    const item = (value as Record<string, unknown>)[role];
    if (item === undefined || item === null) {
      continue;
    }
    if (typeof item !== "object" || Array.isArray(item)) {
      throw new Error(`roles.${role} must be a JSON object or null`);
    }
    const rolePayload = item as Record<string, unknown>;
    roles[role] = {
      cli: parseOptionalString(rolePayload.cli, `roles.${role}.cli`) ?? null,
      model: parseOptionalString(rolePayload.model, `roles.${role}.model`) ?? null
    };
  }
  return roles;
}
