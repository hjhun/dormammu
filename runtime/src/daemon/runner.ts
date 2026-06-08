import type { RequestClass } from "../workflowPolicy.js";

export type DaemonPendingDecisionAction = "idle" | "wait" | "process";

export type DaemonPendingDecisionInput = {
  processedCount: number;
  readyPromptPaths: readonly string[];
  retryAfterSeconds: number | null;
};

export type DaemonPendingDecision = {
  action: DaemonPendingDecisionAction;
  promptPath: string | null;
  queuedPromptNames: string[];
  retryAfterSeconds: number | null;
  reason: string;
};

export type DaemonPromptRouteAction =
  | "configured_pipeline"
  | "direct_pipeline"
  | "planning_pipeline"
  | "prelude_then_loop";

export type DaemonPromptRouteInput = {
  hasAgentsConfig: boolean;
  requestClass: RequestClass;
  hasGoalFile: boolean;
};

export type DaemonPromptRouteDecision = {
  action: DaemonPromptRouteAction;
  runner: "pipeline" | "loop";
  requiresAgentCli: boolean;
  runRefineAndPlanPrelude: boolean;
  enablePlanEvaluator: boolean;
  useGoalsEvaluatorConfig: boolean;
  reason: string;
};

export type DaemonPromptLifecycleAction = "process" | "skip";

export type DaemonPromptLifecycleStatus = "processing" | "skipped";

export type DaemonPromptLifecycleDecisionInput = {
  promptPath: string;
  resultPath: string;
  promptExists: boolean;
};

export type DaemonPromptLifecycleDecision = {
  action: DaemonPromptLifecycleAction;
  status: DaemonPromptLifecycleStatus;
  promptPath: string;
  resultPath: string;
  removeExistingResult: boolean;
  errorMessage: string | null;
  reason: string;
};

export type DaemonPromptPathDecisionInput = {
  promptPath: string;
  resultPathRoot: string;
};

export type DaemonPromptPathDecision = {
  promptStem: string;
  resultPath: string;
  progressLogPath: string;
  reason: string;
};

export type DaemonResultReportAction = "publish" | "skip";

export type DaemonResultReportDecisionInput = {
  promptPath: string;
  resultPath: string;
  promptExists: boolean;
  daemonRunId: string | null;
  latestRunId: string | null;
  sessionId: string | null;
};

export type DaemonResultReportDecision = {
  action: DaemonResultReportAction;
  writeReport: boolean;
  removePrompt: boolean;
  promptPath: string;
  resultPath: string;
  artifactKind: "result_report";
  artifactLabel: "result_report";
  contentType: "text/markdown";
  runId: string | null;
  role: "daemon";
  stageName: "daemon";
  sessionId: string | null;
  reason: string;
};

export type DaemonResultReportFallbackDecisionInput = {
  promptName: string;
  existingError: string | null;
  cause: string;
};

export type DaemonResultReportFallbackDecision = {
  logMessage: string;
  fallbackNote: string;
  combinedError: string;
  reason: "result_report_authoring_failed";
};

export type DaemonResultMarkdownProjectionInput = {
  result: Readonly<Record<string, unknown>>;
  generatedAt: string;
};

export type DaemonResultMarkdownProjection = {
  markdown: string;
  reason: "result_markdown_projected";
};

export type DaemonResultReportAuthoringAction =
  | "fallback_markdown"
  | "run_configured_cli";

export type DaemonResultReportAuthoringDecisionInput = {
  result: Readonly<Record<string, unknown>>;
  generatedAt: string;
  runtimePathsText: string;
  cliPath: string | null;
  repoRoot: string;
};

export type DaemonResultReportAuthoringDecision = {
  action: DaemonResultReportAuthoringAction;
  promptText: string | null;
  cliPath: string | null;
  repoRoot: string;
  workdir: string;
  runLabel: string | null;
  generatedAt: string;
  reason:
    | "active_agent_cli_missing"
    | "configured_cli_authoring_requested";
};

export type DaemonResultReportAuthoredOutputAction = "accept" | "error";

export type DaemonResultReportAuthoredOutputDecisionInput = {
  stdoutText: string | null;
  stderrText: string | null;
  generatedAt: string;
  promptName: string;
};

export type DaemonResultReportAuthoredOutputDecision = {
  action: DaemonResultReportAuthoredOutputAction;
  authoredMarkdown: string | null;
  errorMessage: string | null;
  reason:
    | "authored_output_accepted"
    | "authored_output_empty"
    | "authored_output_missing_generated_at";
};

export type DaemonPlanStateDecisionInput = {
  requestClass: string;
  taskSync: Readonly<Record<string, unknown>> | null;
};

export type DaemonPlanStateDecision = {
  planAllCompleted: boolean | null;
  nextPendingTask: string | null;
  reason:
    | "direct_response_plan_complete"
    | "task_sync_missing"
    | "task_sync_normalized";
};

export type DaemonArtifactWriterDecisionInput = {
  baseDir: string;
  logsDir: string | null;
  runId: string | null;
  sessionId: string | null;
};

export type DaemonArtifactWriterDecision = {
  baseDir: string;
  logsDir: string | null;
  runId: string | null;
  role: "daemon";
  stageName: "daemon";
  sessionId: string | null;
  reason: "daemon_artifact_writer_bound";
};

export type DaemonArtifactPersistedEventDecisionInput = {
  artifactKind: string;
};

export type DaemonArtifactPersistedEventDecision = {
  eventType: "artifact_persisted";
  role: "daemon";
  stage: "daemon";
  status: "persisted";
  artifactKind: string;
  summary: string;
  reason:
    | "input_prompt_artifact_persisted"
    | "result_report_artifact_persisted"
    | "daemon_artifact_persisted";
};

export type DaemonSupervisorHandoffDecisionInput = {
  fromRole: string;
  toRole: string;
  attempt: number;
};

export type DaemonSupervisorHandoffDecision = {
  eventType: "supervisor.handoff";
  role: string;
  stage: string;
  status: "handoff";
  payload: {
    fromRole: string;
    toRole: string;
    reason: string;
    attempt: number;
  };
  reason: "daemon_supervisor_prelude_handoff";
};

export type DaemonRunLifecycleEventKind = "requested" | "started";

export type DaemonRunLifecycleEventDecisionInput = {
  eventKind: DaemonRunLifecycleEventKind;
  promptSummary: string | null;
};

export type DaemonRunLifecycleEventDecision = {
  eventType: "run.requested" | "run.started";
  role: "daemon";
  stage: "daemon";
  status: DaemonRunLifecycleEventKind;
  payload: {
    source: "daemon_runner";
    entrypoint: "DaemonRunner._process_prompt";
    trigger: "daemon_queue";
    promptSummary: string | null;
  };
  reason: "daemon_run_requested" | "daemon_run_started";
};

export type DaemonResultArtifactRefAction = "reference" | "skip";

export type DaemonResultArtifactRefDecisionInput = {
  resultPath: string;
  resultExists: boolean;
  createdAt: string | null;
  daemonRunId: string | null;
  latestRunId: string | null;
  sessionId: string | null;
};

export type DaemonResultArtifactRefDecision = {
  action: DaemonResultArtifactRefAction;
  artifactRef: {
    kind: "result_report";
    path: string;
    label: "result_report";
    contentType: "text/markdown";
    createdAt: string | null;
    runId: string | null;
    role: "daemon";
    stageName: "daemon";
    sessionId: string | null;
  } | null;
  reason: string;
};

export type DaemonRunFinishedDecisionInput = {
  attemptsCompleted: number | null;
  retriesUsed: number | null;
  supervisorVerdict: string | null;
  outcome: string;
  error: string | null;
};

export type DaemonRunFinishedDecision = {
  eventType: "run.finished";
  role: "daemon";
  stage: "daemon";
  status: string;
  source: "daemon_runner";
  runEntrypoint: "DaemonRunner._process_prompt";
  attemptsCompleted: number | null;
  retriesUsed: number | null;
  supervisorVerdict: string | null;
  outcome: string;
  error: string | null;
  reason: string;
};

export type DaemonRoadmapPhaseDecisionInput = {
  activePhaseIds: readonly unknown[];
};

export type DaemonRoadmapPhaseDecision = {
  expectedRoadmapPhaseId: string;
  reason: string;
};

export type DaemonGoalSourceDecisionInput = {
  promptText: string;
};

export type DaemonGoalSourceDecision = {
  goalSourcePath: string | null;
  reason: "goal_source_found" | "goal_source_missing";
};

export type DaemonAgentCliAction = "use" | "error";

export type DaemonAgentCliDecisionInput = {
  activeAgentCli: string | null;
};

export type DaemonAgentCliDecision = {
  action: DaemonAgentCliAction;
  agentCli: string | null;
  errorMessage: string | null;
  reason: "active_agent_cli_configured" | "active_agent_cli_missing";
};

export type DaemonTerminalErrorDecisionInput = {
  status: string;
  nextPendingTask: string | null;
};

export type DaemonTerminalErrorDecision = {
  status: string;
  nextPendingTask: string | null;
  message: string;
  reason: string;
};

export type DaemonTerminalStatusDecisionInput = {
  status: string;
  planAllCompleted: boolean | null;
  hasCleanTerminalStageEvidence: boolean;
  nextPendingTask: string | null;
};

export type DaemonTerminalStatusDecision = {
  status: string;
  error: string | null;
  preserveCompleted: boolean;
  reason: string;
};

export type DaemonResultStatusDecisionInput = {
  resultText: string;
};

export type DaemonResultStatusDecision = {
  status: string | null;
  reason: string;
};

export type DaemonExistingResultAction = "remove" | "keep";

export type DaemonExistingResultDecisionInput = {
  promptPath: string;
  resultPath: string;
  resultExists: boolean;
  existingResultStatus: string | null;
};

export type DaemonExistingResultDecision = {
  action: DaemonExistingResultAction;
  removeExistingResult: boolean;
  promptPath: string;
  resultPath: string;
  existingResultStatus: string | null;
  reason: string;
};

export type DaemonPromptSettleAction = "ready" | "defer";

export type DaemonPromptSettleDecisionInput = {
  promptPath: string;
  settleSeconds: number;
  ageSeconds: number;
};

export type DaemonPromptSettleDecision = {
  action: DaemonPromptSettleAction;
  promptPath: string;
  retryAfterSeconds: number | null;
  reason: string;
};

export type DaemonQueueFileAction = "inspect" | "skip";

export type DaemonQueueFileDecisionInput = {
  promptPath: string;
  inProgress: boolean;
  promptCandidate: boolean;
};

export type DaemonQueueFileDecision = {
  action: DaemonQueueFileAction;
  promptPath: string;
  reason: string;
};

export type DaemonLoopIterationAction = "continue" | "wait" | "stop";

export type DaemonLoopIterationInput = {
  processedCount: number;
  inProgressCount: number;
  shutdownRequested: boolean;
};

export type DaemonLoopIterationDecision = {
  action: DaemonLoopIterationAction;
  heartbeatStatus: "busy" | "idle";
  waitForChanges: boolean;
  reason: string;
};

export type DaemonStartupDecisionInput = {
  goalsSchedulerConfigured: boolean;
  autonomousSchedulerConfigured: boolean;
};

export type DaemonStartupDecision = {
  action: "start";
  initialHeartbeatStatus: "idle";
  startGoalsScheduler: boolean;
  triggerGoalsScheduler: boolean;
  startAutonomousScheduler: boolean;
  triggerAutonomousScheduler: boolean;
  reason: string;
};

export type DaemonStartupBannerDecisionInput = {
  repoRoot: string;
  configPath: string;
  promptPath: string;
  resultPath: string;
  watcherBackend: string;
  requestedWatcherBackend: string;
  pollIntervalSeconds: number;
  settleSeconds: number;
  ignoreHiddenFiles: boolean;
  allowedExtensions: readonly string[];
  goalsPath: string | null;
  goalsIntervalMinutes: number | null;
  autonomousEnabled: boolean;
  autonomousIntervalMinutes: number | null;
  autonomousFocus: string | null;
  autonomousMaxQueuedTasks: number | null;
};

export type DaemonStartupBannerDecision = {
  allowedExtensionsDescription: string;
  lines: string[];
  reason: string;
};

export type DaemonShutdownDecisionInput = {
  goalsSchedulerConfigured: boolean;
  autonomousSchedulerConfigured: boolean;
  progressLogActive: boolean;
};

export type DaemonShutdownDecision = {
  action: "shutdown";
  stopGoalsScheduler: boolean;
  stopAutonomousScheduler: boolean;
  closeWatcher: boolean;
  removeHeartbeat: boolean;
  closeProgressLog: boolean;
  reason: string;
};

export type DaemonInstanceLockAction = "skip" | "hold" | "reject";

export type DaemonInstanceLockDecisionInput = {
  fcntlAvailable: boolean;
  lockAcquired: boolean;
  promptPath: string;
  existingPid: string | null;
};

export type DaemonInstanceLockDecision = {
  action: DaemonInstanceLockAction;
  writePidFile: boolean;
  errorMessage: string | null;
  reason: string;
};

export type DaemonInstanceUnlockAction = "skip" | "release";

export type DaemonInstanceUnlockDecisionInput = {
  fcntlAvailable: boolean;
  lockHeld: boolean;
};

export type DaemonInstanceUnlockDecision = {
  action: DaemonInstanceUnlockAction;
  unlockFcntl: boolean;
  closeLockFile: boolean;
  clearPidLockFile: boolean;
  removePidFile: boolean;
  reason: string;
};

export type DaemonHeartbeatStatus = "busy" | "idle";

export type DaemonHeartbeatWriteAction = "skip" | "write";

export type DaemonHeartbeatWriteDecisionInput = {
  heartbeatPathConfigured: boolean;
  pid: number;
  status: DaemonHeartbeatStatus;
  timestamp: string;
};

export type DaemonHeartbeatPayload = {
  pid: number;
  status: DaemonHeartbeatStatus;
  ts: string;
};

export type DaemonHeartbeatWriteDecision = {
  action: DaemonHeartbeatWriteAction;
  ensureParent: boolean;
  heartbeatPayload: DaemonHeartbeatPayload | null;
  reason: string;
};

export type DaemonHeartbeatRemoveAction = "skip" | "remove";

export type DaemonHeartbeatRemoveDecisionInput = {
  heartbeatPathConfigured: boolean;
};

export type DaemonHeartbeatRemoveDecision = {
  action: DaemonHeartbeatRemoveAction;
  removeHeartbeat: boolean;
  reason: string;
};

export type DaemonWatcherBackend = "auto" | "inotify" | "polling";

export type DaemonWatcherBackendDecisionAction = "error" | "use";

export type DaemonWatcherBackendDecisionInput = {
  requestedBackend: DaemonWatcherBackend;
  inotifyAvailable: boolean;
};

export type DaemonWatcherBackendDecision = {
  action: DaemonWatcherBackendDecisionAction;
  backend: "inotify" | "polling" | null;
  errorMessage: string | null;
  reason: string;
};

export type DaemonWatcherWaitAction = "skip" | "wait";

export type DaemonWatcherWaitDecisionInput = {
  waitRequested: boolean;
  shutdownRequested: boolean;
  watcherBackend: string;
};

export type DaemonWatcherWaitDecision = {
  action: DaemonWatcherWaitAction;
  waitForChanges: boolean;
  watcherBackend: string;
  reason: string;
};

export function daemonPendingDecision(
  input: DaemonPendingDecisionInput
): DaemonPendingDecision {
  const readyPromptPaths = input.readyPromptPaths.filter(
    (path) => path.length > 0
  );
  const processedCount = Math.max(0, Math.trunc(input.processedCount));
  if (readyPromptPaths.length === 0) {
    if (processedCount === 0 && input.retryAfterSeconds !== null) {
      return {
        action: "wait",
        promptPath: null,
        queuedPromptNames: [],
        retryAfterSeconds: Math.max(0, input.retryAfterSeconds),
        reason: "settle_window_pending"
      };
    }
    return {
      action: "idle",
      promptPath: null,
      queuedPromptNames: [],
      retryAfterSeconds: null,
      reason: "no_ready_prompts"
    };
  }
  return {
    action: "process",
    promptPath: readyPromptPaths[0],
    queuedPromptNames: readyPromptPaths.slice(1).map((path) => basename(path)),
    retryAfterSeconds: null,
    reason: "ready_prompt_available"
  };
}

export function daemonPromptRouteDecision(
  input: DaemonPromptRouteInput
): DaemonPromptRouteDecision {
  if (input.hasAgentsConfig) {
    return {
      action: "configured_pipeline",
      runner: "pipeline",
      requiresAgentCli: false,
      runRefineAndPlanPrelude: false,
      enablePlanEvaluator: false,
      useGoalsEvaluatorConfig: input.hasGoalFile,
      reason: "agents_config_present"
    };
  }

  if (input.requestClass === "direct_response") {
    return {
      action: "direct_pipeline",
      runner: "pipeline",
      requiresAgentCli: false,
      runRefineAndPlanPrelude: false,
      enablePlanEvaluator: false,
      useGoalsEvaluatorConfig: false,
      reason: "direct_response_fast_path"
    };
  }

  if (input.requestClass === "planning_only") {
    return {
      action: "planning_pipeline",
      runner: "pipeline",
      requiresAgentCli: true,
      runRefineAndPlanPrelude: false,
      enablePlanEvaluator: false,
      useGoalsEvaluatorConfig: false,
      reason: "planning_only_pipeline"
    };
  }

  return {
    action: "prelude_then_loop",
    runner: "loop",
    requiresAgentCli: true,
    runRefineAndPlanPrelude: true,
    enablePlanEvaluator: input.hasGoalFile,
    useGoalsEvaluatorConfig: false,
    reason: `${input.requestClass}_requires_supervised_loop`
  };
}

export function daemonPromptLifecycleDecision(
  input: DaemonPromptLifecycleDecisionInput
): DaemonPromptLifecycleDecision {
  if (!input.promptExists) {
    return {
      action: "skip",
      status: "skipped",
      promptPath: input.promptPath,
      resultPath: input.resultPath,
      removeExistingResult: false,
      errorMessage: "Prompt file was deleted before processing.",
      reason: "prompt_missing"
    };
  }

  return {
    action: "process",
    status: "processing",
    promptPath: input.promptPath,
    resultPath: input.resultPath,
    removeExistingResult: true,
    errorMessage: null,
    reason: "prompt_ready"
  };
}

export function daemonPromptPathDecision(
  input: DaemonPromptPathDecisionInput
): DaemonPromptPathDecision {
  const promptStem = stem(input.promptPath);
  const resultPath = joinPath(input.resultPathRoot, `${promptStem}_RESULT.md`);
  return {
    promptStem,
    resultPath,
    progressLogPath: joinPath(dirname(input.resultPathRoot), "progress", `${promptStem}_progress.log`),
    reason: "prompt_paths_projected"
  };
}

export function daemonResultReportDecision(
  input: DaemonResultReportDecisionInput
): DaemonResultReportDecision {
  const runId = nonEmpty(input.daemonRunId) ?? nonEmpty(input.latestRunId);

  return {
    action: "publish",
    writeReport: true,
    removePrompt: input.promptExists,
    promptPath: input.promptPath,
    resultPath: input.resultPath,
    artifactKind: "result_report",
    artifactLabel: "result_report",
    contentType: "text/markdown",
    runId,
    role: "daemon",
    stageName: "daemon",
    sessionId: nonEmpty(input.sessionId),
    reason: input.promptExists ? "publish_and_remove_prompt" : "publish_without_prompt"
  };
}

export function daemonResultReportFallbackDecision(
  input: DaemonResultReportFallbackDecisionInput
): DaemonResultReportFallbackDecision {
  const fallbackNote = [
    "Configured CLI result report authoring failed; ",
    `wrote fallback report instead. Cause: ${input.cause}`
  ].join("");
  return {
    logMessage: [
      "daemon result report fallback: configured CLI authoring failed for ",
      `${input.promptName}: ${input.cause}`
    ].join(""),
    fallbackNote,
    combinedError:
      input.existingError !== null && input.existingError.length > 0
        ? `${input.existingError}\n\n${fallbackNote}`
        : fallbackNote,
    reason: "result_report_authoring_failed"
  };
}

export function daemonResultMarkdownProjection(
  input: DaemonResultMarkdownProjectionInput
): DaemonResultMarkdownProjection {
  const result = input.result;
  const lines = [
    `# Result: ${basename(requiredText(result.prompt_path))}`,
    "",
    "## Summary",
    "",
    `- Generated at: \`${input.generatedAt}\``,
    `- Status: \`${displayValue(result.status)}\``,
    `- Prompt path: \`${requiredText(result.prompt_path)}\``,
    `- Result path: \`${requiredText(result.result_path)}\``,
    `- Session id: \`${optionalText(result.session_id) ?? "unknown"}\``,
    `- Watcher backend: \`${requiredText(result.watcher_backend)}\``,
    `- Started at: \`${requiredText(result.started_at)}\``,
    `- Completed at: \`${optionalText(result.completed_at) ?? "not completed"}\``,
    `- Queue sort key: \`${tupleDisplay(result.sort_key)}\``
  ];

  if (displayValue(result.status) === "in_progress") {
    lines.push("- Processing state: `active`");
  }
  if (
    result.plan_all_completed !== null &&
    result.plan_all_completed !== undefined
  ) {
    lines.push(
      `- PLAN complete: \`${result.plan_all_completed === true ? "yes" : "no"}\``
    );
  }
  const nextPendingTask = optionalText(result.next_pending_task);
  if (nextPendingTask !== null) {
    lines.push(`- Next pending PLAN task: \`${nextPendingTask}\``);
  }
  if (
    result.attempts_completed !== null &&
    result.attempts_completed !== undefined
  ) {
    lines.push(`- Attempts completed: \`${String(result.attempts_completed)}\``);
  }
  const latestRunId = optionalText(result.latest_run_id);
  if (latestRunId !== null) {
    lines.push(`- Latest run id: \`${latestRunId}\``);
  }
  const supervisorVerdict = optionalText(result.supervisor_verdict);
  if (supervisorVerdict !== null) {
    lines.push(`- Supervisor verdict: \`${supervisorVerdict}\``);
  }
  const summary = optionalText(result.summary);
  if (summary !== null) {
    lines.push(`- Run summary: ${summary}`);
  }
  const supervisorReportPath = optionalText(result.supervisor_report_path);
  if (supervisorReportPath !== null) {
    lines.push(`- Supervisor report: \`${supervisorReportPath}\``);
  }
  const continuationPromptPath = optionalText(result.continuation_prompt_path);
  if (continuationPromptPath !== null) {
    lines.push(`- Continuation prompt: \`${continuationPromptPath}\``);
  }
  const error = optionalText(result.error);
  if (error !== null) {
    lines.push("", "## Error", "", error);
  }

  const stageResults = arrayOfRecords(result.stage_results);
  if (stageResults.length > 0) {
    lines.push("", "## Stage Results", "");
    for (const stageResult of stageResults) {
      lines.push(`### ${optionalText(stageResult.stage_name) ?? requiredText(stageResult.role)}`);
      lines.push("");
      lines.push(`- Role: \`${requiredText(stageResult.role)}\``);
      lines.push(`- Status: \`${displayValue(stageResult.status)}\``);
      lines.push(
        `- Verdict: \`${optionalText(stageResult.verdict) ?? "n/a"}\``
      );
      lines.push(`- Report: \`${optionalText(stageResult.report_path) ?? "n/a"}\``);
      const stageSummary = optionalText(stageResult.summary);
      if (stageSummary !== null) {
        lines.push(`- Summary: ${stageSummary}`);
      }
      const retry = recordOrNull(stageResult.retry);
      if (retry !== null) {
        lines.push(
          [
            "- Retry: `",
            `attempt=${valueOrNullText(retry.attempt)}, `,
            `retries_used=${valueOrNullText(retry.retries_used)}, `,
            `max_retries=${valueOrNullText(retry.max_retries)}, `,
            `max_iterations=${valueOrNullText(retry.max_iterations)}`,
            "`"
          ].join("")
        );
      }
      const timing = recordOrNull(stageResult.timing);
      if (timing !== null) {
        lines.push(
          [
            "- Timing: `",
            `started_at=${optionalText(timing.started_at) ?? "n/a"}, `,
            `completed_at=${optionalText(timing.completed_at) ?? "n/a"}, `,
            "duration_seconds=",
            timing.duration_seconds !== null && timing.duration_seconds !== undefined
              ? String(timing.duration_seconds)
              : "n/a",
            "`"
          ].join("")
        );
      }
      lines.push("");
    }
  }

  const artifacts = arrayOfRecords(result.artifacts);
  if (artifacts.length > 0) {
    lines.push("", "## Artifacts", "");
    for (const artifact of artifacts) {
      const label = optionalText(artifact.label);
      lines.push(
        `- \`${requiredText(artifact.kind)}\`: \`${requiredText(artifact.path)}\`` +
          (label !== null ? ` (${label})` : "")
      );
    }
  }

  const phaseResults = arrayOfRecords(result.phase_results);
  if (phaseResults.length > 0) {
    lines.push("", "## Phases", "");
    for (const phaseResult of phaseResults) {
      lines.push(`### ${requiredText(phaseResult.phase_name)}`);
      lines.push("");
      lines.push(`- Exit code: \`${String(phaseResult.exit_code)}\``);
      lines.push(`- CLI: \`${requiredText(phaseResult.cli_path)}\``);
      lines.push(`- Run id: \`${optionalText(phaseResult.run_id) ?? "n/a"}\``);
      lines.push(
        `- Prompt artifact: \`${optionalText(phaseResult.prompt_path) ?? "n/a"}\``
      );
      lines.push(
        `- Stdout artifact: \`${optionalText(phaseResult.stdout_path) ?? "n/a"}\``
      );
      lines.push(
        `- Stderr artifact: \`${optionalText(phaseResult.stderr_path) ?? "n/a"}\``
      );
      lines.push(
        `- Metadata artifact: \`${optionalText(phaseResult.metadata_path) ?? "n/a"}\``
      );
      const phaseError = optionalText(phaseResult.error);
      if (phaseError !== null) {
        lines.push(`- Error: ${phaseError}`);
      }
      lines.push("");
    }
  }

  return {
    markdown: `${lines.join("\n").trimEnd()}\n`,
    reason: "result_markdown_projected"
  };
}

export function daemonResultReportAuthoringDecision(
  input: DaemonResultReportAuthoringDecisionInput
): DaemonResultReportAuthoringDecision {
  const cliPath = nonEmpty(input.cliPath);
  if (cliPath === null) {
    return {
      action: "fallback_markdown",
      promptText: null,
      cliPath: null,
      repoRoot: input.repoRoot,
      workdir: input.repoRoot,
      runLabel: null,
      generatedAt: input.generatedAt,
      reason: "active_agent_cli_missing"
    };
  }

  const facts = daemonResultMarkdownProjection({
    result: input.result,
    generatedAt: input.generatedAt
  }).markdown.trim();
  const promptText = [
    "Write a deterministic operator-facing Markdown result report.",
    "",
    "Requirements:",
    "- Preserve the exact factual content provided below.",
    "- Include the explicit generation date and time exactly as given.",
    "- Keep the output concise and structured with headings and bullet points.",
    "- Do not invent facts that are not present in the supplied data.",
    "",
    "# Runtime Paths",
    "",
    input.runtimePathsText.trim(),
    "",
    "# Structured Facts",
    "",
    facts
  ].join("\n") + "\n";

  return {
    action: "run_configured_cli",
    promptText,
    cliPath,
    repoRoot: input.repoRoot,
    workdir: input.repoRoot,
    runLabel: `result-report-${stem(requiredText(input.result.prompt_path))}`,
    generatedAt: input.generatedAt,
    reason: "configured_cli_authoring_requested"
  };
}

export function daemonResultReportAuthoredOutputDecision(
  input: DaemonResultReportAuthoredOutputDecisionInput
): DaemonResultReportAuthoredOutputDecision {
  const authored = selectAgentOutput(
    input.stdoutText,
    input.stderrText
  ).trim();
  if (authored.length === 0) {
    return {
      action: "error",
      authoredMarkdown: null,
      errorMessage:
        `Configured CLI returned no result report content for ${input.promptName}.`,
      reason: "authored_output_empty"
    };
  }
  if (
    !authored.includes("Generated at:") ||
    !authored.includes(input.generatedAt)
  ) {
    return {
      action: "error",
      authoredMarkdown: null,
      errorMessage:
        "Configured CLI result report did not preserve the required generated-at timestamp.",
      reason: "authored_output_missing_generated_at"
    };
  }
  return {
    action: "accept",
    authoredMarkdown: `${authored}\n`,
    errorMessage: null,
    reason: "authored_output_accepted"
  };
}

export function daemonPlanStateDecision(
  input: DaemonPlanStateDecisionInput
): DaemonPlanStateDecision {
  if (input.requestClass === "direct_response") {
    return {
      planAllCompleted: true,
      nextPendingTask: null,
      reason: "direct_response_plan_complete"
    };
  }

  if (input.taskSync === null) {
    return {
      planAllCompleted: null,
      nextPendingTask: null,
      reason: "task_sync_missing"
    };
  }

  const allCompletedRaw = input.taskSync.all_completed;
  const nextPendingRaw = input.taskSync.next_pending_task;
  const nextPendingText =
    typeof nextPendingRaw === "string" ? nextPendingRaw.trim() : "";
  return {
    planAllCompleted:
      allCompletedRaw === null || allCompletedRaw === undefined
        ? null
        : Boolean(allCompletedRaw),
    nextPendingTask: nextPendingText.length > 0 ? nextPendingText : null,
    reason: "task_sync_normalized"
  };
}

export function daemonArtifactWriterDecision(
  input: DaemonArtifactWriterDecisionInput
): DaemonArtifactWriterDecision {
  return {
    baseDir: input.baseDir,
    logsDir: input.logsDir,
    runId: input.runId,
    role: "daemon",
    stageName: "daemon",
    sessionId: input.sessionId,
    reason: "daemon_artifact_writer_bound"
  };
}

export function daemonArtifactPersistedEventDecision(
  input: DaemonArtifactPersistedEventDecisionInput
): DaemonArtifactPersistedEventDecision {
  const artifactKind = input.artifactKind.trim();
  if (artifactKind === "input_prompt") {
    return {
      eventType: "artifact_persisted",
      role: "daemon",
      stage: "daemon",
      status: "persisted",
      artifactKind,
      summary: "Persisted the daemon prompt into the active session workspace.",
      reason: "input_prompt_artifact_persisted"
    };
  }
  if (artifactKind === "result_report") {
    return {
      eventType: "artifact_persisted",
      role: "daemon",
      stage: "daemon",
      status: "persisted",
      artifactKind,
      summary: "Persisted the daemon result report.",
      reason: "result_report_artifact_persisted"
    };
  }
  return {
    eventType: "artifact_persisted",
    role: "daemon",
    stage: "daemon",
    status: "persisted",
    artifactKind,
    summary: `Persisted daemon artifact: ${artifactKind}.`,
    reason: "daemon_artifact_persisted"
  };
}

export function daemonSupervisorHandoffDecision(
  input: DaemonSupervisorHandoffDecisionInput
): DaemonSupervisorHandoffDecision {
  const fromRole = nonEmpty(input.fromRole) ?? "planner";
  const toRole = nonEmpty(input.toRole) ?? "developer";
  const rawAttempt = Number.isFinite(input.attempt) ? input.attempt : 1;
  const attempt = Math.max(1, Math.trunc(rawAttempt));
  return {
    eventType: "supervisor.handoff",
    role: fromRole,
    stage: toRole,
    status: "handoff",
    payload: {
      fromRole,
      toRole,
      reason:
        "Mandatory refine/plan prelude completed; handing off to the supervised developer loop.",
      attempt
    },
    reason: "daemon_supervisor_prelude_handoff"
  };
}

export function daemonRunLifecycleEventDecision(
  input: DaemonRunLifecycleEventDecisionInput
): DaemonRunLifecycleEventDecision {
  const promptSummary = nonEmpty(input.promptSummary);
  if (input.eventKind === "started") {
    return {
      eventType: "run.started",
      role: "daemon",
      stage: "daemon",
      status: "started",
      payload: {
        source: "daemon_runner",
        entrypoint: "DaemonRunner._process_prompt",
        trigger: "daemon_queue",
        promptSummary
      },
      reason: "daemon_run_started"
    };
  }
  return {
    eventType: "run.requested",
    role: "daemon",
    stage: "daemon",
    status: "requested",
    payload: {
      source: "daemon_runner",
      entrypoint: "DaemonRunner._process_prompt",
      trigger: "daemon_queue",
      promptSummary
    },
    reason: "daemon_run_requested"
  };
}

export function daemonResultArtifactRefDecision(
  input: DaemonResultArtifactRefDecisionInput
): DaemonResultArtifactRefDecision {
  if (!input.resultExists) {
    return {
      action: "skip",
      artifactRef: null,
      reason: "result_report_missing"
    };
  }

  return {
    action: "reference",
    artifactRef: {
      kind: "result_report",
      path: input.resultPath,
      label: "result_report",
      contentType: "text/markdown",
      createdAt: nonEmpty(input.createdAt),
      runId: nonEmpty(input.daemonRunId) ?? nonEmpty(input.latestRunId),
      role: "daemon",
      stageName: "daemon",
      sessionId: nonEmpty(input.sessionId)
    },
    reason: "result_report_referenced"
  };
}

export function daemonRunFinishedDecision(
  input: DaemonRunFinishedDecisionInput
): DaemonRunFinishedDecision {
  const outcome = nonEmpty(input.outcome) ?? "unknown";
  return {
    eventType: "run.finished",
    role: "daemon",
    stage: "daemon",
    status: outcome,
    source: "daemon_runner",
    runEntrypoint: "DaemonRunner._process_prompt",
    attemptsCompleted: nonNegativeIntegerOrNull(input.attemptsCompleted),
    retriesUsed: nonNegativeIntegerOrNull(input.retriesUsed),
    supervisorVerdict: nonEmpty(input.supervisorVerdict),
    outcome,
    error: nonEmpty(input.error),
    reason: "daemon_run_finished"
  };
}

export function daemonRoadmapPhaseDecision(
  input: DaemonRoadmapPhaseDecisionInput
): DaemonRoadmapPhaseDecision {
  for (const phaseId of input.activePhaseIds) {
    if (typeof phaseId !== "string") {
      continue;
    }
    if (phaseId.trim().length > 0) {
      return {
        expectedRoadmapPhaseId: phaseId,
        reason: "active_phase_selected"
      };
    }
  }
  return {
    expectedRoadmapPhaseId: "phase_4",
    reason: "default_phase_selected"
  };
}

export function daemonGoalSourceDecision(
  input: DaemonGoalSourceDecisionInput
): DaemonGoalSourceDecision {
  const match = /^<!--\s*dormammu:goal_source=([^\s>]+)\s*-->/m.exec(
    input.promptText
  );
  const goalSourcePath = match?.[1]?.trim() ?? "";
  if (goalSourcePath.length === 0) {
    return {
      goalSourcePath: null,
      reason: "goal_source_missing"
    };
  }
  return {
    goalSourcePath,
    reason: "goal_source_found"
  };
}

export function daemonAgentCliDecision(
  input: DaemonAgentCliDecisionInput
): DaemonAgentCliDecision {
  const agentCli = nonEmpty(input.activeAgentCli);
  if (agentCli !== null) {
    return {
      action: "use",
      agentCli,
      errorMessage: null,
      reason: "active_agent_cli_configured"
    };
  }
  return {
    action: "error",
    agentCli: null,
    errorMessage: [
      "daemonize requires active_agent_cli in dormammu.json or ~/.dormammu/config. ",
      "It now reuses the normal dormammu run loop instead of per-phase daemon CLI settings."
    ].join(""),
    reason: "active_agent_cli_missing"
  };
}

export function daemonTerminalErrorDecision(
  input: DaemonTerminalErrorDecisionInput
): DaemonTerminalErrorDecision {
  const status = nonEmpty(input.status) ?? "unknown";
  const nextPendingTask = nonEmpty(input.nextPendingTask);

  if (status === "failed") {
    const suffix =
      nextPendingTask !== null
        ? ` Next pending PLAN task: ${nextPendingTask}.`
        : "";
    return {
      status,
      nextPendingTask,
      message: `Loop retry budget was exhausted before PLAN.md completed.${suffix}`,
      reason: "retry_budget_exhausted"
    };
  }
  if (status === "blocked") {
    return {
      status,
      nextPendingTask,
      message: "Loop stopped because the configured coding-agent CLIs were blocked.",
      reason: "agent_cli_blocked"
    };
  }
  if (status === "manual_review_needed") {
    return {
      status,
      nextPendingTask,
      message: "Loop stopped because manual review is required.",
      reason: "manual_review_needed"
    };
  }
  return {
    status,
    nextPendingTask,
    message: `Loop finished with terminal status: ${status}.`,
    reason: "terminal_status_fallback"
  };
}

export function daemonTerminalStatusDecision(
  input: DaemonTerminalStatusDecisionInput
): DaemonTerminalStatusDecision {
  const status = nonEmpty(input.status) ?? "unknown";
  if (status === "completed") {
    if (input.planAllCompleted === true) {
      return {
        status,
        error: null,
        preserveCompleted: false,
        reason: "plan_complete"
      };
    }
    if (input.hasCleanTerminalStageEvidence) {
      return {
        status,
        error: null,
        preserveCompleted: true,
        reason: "clean_terminal_stage_evidence"
      };
    }
    return {
      status: "failed",
      error: "Loop returned completed but session PLAN.md is not fully complete.",
      preserveCompleted: false,
      reason: "completed_plan_incomplete"
    };
  }
  return {
    status,
    error: daemonTerminalErrorDecision({
      status,
      nextPendingTask: input.nextPendingTask
    }).message,
    preserveCompleted: false,
    reason: "terminal_error_status"
  };
}

export function daemonResultStatusDecision(
  input: DaemonResultStatusDecisionInput
): DaemonResultStatusDecision {
  const match = /^- Status: `([^`]+)`$/m.exec(input.resultText);
  if (match === null) {
    return {
      status: null,
      reason: "status_line_missing"
    };
  }
  return {
    status: match[1]?.trim() ?? "",
    reason: "status_line_found"
  };
}

export function daemonExistingResultDecision(
  input: DaemonExistingResultDecisionInput
): DaemonExistingResultDecision {
  const existingResultStatus = nonEmpty(input.existingResultStatus);
  const removeExistingResult =
    input.resultExists && existingResultStatus === "completed";
  return {
    action: removeExistingResult ? "remove" : "keep",
    removeExistingResult,
    promptPath: input.promptPath,
    resultPath: input.resultPath,
    existingResultStatus,
    reason: removeExistingResult
      ? "completed_result_reprocess"
      : input.resultExists
        ? "existing_result_not_completed"
        : "no_existing_result"
  };
}

export function daemonPromptSettleDecision(
  input: DaemonPromptSettleDecisionInput
): DaemonPromptSettleDecision {
  const settleSeconds = Math.max(0, input.settleSeconds);
  const ageSeconds = Math.max(0, input.ageSeconds);
  const remainingSeconds = Math.max(settleSeconds - ageSeconds, 0);
  const shouldDefer = settleSeconds > 0 && remainingSeconds > 0;
  return {
    action: shouldDefer ? "defer" : "ready",
    promptPath: input.promptPath,
    retryAfterSeconds: shouldDefer ? remainingSeconds : null,
    reason: shouldDefer ? "settle_window_pending" : "settle_window_elapsed"
  };
}

export function daemonQueueFileDecision(
  input: DaemonQueueFileDecisionInput
): DaemonQueueFileDecision {
  if (input.inProgress) {
    return {
      action: "skip",
      promptPath: input.promptPath,
      reason: "prompt_in_progress"
    };
  }
  if (!input.promptCandidate) {
    return {
      action: "skip",
      promptPath: input.promptPath,
      reason: "not_prompt_candidate"
    };
  }
  return {
    action: "inspect",
    promptPath: input.promptPath,
    reason: "prompt_ready_for_inspection"
  };
}

export function daemonLoopIterationDecision(
  input: DaemonLoopIterationInput
): DaemonLoopIterationDecision {
  const processedCount = Math.max(0, Math.trunc(input.processedCount));
  const inProgressCount = Math.max(0, Math.trunc(input.inProgressCount));
  const heartbeatStatus = inProgressCount > 0 ? "busy" : "idle";

  if (input.shutdownRequested) {
    return {
      action: "stop",
      heartbeatStatus,
      waitForChanges: false,
      reason: "shutdown_requested"
    };
  }

  if (processedCount === 0) {
    return {
      action: "wait",
      heartbeatStatus,
      waitForChanges: true,
      reason: "no_prompt_processed"
    };
  }

  return {
    action: "continue",
    heartbeatStatus,
    waitForChanges: false,
    reason: "prompt_processed"
  };
}

export function daemonStartupDecision(
  input: DaemonStartupDecisionInput
): DaemonStartupDecision {
  return {
    action: "start",
    initialHeartbeatStatus: "idle",
    startGoalsScheduler: input.goalsSchedulerConfigured,
    triggerGoalsScheduler: input.goalsSchedulerConfigured,
    startAutonomousScheduler: input.autonomousSchedulerConfigured,
    triggerAutonomousScheduler: input.autonomousSchedulerConfigured,
    reason: "daemon_startup"
  };
}

export function daemonStartupBannerDecision(
  input: DaemonStartupBannerDecisionInput
): DaemonStartupBannerDecision {
  const allowedExtensionsDescription =
    input.allowedExtensions.length === 0
      ? "any"
      : input.allowedExtensions.join(",");
  const lines = [
    "=== dormammu daemonize ===",
    `repo root: ${input.repoRoot}`,
    `daemon config: ${input.configPath}`,
    `prompt path: ${input.promptPath}`,
    `result path: ${input.resultPath}`,
    [
      "watcher: ",
      `${input.watcherBackend} (requested=${input.requestedWatcherBackend}, `,
      `poll_interval=${input.pollIntervalSeconds}s, `,
      `settle=${input.settleSeconds}s)`
    ].join(""),
    [
      "prompt detection: ",
      `hidden_files=${input.ignoreHiddenFiles ? "ignore" : "include"}, `,
      `extensions=${allowedExtensionsDescription}, `,
      "replace_completed_result_on_requeued_prompt=yes, ",
      "order=numeric-prefix -> alpha-prefix -> remaining-name"
    ].join(""),
    [
      "prompt lifecycle: each accepted prompt reuses the dormammu run loop ",
      "and writes its result only after the loop reaches a terminal outcome"
    ].join("")
  ];

  if (nonEmpty(input.goalsPath) !== null) {
    lines.push(
      [
        `goals: ${input.goalsPath} `,
        `(interval=${input.goalsIntervalMinutes ?? 0}m, `,
        "watching for .md files)"
      ].join("")
    );
  } else {
    lines.push("goals: disabled");
  }

  if (input.autonomousEnabled) {
    lines.push(
      [
        "autonomous: enabled ",
        `(interval=${input.autonomousIntervalMinutes ?? 0}m, `,
        `focus=${nonEmpty(input.autonomousFocus) ?? ""}, `,
        `max_queued=${input.autonomousMaxQueuedTasks ?? 0})`
      ].join("")
    );
  } else {
    lines.push("autonomous: disabled");
  }

  return {
    allowedExtensionsDescription,
    lines,
    reason: "startup_banner_projected"
  };
}

export function daemonShutdownDecision(
  input: DaemonShutdownDecisionInput
): DaemonShutdownDecision {
  return {
    action: "shutdown",
    stopGoalsScheduler: input.goalsSchedulerConfigured,
    stopAutonomousScheduler: input.autonomousSchedulerConfigured,
    closeWatcher: true,
    removeHeartbeat: true,
    closeProgressLog: input.progressLogActive,
    reason: "daemon_shutdown"
  };
}

export function daemonInstanceLockDecision(
  input: DaemonInstanceLockDecisionInput
): DaemonInstanceLockDecision {
  if (!input.fcntlAvailable) {
    return {
      action: "skip",
      writePidFile: false,
      errorMessage: null,
      reason: "fcntl_unavailable"
    };
  }

  if (input.lockAcquired) {
    return {
      action: "hold",
      writePidFile: true,
      errorMessage: null,
      reason: "instance_lock_acquired"
    };
  }

  const existingPid = input.existingPid?.trim() ?? "";
  const pidInfo = existingPid.length > 0
    ? ` (existing daemon PID: ${existingPid})`
    : "";
  return {
    action: "reject",
    writePidFile: false,
    errorMessage: [
      `Another dormammu daemon is already running against ${input.promptPath}${pidInfo}.`,
      "Stop it first or use a different prompt_path."
    ].join("\n"),
    reason: "instance_lock_busy"
  };
}

export function daemonInstanceUnlockDecision(
  input: DaemonInstanceUnlockDecisionInput
): DaemonInstanceUnlockDecision {
  if (!input.fcntlAvailable || !input.lockHeld) {
    return {
      action: "skip",
      unlockFcntl: false,
      closeLockFile: false,
      clearPidLockFile: false,
      removePidFile: false,
      reason: !input.fcntlAvailable ? "fcntl_unavailable" : "lock_not_held"
    };
  }

  return {
    action: "release",
    unlockFcntl: true,
    closeLockFile: true,
    clearPidLockFile: true,
    removePidFile: true,
    reason: "instance_lock_release"
  };
}

export function daemonHeartbeatWriteDecision(
  input: DaemonHeartbeatWriteDecisionInput
): DaemonHeartbeatWriteDecision {
  if (!input.heartbeatPathConfigured) {
    return {
      action: "skip",
      ensureParent: false,
      heartbeatPayload: null,
      reason: "heartbeat_path_unconfigured"
    };
  }

  return {
    action: "write",
    ensureParent: true,
    heartbeatPayload: {
      pid: Math.trunc(input.pid),
      status: input.status,
      ts: input.timestamp
    },
    reason: "heartbeat_write"
  };
}

export function daemonHeartbeatRemoveDecision(
  input: DaemonHeartbeatRemoveDecisionInput
): DaemonHeartbeatRemoveDecision {
  if (!input.heartbeatPathConfigured) {
    return {
      action: "skip",
      removeHeartbeat: false,
      reason: "heartbeat_path_unconfigured"
    };
  }

  return {
    action: "remove",
    removeHeartbeat: true,
    reason: "heartbeat_remove"
  };
}

export function daemonWatcherBackendDecision(
  input: DaemonWatcherBackendDecisionInput
): DaemonWatcherBackendDecision {
  if (input.requestedBackend === "polling") {
    return {
      action: "use",
      backend: "polling",
      errorMessage: null,
      reason: "polling_requested"
    };
  }

  if (input.requestedBackend === "inotify") {
    if (!input.inotifyAvailable) {
      return {
        action: "error",
        backend: null,
        errorMessage: "Inotify backend is not available on this platform.",
        reason: "inotify_unavailable"
      };
    }
    return {
      action: "use",
      backend: "inotify",
      errorMessage: null,
      reason: "inotify_requested"
    };
  }

  if (input.inotifyAvailable) {
    return {
      action: "use",
      backend: "inotify",
      errorMessage: null,
      reason: "auto_prefers_inotify"
    };
  }

  return {
    action: "use",
    backend: "polling",
    errorMessage: null,
    reason: "auto_falls_back_to_polling"
  };
}

export function daemonWatcherWaitDecision(
  input: DaemonWatcherWaitDecisionInput
): DaemonWatcherWaitDecision {
  const watcherBackend = input.watcherBackend.trim() || "unknown";

  if (input.shutdownRequested) {
    return {
      action: "skip",
      waitForChanges: false,
      watcherBackend,
      reason: "shutdown_requested"
    };
  }

  if (!input.waitRequested) {
    return {
      action: "skip",
      waitForChanges: false,
      watcherBackend,
      reason: "wait_not_requested"
    };
  }

  return {
    action: "wait",
    waitForChanges: true,
    watcherBackend,
    reason: "wait_requested"
  };
}

function basename(path: string): string {
  const normalized = path.replace(/\\/g, "/");
  const slashIndex = normalized.lastIndexOf("/");
  return slashIndex >= 0 ? normalized.slice(slashIndex + 1) : normalized;
}

function dirname(path: string): string {
  const normalized = path.replace(/\\/g, "/").replace(/\/+$/, "");
  const slashIndex = normalized.lastIndexOf("/");
  if (slashIndex > 0) {
    return normalized.slice(0, slashIndex);
  }
  if (slashIndex === 0) {
    return "/";
  }
  return ".";
}

function joinPath(base: string, ...parts: string[]): string {
  const normalizedBase = base.replace(/\\/g, "/").replace(/\/+$/, "");
  const filteredParts = parts
    .map((part) => part.replace(/\\/g, "/").replace(/^\/+|\/+$/g, ""))
    .filter((part) => part.length > 0);
  if (normalizedBase === "" || normalizedBase === ".") {
    return filteredParts.join("/");
  }
  if (normalizedBase === "/") {
    return `/${filteredParts.join("/")}`;
  }
  return [normalizedBase, ...filteredParts].join("/");
}

function stem(path: string): string {
  const name = basename(path);
  const dotIndex = name.lastIndexOf(".");
  return dotIndex > 0 ? name.slice(0, dotIndex) : name;
}

function nonEmpty(value: string | null): string | null {
  const trimmed = value?.trim() ?? "";
  return trimmed.length > 0 ? trimmed : null;
}

function selectAgentOutput(
  stdoutText: string | null,
  stderrText: string | null
): string {
  if (stdoutText !== null && stdoutText.trim().length > 0) {
    return stdoutText;
  }
  if (stderrText !== null && stderrText.trim().length > 0) {
    return stderrText;
  }
  return stdoutText ?? stderrText ?? "";
}

function nonNegativeIntegerOrNull(value: number | null): number | null {
  if (value === null) {
    return null;
  }
  return Math.max(0, Math.trunc(value));
}

function optionalText(value: unknown): string | null {
  if (value === null || value === undefined) {
    return null;
  }
  const text = String(value);
  return text.length > 0 ? text : null;
}

function requiredText(value: unknown): string {
  return String(value);
}

function displayValue(value: unknown): string {
  return String(value);
}

function tupleDisplay(value: unknown): string {
  if (!Array.isArray(value)) {
    return String(value);
  }
  return `(${value.map((item) => pythonRepr(item)).join(", ")}${value.length === 1 ? "," : ""})`;
}

function pythonRepr(value: unknown): string {
  if (typeof value === "string") {
    return `'${value.replace(/\\/g, "\\\\").replace(/'/g, "\\'")}'`;
  }
  if (value === null) {
    return "None";
  }
  if (typeof value === "boolean") {
    return value ? "True" : "False";
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => pythonRepr(item)).join(", ")}]`;
  }
  return String(value);
}

function recordOrNull(value: unknown): Readonly<Record<string, unknown>> | null {
  if (value === null || value === undefined || typeof value !== "object") {
    return null;
  }
  if (Array.isArray(value)) {
    return null;
  }
  return value as Readonly<Record<string, unknown>>;
}

function arrayOfRecords(
  value: unknown
): ReadonlyArray<Readonly<Record<string, unknown>>> {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.flatMap((item) => {
    const record = recordOrNull(item);
    return record === null ? [] : [record];
  });
}

function valueOrNullText(value: unknown): string {
  if (value === null || value === undefined) {
    return "None";
  }
  return String(value);
}
