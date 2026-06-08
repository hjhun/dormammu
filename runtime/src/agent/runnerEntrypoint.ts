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
  daemonArtifactPersistedEventDecision,
  daemonArtifactWriterDecision,
  daemonAgentCliDecision,
  daemonCleanTerminalEvidenceDecision,
  daemonExistingResultDecision,
  daemonGoalSourceDecision,
  daemonHeartbeatRemoveDecision,
  daemonHeartbeatWriteDecision,
  daemonInstanceLockDecision,
  daemonInstanceUnlockDecision,
  daemonLoopIterationDecision,
  daemonPlanStateDecision,
  daemonPendingDecision,
  daemonPromptCompletionLineDecision,
  daemonPromptInterruptionDecision,
  daemonPromptLifecycleDecision,
  daemonPromptPathDecision,
  daemonPromptProcessingMetadataDecision,
  daemonRequestClassDecision,
  daemonPromptRouteDecision,
  daemonPromptSessionDecision,
  daemonPromptSettleDecision,
  daemonPromptSummaryDecision,
  daemonQueueFileDecision,
  daemonResultArtifactRefDecision,
  daemonResultMarkdownProjection,
  daemonResultReportAuthoredOutputDecision,
  daemonResultReportAuthoringDecision,
  daemonResultReportFallbackDecision,
  daemonResultReportDecision,
  daemonResultStatusDecision,
  daemonRoadmapPhaseDecision,
  daemonRunLifecycleEventDecision,
  daemonRunFinishedDecision,
  daemonShutdownDecision,
  daemonStartupBannerDecision,
  daemonStartupDecision,
  daemonSupervisorHandoffDecision,
  daemonTerminalErrorDecision,
  daemonTerminalStatusDecision,
  daemonWatcherBackendDecision,
  daemonWatcherWaitDecision,
  type DaemonArtifactPersistedEventDecision,
  type DaemonArtifactWriterDecision,
  type DaemonAgentCliDecision,
  type DaemonCleanTerminalEvidenceDecision,
  type DaemonExistingResultDecision,
  type DaemonGoalSourceDecision,
  type DaemonHeartbeatRemoveDecision,
  type DaemonHeartbeatStatus,
  type DaemonHeartbeatWriteDecision,
  type DaemonInstanceLockDecision,
  type DaemonInstanceUnlockDecision,
  type DaemonLoopIterationDecision,
  type DaemonPlanStateDecision,
  type DaemonPendingDecision,
  type DaemonPromptCompletionLineDecision,
  type DaemonPromptInterruptionDecision,
  type DaemonPromptLifecycleDecision,
  type DaemonPromptPathDecision,
  type DaemonPromptProcessingMetadataDecision,
  type DaemonRequestClassDecision,
  type DaemonPromptRouteDecision,
  type DaemonPromptSessionDecision,
  type DaemonPromptSettleDecision,
  type DaemonPromptSummaryDecision,
  type DaemonQueueFileDecision,
  type DaemonResultArtifactRefDecision,
  type DaemonResultMarkdownProjection,
  type DaemonResultReportAuthoredOutputDecision,
  type DaemonResultReportAuthoringDecision,
  type DaemonResultReportFallbackDecision,
  type DaemonResultReportDecision,
  type DaemonResultStatusDecision,
  type DaemonRoadmapPhaseDecision,
  type DaemonRunLifecycleEventDecision,
  type DaemonRunFinishedDecision,
  type DaemonShutdownDecision,
  type DaemonStartupBannerDecision,
  type DaemonStartupDecision,
  type DaemonSupervisorHandoffDecision,
  type DaemonTerminalErrorDecision,
  type DaemonTerminalStatusDecision,
  type DaemonWatcherBackend,
  type DaemonWatcherBackendDecision,
  type DaemonWatcherWaitDecision
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
import {
  stageResultToDict,
  type RunResult,
  type StageResult
} from "../results.js";
import type { RequestClass } from "../workflowPolicy.js";

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

export type DaemonPromptRouteEntrypointPayload = {
  entrypoint: "daemon_prompt_route_decision";
  has_agents_config: boolean;
  request_class: RequestClass;
  has_goal_file: boolean;
};

export type DaemonPromptRouteEntrypointResultPayload =
  DaemonPromptRouteDecision & {
    entrypoint: "daemon_prompt_route_decision";
  };

export type DaemonRequestClassEntrypointPayload = {
  entrypoint: "daemon_request_class_decision";
  prompt_text: string;
  workflow_state?: Record<string, unknown> | null;
};

export type DaemonRequestClassEntrypointResultPayload =
  DaemonRequestClassDecision & {
    entrypoint: "daemon_request_class_decision";
  };

export type DaemonPromptLifecycleEntrypointPayload = {
  entrypoint: "daemon_prompt_lifecycle_decision";
  prompt_path: string;
  result_path: string;
  prompt_exists: boolean;
};

export type DaemonPromptLifecycleEntrypointResultPayload =
  DaemonPromptLifecycleDecision & {
    entrypoint: "daemon_prompt_lifecycle_decision";
  };

export type DaemonPromptPathEntrypointPayload = {
  entrypoint: "daemon_prompt_path_decision";
  prompt_path: string;
  result_path_root: string;
};

export type DaemonPromptPathEntrypointResultPayload =
  DaemonPromptPathDecision & {
    entrypoint: "daemon_prompt_path_decision";
  };

export type DaemonPromptSessionEntrypointPayload = {
  entrypoint: "daemon_prompt_session_decision";
  prompt_name: string;
  prompt_text: string;
};

export type DaemonPromptSessionEntrypointResultPayload =
  DaemonPromptSessionDecision & {
    entrypoint: "daemon_prompt_session_decision";
  };

export type DaemonPromptProcessingMetadataEntrypointPayload = {
  entrypoint: "daemon_prompt_processing_metadata_decision";
  prompt_name: string;
  prompt_text: string;
  watcher_backend: string;
  result_path: string;
};

export type DaemonPromptProcessingMetadataEntrypointResultPayload =
  DaemonPromptProcessingMetadataDecision & {
    entrypoint: "daemon_prompt_processing_metadata_decision";
  };

export type DaemonPlanStateEntrypointPayload = {
  entrypoint: "daemon_plan_state_decision";
  request_class: string;
  task_sync?: Record<string, unknown> | null;
};

export type DaemonPlanStateEntrypointResultPayload =
  DaemonPlanStateDecision & {
    entrypoint: "daemon_plan_state_decision";
  };

export type DaemonArtifactWriterEntrypointPayload = {
  entrypoint: "daemon_artifact_writer_decision";
  base_dir: string;
  logs_dir?: string | null;
  run_id?: string | null;
  session_id?: string | null;
};

export type DaemonArtifactWriterEntrypointResultPayload =
  DaemonArtifactWriterDecision & {
    entrypoint: "daemon_artifact_writer_decision";
  };

export type DaemonArtifactPersistedEventEntrypointPayload = {
  entrypoint: "daemon_artifact_persisted_event_decision";
  artifact_kind: string;
};

export type DaemonArtifactPersistedEventEntrypointResultPayload =
  DaemonArtifactPersistedEventDecision & {
    entrypoint: "daemon_artifact_persisted_event_decision";
  };

export type DaemonSupervisorHandoffEntrypointPayload = {
  entrypoint: "daemon_supervisor_handoff_decision";
  from_role: string;
  to_role: string;
  attempt: number;
};

export type DaemonSupervisorHandoffEntrypointResultPayload =
  DaemonSupervisorHandoffDecision & {
    entrypoint: "daemon_supervisor_handoff_decision";
  };

export type DaemonRunLifecycleEventEntrypointPayload = {
  entrypoint: "daemon_run_lifecycle_event_decision";
  event_kind: "requested" | "started";
  prompt_summary?: string | null;
};

export type DaemonRunLifecycleEventEntrypointResultPayload =
  DaemonRunLifecycleEventDecision & {
    entrypoint: "daemon_run_lifecycle_event_decision";
  };

export type DaemonPromptSummaryEntrypointPayload = {
  entrypoint: "daemon_prompt_summary_decision";
  prompt_text: string;
};

export type DaemonPromptSummaryEntrypointResultPayload =
  DaemonPromptSummaryDecision & {
    entrypoint: "daemon_prompt_summary_decision";
  };

export type DaemonResultReportEntrypointPayload = {
  entrypoint: "daemon_result_report_decision";
  prompt_path: string;
  result_path: string;
  prompt_exists: boolean;
  daemon_run_id?: string | null;
  latest_run_id?: string | null;
  session_id?: string | null;
};

export type DaemonResultReportEntrypointResultPayload =
  DaemonResultReportDecision & {
    entrypoint: "daemon_result_report_decision";
  };

export type DaemonResultReportFallbackEntrypointPayload = {
  entrypoint: "daemon_result_report_fallback_decision";
  prompt_name: string;
  existing_error?: string | null;
  cause: string;
};

export type DaemonResultReportFallbackEntrypointResultPayload =
  DaemonResultReportFallbackDecision & {
    entrypoint: "daemon_result_report_fallback_decision";
  };

export type DaemonResultMarkdownEntrypointPayload = {
  entrypoint: "daemon_result_markdown_projection";
  result: Record<string, unknown>;
  generated_at: string;
};

export type DaemonResultMarkdownEntrypointResultPayload =
  DaemonResultMarkdownProjection & {
    entrypoint: "daemon_result_markdown_projection";
  };

export type DaemonResultReportAuthoringEntrypointPayload = {
  entrypoint: "daemon_result_report_authoring_decision";
  result: Record<string, unknown>;
  generated_at: string;
  runtime_paths_text: string;
  cli_path?: string | null;
  repo_root: string;
};

export type DaemonResultReportAuthoringEntrypointResultPayload =
  DaemonResultReportAuthoringDecision & {
    entrypoint: "daemon_result_report_authoring_decision";
  };

export type DaemonResultReportAuthoredOutputEntrypointPayload = {
  entrypoint: "daemon_result_report_authored_output_decision";
  stdout_text?: string | null;
  stderr_text?: string | null;
  generated_at: string;
  prompt_name: string;
};

export type DaemonResultReportAuthoredOutputEntrypointResultPayload =
  DaemonResultReportAuthoredOutputDecision & {
    entrypoint: "daemon_result_report_authored_output_decision";
  };

export type DaemonResultArtifactRefEntrypointPayload = {
  entrypoint: "daemon_result_artifact_ref_decision";
  result_path: string;
  result_exists: boolean;
  created_at?: string | null;
  daemon_run_id?: string | null;
  latest_run_id?: string | null;
  session_id?: string | null;
};

export type DaemonResultArtifactRefEntrypointResultPayload =
  DaemonResultArtifactRefDecision & {
    entrypoint: "daemon_result_artifact_ref_decision";
  };

export type DaemonRunFinishedEntrypointPayload = {
  entrypoint: "daemon_run_finished_decision";
  attempts_completed?: number | null;
  retries_used?: number | null;
  supervisor_verdict?: string | null;
  outcome: string;
  error?: string | null;
};

export type DaemonRunFinishedEntrypointResultPayload =
  DaemonRunFinishedDecision & {
    entrypoint: "daemon_run_finished_decision";
  };

export type DaemonPromptCompletionLineEntrypointPayload = {
  entrypoint: "daemon_prompt_completion_line_decision";
  prompt_name: string;
  status: string;
  result_path: string;
};

export type DaemonPromptCompletionLineEntrypointResultPayload =
  DaemonPromptCompletionLineDecision & {
    entrypoint: "daemon_prompt_completion_line_decision";
  };

export type DaemonPromptInterruptionEntrypointPayload = {
  entrypoint: "daemon_prompt_interruption_decision";
  prompt_name: string;
};

export type DaemonPromptInterruptionEntrypointResultPayload =
  DaemonPromptInterruptionDecision & {
    entrypoint: "daemon_prompt_interruption_decision";
  };

export type DaemonRoadmapPhaseEntrypointPayload = {
  entrypoint: "daemon_roadmap_phase_decision";
  active_phase_ids?: readonly unknown[] | null;
};

export type DaemonRoadmapPhaseEntrypointResultPayload =
  DaemonRoadmapPhaseDecision & {
    entrypoint: "daemon_roadmap_phase_decision";
  };

export type DaemonGoalSourceEntrypointPayload = {
  entrypoint: "daemon_goal_source_decision";
  prompt_text: string;
};

export type DaemonGoalSourceEntrypointResultPayload =
  DaemonGoalSourceDecision & {
    entrypoint: "daemon_goal_source_decision";
  };

export type DaemonAgentCliEntrypointPayload = {
  entrypoint: "daemon_agent_cli_decision";
  active_agent_cli?: string | null;
};

export type DaemonAgentCliEntrypointResultPayload = DaemonAgentCliDecision & {
  entrypoint: "daemon_agent_cli_decision";
};

export type DaemonTerminalErrorEntrypointPayload = {
  entrypoint: "daemon_terminal_error_decision";
  status: string;
  next_pending_task?: string | null;
};

export type DaemonTerminalErrorEntrypointResultPayload =
  DaemonTerminalErrorDecision & {
    entrypoint: "daemon_terminal_error_decision";
  };

export type DaemonTerminalStatusEntrypointPayload = {
  entrypoint: "daemon_terminal_status_decision";
  status: string;
  plan_all_completed?: boolean | null;
  has_clean_terminal_stage_evidence: boolean;
  next_pending_task?: string | null;
};

export type DaemonTerminalStatusEntrypointResultPayload =
  DaemonTerminalStatusDecision & {
    entrypoint: "daemon_terminal_status_decision";
  };

export type DaemonCleanTerminalEvidenceEntrypointPayload = {
  entrypoint: "daemon_clean_terminal_evidence_decision";
  run_result: Record<string, unknown>;
};

export type DaemonCleanTerminalEvidenceEntrypointResultPayload =
  DaemonCleanTerminalEvidenceDecision & {
    entrypoint: "daemon_clean_terminal_evidence_decision";
  };

export type DaemonExistingResultEntrypointPayload = {
  entrypoint: "daemon_existing_result_decision";
  prompt_path: string;
  result_path: string;
  result_exists: boolean;
  existing_result_status?: string | null;
};

export type DaemonExistingResultEntrypointResultPayload =
  DaemonExistingResultDecision & {
    entrypoint: "daemon_existing_result_decision";
  };

export type DaemonResultStatusEntrypointPayload = {
  entrypoint: "daemon_result_status_decision";
  result_text: string;
};

export type DaemonResultStatusEntrypointResultPayload =
  DaemonResultStatusDecision & {
    entrypoint: "daemon_result_status_decision";
  };

export type DaemonPromptSettleEntrypointPayload = {
  entrypoint: "daemon_prompt_settle_decision";
  prompt_path: string;
  settle_seconds: number;
  age_seconds: number;
};

export type DaemonPromptSettleEntrypointResultPayload =
  DaemonPromptSettleDecision & {
    entrypoint: "daemon_prompt_settle_decision";
  };

export type DaemonQueueFileEntrypointPayload = {
  entrypoint: "daemon_queue_file_decision";
  prompt_path: string;
  in_progress: boolean;
  prompt_candidate: boolean;
};

export type DaemonQueueFileEntrypointResultPayload =
  DaemonQueueFileDecision & {
    entrypoint: "daemon_queue_file_decision";
  };

export type DaemonLoopIterationEntrypointPayload = {
  entrypoint: "daemon_loop_iteration_decision";
  processed_count: number;
  in_progress_count: number;
  shutdown_requested: boolean;
};

export type DaemonLoopIterationEntrypointResultPayload =
  DaemonLoopIterationDecision & {
    entrypoint: "daemon_loop_iteration_decision";
  };

export type DaemonStartupEntrypointPayload = {
  entrypoint: "daemon_startup_decision";
  goals_scheduler_configured: boolean;
  autonomous_scheduler_configured: boolean;
};

export type DaemonStartupEntrypointResultPayload = DaemonStartupDecision & {
  entrypoint: "daemon_startup_decision";
};

export type DaemonStartupBannerEntrypointPayload = {
  entrypoint: "daemon_startup_banner_decision";
  repo_root: string;
  config_path: string;
  prompt_path: string;
  result_path: string;
  watcher_backend: string;
  requested_watcher_backend: string;
  poll_interval_seconds: number;
  settle_seconds: number;
  ignore_hidden_files: boolean;
  allowed_extensions?: readonly unknown[] | null;
  goals_path?: string | null;
  goals_interval_minutes?: number | null;
  autonomous_enabled: boolean;
  autonomous_interval_minutes?: number | null;
  autonomous_focus?: string | null;
  autonomous_max_queued_tasks?: number | null;
};

export type DaemonStartupBannerEntrypointResultPayload =
  DaemonStartupBannerDecision & {
    entrypoint: "daemon_startup_banner_decision";
  };

export type DaemonShutdownEntrypointPayload = {
  entrypoint: "daemon_shutdown_decision";
  goals_scheduler_configured: boolean;
  autonomous_scheduler_configured: boolean;
  progress_log_active: boolean;
};

export type DaemonShutdownEntrypointResultPayload = DaemonShutdownDecision & {
  entrypoint: "daemon_shutdown_decision";
};

export type DaemonInstanceLockEntrypointPayload = {
  entrypoint: "daemon_instance_lock_decision";
  fcntl_available: boolean;
  lock_acquired: boolean;
  prompt_path: string;
  existing_pid?: string | null;
};

export type DaemonInstanceLockEntrypointResultPayload =
  DaemonInstanceLockDecision & {
    entrypoint: "daemon_instance_lock_decision";
  };

export type DaemonInstanceUnlockEntrypointPayload = {
  entrypoint: "daemon_instance_unlock_decision";
  fcntl_available: boolean;
  lock_held: boolean;
};

export type DaemonInstanceUnlockEntrypointResultPayload =
  DaemonInstanceUnlockDecision & {
    entrypoint: "daemon_instance_unlock_decision";
  };

export type DaemonHeartbeatWriteEntrypointPayload = {
  entrypoint: "daemon_heartbeat_write_decision";
  heartbeat_path_configured: boolean;
  pid: number;
  status: DaemonHeartbeatStatus;
  timestamp: string;
};

export type DaemonHeartbeatWriteEntrypointResultPayload =
  DaemonHeartbeatWriteDecision & {
    entrypoint: "daemon_heartbeat_write_decision";
  };

export type DaemonHeartbeatRemoveEntrypointPayload = {
  entrypoint: "daemon_heartbeat_remove_decision";
  heartbeat_path_configured: boolean;
};

export type DaemonHeartbeatRemoveEntrypointResultPayload =
  DaemonHeartbeatRemoveDecision & {
    entrypoint: "daemon_heartbeat_remove_decision";
  };

export type DaemonWatcherBackendEntrypointPayload = {
  entrypoint: "daemon_watcher_backend_decision";
  requested_backend: DaemonWatcherBackend;
  inotify_available: boolean;
};

export type DaemonWatcherBackendEntrypointResultPayload =
  DaemonWatcherBackendDecision & {
    entrypoint: "daemon_watcher_backend_decision";
  };

export type DaemonWatcherWaitEntrypointPayload = {
  entrypoint: "daemon_watcher_wait_decision";
  wait_requested: boolean;
  shutdown_requested: boolean;
  watcher_backend: string;
};

export type DaemonWatcherWaitEntrypointResultPayload =
  DaemonWatcherWaitDecision & {
    entrypoint: "daemon_watcher_wait_decision";
  };

export type RunnerCliPayload =
  | AgentRunnerEntrypointPayload
  | DaemonArtifactPersistedEventEntrypointPayload
  | DaemonArtifactWriterEntrypointPayload
  | DaemonExistingResultEntrypointPayload
  | DaemonHeartbeatRemoveEntrypointPayload
  | DaemonHeartbeatWriteEntrypointPayload
  | DaemonInstanceLockEntrypointPayload
  | DaemonInstanceUnlockEntrypointPayload
  | DaemonLoopIterationEntrypointPayload
  | DaemonPendingDecisionEntrypointPayload
  | DaemonPlanStateEntrypointPayload
  | DaemonPromptLifecycleEntrypointPayload
  | DaemonPromptPathEntrypointPayload
  | DaemonPromptProcessingMetadataEntrypointPayload
  | DaemonRequestClassEntrypointPayload
  | DaemonPromptRouteEntrypointPayload
  | DaemonPromptSessionEntrypointPayload
  | DaemonPromptSettleEntrypointPayload
  | DaemonQueueFileEntrypointPayload
  | DaemonResultArtifactRefEntrypointPayload
  | DaemonResultReportAuthoredOutputEntrypointPayload
  | DaemonResultReportAuthoringEntrypointPayload
  | DaemonResultMarkdownEntrypointPayload
  | DaemonResultReportFallbackEntrypointPayload
  | DaemonResultReportEntrypointPayload
  | DaemonResultStatusEntrypointPayload
  | DaemonRoadmapPhaseEntrypointPayload
  | DaemonGoalSourceEntrypointPayload
  | DaemonAgentCliEntrypointPayload
  | DaemonRunLifecycleEventEntrypointPayload
  | DaemonPromptSummaryEntrypointPayload
  | DaemonRunFinishedEntrypointPayload
  | DaemonPromptCompletionLineEntrypointPayload
  | DaemonPromptInterruptionEntrypointPayload
  | DaemonShutdownEntrypointPayload
  | DaemonStartupBannerEntrypointPayload
  | DaemonStartupEntrypointPayload
  | DaemonSupervisorHandoffEntrypointPayload
  | DaemonTerminalErrorEntrypointPayload
  | DaemonTerminalStatusEntrypointPayload
  | DaemonCleanTerminalEvidenceEntrypointPayload
  | DaemonWatcherBackendEntrypointPayload
  | DaemonWatcherWaitEntrypointPayload
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
  | DaemonArtifactPersistedEventEntrypointResultPayload
  | DaemonArtifactWriterEntrypointResultPayload
  | DaemonExistingResultEntrypointResultPayload
  | DaemonHeartbeatRemoveEntrypointResultPayload
  | DaemonHeartbeatWriteEntrypointResultPayload
  | DaemonInstanceLockEntrypointResultPayload
  | DaemonInstanceUnlockEntrypointResultPayload
  | DaemonLoopIterationEntrypointResultPayload
  | DaemonPendingDecisionEntrypointResultPayload
  | DaemonPlanStateEntrypointResultPayload
  | DaemonPromptLifecycleEntrypointResultPayload
  | DaemonPromptPathEntrypointResultPayload
  | DaemonPromptProcessingMetadataEntrypointResultPayload
  | DaemonRequestClassEntrypointResultPayload
  | DaemonPromptRouteEntrypointResultPayload
  | DaemonPromptSessionEntrypointResultPayload
  | DaemonPromptSettleEntrypointResultPayload
  | DaemonQueueFileEntrypointResultPayload
  | DaemonResultArtifactRefEntrypointResultPayload
  | DaemonResultReportAuthoredOutputEntrypointResultPayload
  | DaemonResultReportAuthoringEntrypointResultPayload
  | DaemonResultMarkdownEntrypointResultPayload
  | DaemonResultReportFallbackEntrypointResultPayload
  | DaemonResultReportEntrypointResultPayload
  | DaemonResultStatusEntrypointResultPayload
  | DaemonRoadmapPhaseEntrypointResultPayload
  | DaemonGoalSourceEntrypointResultPayload
  | DaemonAgentCliEntrypointResultPayload
  | DaemonRunLifecycleEventEntrypointResultPayload
  | DaemonPromptSummaryEntrypointResultPayload
  | DaemonRunFinishedEntrypointResultPayload
  | DaemonPromptCompletionLineEntrypointResultPayload
  | DaemonPromptInterruptionEntrypointResultPayload
  | DaemonShutdownEntrypointResultPayload
  | DaemonStartupBannerEntrypointResultPayload
  | DaemonStartupEntrypointResultPayload
  | DaemonSupervisorHandoffEntrypointResultPayload
  | DaemonTerminalErrorEntrypointResultPayload
  | DaemonTerminalStatusEntrypointResultPayload
  | DaemonCleanTerminalEvidenceEntrypointResultPayload
  | DaemonWatcherBackendEntrypointResultPayload
  | DaemonWatcherWaitEntrypointResultPayload
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

export function runDaemonPromptRouteEntrypoint(
  payload: DaemonPromptRouteEntrypointPayload
): DaemonPromptRouteEntrypointResultPayload {
  return {
    entrypoint: "daemon_prompt_route_decision",
    ...daemonPromptRouteDecision({
      hasAgentsConfig: parseBoolean(
        payload.has_agents_config,
        "has_agents_config"
      ),
      requestClass: parseRequestClass(payload.request_class),
      hasGoalFile: parseBoolean(payload.has_goal_file, "has_goal_file")
    })
  };
}

export function runDaemonRequestClassEntrypoint(
  payload: DaemonRequestClassEntrypointPayload
): DaemonRequestClassEntrypointResultPayload {
  return {
    entrypoint: "daemon_request_class_decision",
    ...daemonRequestClassDecision({
      promptText: parseString(payload.prompt_text, "prompt_text"),
      workflowState:
        payload.workflow_state === null || payload.workflow_state === undefined
          ? null
          : parseRecord(payload.workflow_state, "workflow_state")
    })
  };
}

export function runDaemonPromptLifecycleEntrypoint(
  payload: DaemonPromptLifecycleEntrypointPayload
): DaemonPromptLifecycleEntrypointResultPayload {
  return {
    entrypoint: "daemon_prompt_lifecycle_decision",
    ...daemonPromptLifecycleDecision({
      promptPath: parseRequiredString(payload.prompt_path, "prompt_path"),
      resultPath: parseRequiredString(payload.result_path, "result_path"),
      promptExists: parseBoolean(payload.prompt_exists, "prompt_exists")
    })
  };
}

export function runDaemonPromptPathEntrypoint(
  payload: DaemonPromptPathEntrypointPayload
): DaemonPromptPathEntrypointResultPayload {
  return {
    entrypoint: "daemon_prompt_path_decision",
    ...daemonPromptPathDecision({
      promptPath: parseRequiredString(payload.prompt_path, "prompt_path"),
      resultPathRoot: parseRequiredString(
        payload.result_path_root,
        "result_path_root"
      )
    })
  };
}

export function runDaemonPromptSessionEntrypoint(
  payload: DaemonPromptSessionEntrypointPayload
): DaemonPromptSessionEntrypointResultPayload {
  return {
    entrypoint: "daemon_prompt_session_decision",
    ...daemonPromptSessionDecision({
      promptName: parseRequiredString(payload.prompt_name, "prompt_name"),
      promptText: parseString(payload.prompt_text, "prompt_text")
    })
  };
}

export function runDaemonPromptProcessingMetadataEntrypoint(
  payload: DaemonPromptProcessingMetadataEntrypointPayload
): DaemonPromptProcessingMetadataEntrypointResultPayload {
  return {
    entrypoint: "daemon_prompt_processing_metadata_decision",
    ...daemonPromptProcessingMetadataDecision({
      promptName: parseRequiredString(payload.prompt_name, "prompt_name"),
      promptText: parseString(payload.prompt_text, "prompt_text"),
      watcherBackend: parseRequiredString(
        payload.watcher_backend,
        "watcher_backend"
      ),
      resultPath: parseRequiredString(payload.result_path, "result_path")
    })
  };
}

export function runDaemonPlanStateEntrypoint(
  payload: DaemonPlanStateEntrypointPayload
): DaemonPlanStateEntrypointResultPayload {
  return {
    entrypoint: "daemon_plan_state_decision",
    ...daemonPlanStateDecision({
      requestClass: parseRequiredString(payload.request_class, "request_class"),
      taskSync:
        payload.task_sync === null || payload.task_sync === undefined
          ? null
          : parseRecord(payload.task_sync, "task_sync")
    })
  };
}

export function runDaemonArtifactWriterEntrypoint(
  payload: DaemonArtifactWriterEntrypointPayload
): DaemonArtifactWriterEntrypointResultPayload {
  return {
    entrypoint: "daemon_artifact_writer_decision",
    ...daemonArtifactWriterDecision({
      baseDir: parseRequiredString(payload.base_dir, "base_dir"),
      logsDir: parseOptionalString(payload.logs_dir, "logs_dir") ?? null,
      runId: parseOptionalString(payload.run_id, "run_id") ?? null,
      sessionId: parseOptionalString(payload.session_id, "session_id") ?? null
    })
  };
}

export function runDaemonArtifactPersistedEventEntrypoint(
  payload: DaemonArtifactPersistedEventEntrypointPayload
): DaemonArtifactPersistedEventEntrypointResultPayload {
  return {
    entrypoint: "daemon_artifact_persisted_event_decision",
    ...daemonArtifactPersistedEventDecision({
      artifactKind: parseRequiredString(payload.artifact_kind, "artifact_kind")
    })
  };
}

export function runDaemonSupervisorHandoffEntrypoint(
  payload: DaemonSupervisorHandoffEntrypointPayload
): DaemonSupervisorHandoffEntrypointResultPayload {
  return {
    entrypoint: "daemon_supervisor_handoff_decision",
    ...daemonSupervisorHandoffDecision({
      fromRole: parseRequiredString(payload.from_role, "from_role"),
      toRole: parseRequiredString(payload.to_role, "to_role"),
      attempt: parseNumber(payload.attempt, "attempt")
    })
  };
}

export function runDaemonRunLifecycleEventEntrypoint(
  payload: DaemonRunLifecycleEventEntrypointPayload
): DaemonRunLifecycleEventEntrypointResultPayload {
  return {
    entrypoint: "daemon_run_lifecycle_event_decision",
    ...daemonRunLifecycleEventDecision({
      eventKind: parseRunLifecycleEventKind(payload.event_kind),
      promptSummary:
        parseOptionalString(payload.prompt_summary, "prompt_summary") ?? null
    })
  };
}

export function runDaemonPromptSummaryEntrypoint(
  payload: DaemonPromptSummaryEntrypointPayload
): DaemonPromptSummaryEntrypointResultPayload {
  return {
    entrypoint: "daemon_prompt_summary_decision",
    ...daemonPromptSummaryDecision({
      promptText: parseString(payload.prompt_text, "prompt_text")
    })
  };
}

export function runDaemonResultReportEntrypoint(
  payload: DaemonResultReportEntrypointPayload
): DaemonResultReportEntrypointResultPayload {
  return {
    entrypoint: "daemon_result_report_decision",
    ...daemonResultReportDecision({
      promptPath: parseRequiredString(payload.prompt_path, "prompt_path"),
      resultPath: parseRequiredString(payload.result_path, "result_path"),
      promptExists: parseBoolean(payload.prompt_exists, "prompt_exists"),
      daemonRunId: parseOptionalString(
        payload.daemon_run_id,
        "daemon_run_id"
      ) ?? null,
      latestRunId: parseOptionalString(
        payload.latest_run_id,
        "latest_run_id"
      ) ?? null,
      sessionId: parseOptionalString(payload.session_id, "session_id") ?? null
    })
  };
}

export function runDaemonResultReportFallbackEntrypoint(
  payload: DaemonResultReportFallbackEntrypointPayload
): DaemonResultReportFallbackEntrypointResultPayload {
  return {
    entrypoint: "daemon_result_report_fallback_decision",
    ...daemonResultReportFallbackDecision({
      promptName: parseRequiredString(payload.prompt_name, "prompt_name"),
      existingError:
        parseOptionalString(payload.existing_error, "existing_error") ?? null,
      cause: parseString(payload.cause, "cause")
    })
  };
}

export function runDaemonResultMarkdownEntrypoint(
  payload: DaemonResultMarkdownEntrypointPayload
): DaemonResultMarkdownEntrypointResultPayload {
  return {
    entrypoint: "daemon_result_markdown_projection",
    ...daemonResultMarkdownProjection({
      result: parseRecord(payload.result, "result"),
      generatedAt: parseRequiredString(payload.generated_at, "generated_at")
    })
  };
}

export function runDaemonResultReportAuthoringEntrypoint(
  payload: DaemonResultReportAuthoringEntrypointPayload
): DaemonResultReportAuthoringEntrypointResultPayload {
  return {
    entrypoint: "daemon_result_report_authoring_decision",
    ...daemonResultReportAuthoringDecision({
      result: parseRecord(payload.result, "result"),
      generatedAt: parseRequiredString(payload.generated_at, "generated_at"),
      runtimePathsText: parseString(
        payload.runtime_paths_text,
        "runtime_paths_text"
      ),
      cliPath: parseOptionalString(payload.cli_path, "cli_path") ?? null,
      repoRoot: parseRequiredString(payload.repo_root, "repo_root")
    })
  };
}

export function runDaemonResultReportAuthoredOutputEntrypoint(
  payload: DaemonResultReportAuthoredOutputEntrypointPayload
): DaemonResultReportAuthoredOutputEntrypointResultPayload {
  return {
    entrypoint: "daemon_result_report_authored_output_decision",
    ...daemonResultReportAuthoredOutputDecision({
      stdoutText: parseOptionalString(payload.stdout_text, "stdout_text") ?? null,
      stderrText: parseOptionalString(payload.stderr_text, "stderr_text") ?? null,
      generatedAt: parseRequiredString(payload.generated_at, "generated_at"),
      promptName: parseRequiredString(payload.prompt_name, "prompt_name")
    })
  };
}

export function runDaemonResultArtifactRefEntrypoint(
  payload: DaemonResultArtifactRefEntrypointPayload
): DaemonResultArtifactRefEntrypointResultPayload {
  return {
    entrypoint: "daemon_result_artifact_ref_decision",
    ...daemonResultArtifactRefDecision({
      resultPath: parseRequiredString(payload.result_path, "result_path"),
      resultExists: parseBoolean(payload.result_exists, "result_exists"),
      createdAt: parseOptionalString(payload.created_at, "created_at") ?? null,
      daemonRunId: parseOptionalString(
        payload.daemon_run_id,
        "daemon_run_id"
      ) ?? null,
      latestRunId: parseOptionalString(
        payload.latest_run_id,
        "latest_run_id"
      ) ?? null,
      sessionId: parseOptionalString(payload.session_id, "session_id") ?? null
    })
  };
}

export function runDaemonRunFinishedEntrypoint(
  payload: DaemonRunFinishedEntrypointPayload
): DaemonRunFinishedEntrypointResultPayload {
  return {
    entrypoint: "daemon_run_finished_decision",
    ...daemonRunFinishedDecision({
      attemptsCompleted: parseOptionalNumber(
        payload.attempts_completed,
        "attempts_completed"
      ) ?? null,
      retriesUsed: parseOptionalNumber(payload.retries_used, "retries_used") ?? null,
      supervisorVerdict: parseOptionalString(
        payload.supervisor_verdict,
        "supervisor_verdict"
      ) ?? null,
      outcome: parseRequiredString(payload.outcome, "outcome"),
      error: parseOptionalString(payload.error, "error") ?? null
    })
  };
}

export function runDaemonPromptCompletionLineEntrypoint(
  payload: DaemonPromptCompletionLineEntrypointPayload
): DaemonPromptCompletionLineEntrypointResultPayload {
  return {
    entrypoint: "daemon_prompt_completion_line_decision",
    ...daemonPromptCompletionLineDecision({
      promptName: parseRequiredString(payload.prompt_name, "prompt_name"),
      status: parseRequiredString(payload.status, "status"),
      resultPath: parseRequiredString(payload.result_path, "result_path")
    })
  };
}

export function runDaemonPromptInterruptionEntrypoint(
  payload: DaemonPromptInterruptionEntrypointPayload
): DaemonPromptInterruptionEntrypointResultPayload {
  return {
    entrypoint: "daemon_prompt_interruption_decision",
    ...daemonPromptInterruptionDecision({
      promptName: parseRequiredString(payload.prompt_name, "prompt_name")
    })
  };
}

export function runDaemonRoadmapPhaseEntrypoint(
  payload: DaemonRoadmapPhaseEntrypointPayload
): DaemonRoadmapPhaseEntrypointResultPayload {
  return {
    entrypoint: "daemon_roadmap_phase_decision",
    ...daemonRoadmapPhaseDecision({
      activePhaseIds: Array.isArray(payload.active_phase_ids)
        ? payload.active_phase_ids
        : []
    })
  };
}

export function runDaemonGoalSourceEntrypoint(
  payload: DaemonGoalSourceEntrypointPayload
): DaemonGoalSourceEntrypointResultPayload {
  return {
    entrypoint: "daemon_goal_source_decision",
    ...daemonGoalSourceDecision({
      promptText: parseRequiredString(payload.prompt_text, "prompt_text")
    })
  };
}

export function runDaemonAgentCliEntrypoint(
  payload: DaemonAgentCliEntrypointPayload
): DaemonAgentCliEntrypointResultPayload {
  return {
    entrypoint: "daemon_agent_cli_decision",
    ...daemonAgentCliDecision({
      activeAgentCli:
        parseOptionalString(payload.active_agent_cli, "active_agent_cli") ?? null
    })
  };
}

export function runDaemonTerminalErrorEntrypoint(
  payload: DaemonTerminalErrorEntrypointPayload
): DaemonTerminalErrorEntrypointResultPayload {
  return {
    entrypoint: "daemon_terminal_error_decision",
    ...daemonTerminalErrorDecision({
      status: parseRequiredString(payload.status, "status"),
      nextPendingTask:
        parseOptionalString(payload.next_pending_task, "next_pending_task") ?? null
    })
  };
}

export function runDaemonTerminalStatusEntrypoint(
  payload: DaemonTerminalStatusEntrypointPayload
): DaemonTerminalStatusEntrypointResultPayload {
  return {
    entrypoint: "daemon_terminal_status_decision",
    ...daemonTerminalStatusDecision({
      status: parseRequiredString(payload.status, "status"),
      planAllCompleted:
        payload.plan_all_completed === null || payload.plan_all_completed === undefined
          ? null
          : parseBoolean(payload.plan_all_completed, "plan_all_completed"),
      hasCleanTerminalStageEvidence: parseBoolean(
        payload.has_clean_terminal_stage_evidence,
        "has_clean_terminal_stage_evidence"
      ),
      nextPendingTask:
        parseOptionalString(payload.next_pending_task, "next_pending_task") ?? null
    })
  };
}

export function runDaemonCleanTerminalEvidenceEntrypoint(
  payload: DaemonCleanTerminalEvidenceEntrypointPayload
): DaemonCleanTerminalEvidenceEntrypointResultPayload {
  return {
    entrypoint: "daemon_clean_terminal_evidence_decision",
    ...daemonCleanTerminalEvidenceDecision({
      runResult: parseRecord(
        payload.run_result,
        "run_result"
      ) as unknown as RunResult
    })
  };
}

export function runDaemonExistingResultEntrypoint(
  payload: DaemonExistingResultEntrypointPayload
): DaemonExistingResultEntrypointResultPayload {
  return {
    entrypoint: "daemon_existing_result_decision",
    ...daemonExistingResultDecision({
      promptPath: parseRequiredString(payload.prompt_path, "prompt_path"),
      resultPath: parseRequiredString(payload.result_path, "result_path"),
      resultExists: parseBoolean(payload.result_exists, "result_exists"),
      existingResultStatus: parseOptionalString(
        payload.existing_result_status,
        "existing_result_status"
      ) ?? null
    })
  };
}

export function runDaemonResultStatusEntrypoint(
  payload: DaemonResultStatusEntrypointPayload
): DaemonResultStatusEntrypointResultPayload {
  return {
    entrypoint: "daemon_result_status_decision",
    ...daemonResultStatusDecision({
      resultText: parseString(payload.result_text, "result_text")
    })
  };
}

export function runDaemonPromptSettleEntrypoint(
  payload: DaemonPromptSettleEntrypointPayload
): DaemonPromptSettleEntrypointResultPayload {
  return {
    entrypoint: "daemon_prompt_settle_decision",
    ...daemonPromptSettleDecision({
      promptPath: parseRequiredString(payload.prompt_path, "prompt_path"),
      settleSeconds: parseNumber(payload.settle_seconds, "settle_seconds"),
      ageSeconds: parseNumber(payload.age_seconds, "age_seconds")
    })
  };
}

export function runDaemonQueueFileEntrypoint(
  payload: DaemonQueueFileEntrypointPayload
): DaemonQueueFileEntrypointResultPayload {
  return {
    entrypoint: "daemon_queue_file_decision",
    ...daemonQueueFileDecision({
      promptPath: parseRequiredString(payload.prompt_path, "prompt_path"),
      inProgress: parseBoolean(payload.in_progress, "in_progress"),
      promptCandidate: parseBoolean(payload.prompt_candidate, "prompt_candidate")
    })
  };
}

export function runDaemonLoopIterationEntrypoint(
  payload: DaemonLoopIterationEntrypointPayload
): DaemonLoopIterationEntrypointResultPayload {
  return {
    entrypoint: "daemon_loop_iteration_decision",
    ...daemonLoopIterationDecision({
      processedCount: parseNumber(payload.processed_count, "processed_count"),
      inProgressCount: parseNumber(
        payload.in_progress_count,
        "in_progress_count"
      ),
      shutdownRequested: parseBoolean(
        payload.shutdown_requested,
        "shutdown_requested"
      )
    })
  };
}

export function runDaemonStartupEntrypoint(
  payload: DaemonStartupEntrypointPayload
): DaemonStartupEntrypointResultPayload {
  return {
    entrypoint: "daemon_startup_decision",
    ...daemonStartupDecision({
      goalsSchedulerConfigured: parseBoolean(
        payload.goals_scheduler_configured,
        "goals_scheduler_configured"
      ),
      autonomousSchedulerConfigured: parseBoolean(
        payload.autonomous_scheduler_configured,
        "autonomous_scheduler_configured"
      )
    })
  };
}

export function runDaemonStartupBannerEntrypoint(
  payload: DaemonStartupBannerEntrypointPayload
): DaemonStartupBannerEntrypointResultPayload {
  return {
    entrypoint: "daemon_startup_banner_decision",
    ...daemonStartupBannerDecision({
      repoRoot: parseRequiredString(payload.repo_root, "repo_root"),
      configPath: parseRequiredString(payload.config_path, "config_path"),
      promptPath: parseRequiredString(payload.prompt_path, "prompt_path"),
      resultPath: parseRequiredString(payload.result_path, "result_path"),
      watcherBackend: parseRequiredString(
        payload.watcher_backend,
        "watcher_backend"
      ),
      requestedWatcherBackend: parseRequiredString(
        payload.requested_watcher_backend,
        "requested_watcher_backend"
      ),
      pollIntervalSeconds: parseNumber(
        payload.poll_interval_seconds,
        "poll_interval_seconds"
      ),
      settleSeconds: parseNumber(
        payload.settle_seconds,
        "settle_seconds"
      ),
      ignoreHiddenFiles: parseBoolean(
        payload.ignore_hidden_files,
        "ignore_hidden_files"
      ),
      allowedExtensions: Array.isArray(payload.allowed_extensions)
        ? payload.allowed_extensions.filter(
            (item): item is string => typeof item === "string"
          )
        : [],
      goalsPath: parseOptionalString(payload.goals_path, "goals_path") ?? null,
      goalsIntervalMinutes: parseOptionalNumber(
        payload.goals_interval_minutes,
        "goals_interval_minutes"
      ) ?? null,
      autonomousEnabled: parseBoolean(
        payload.autonomous_enabled,
        "autonomous_enabled"
      ),
      autonomousIntervalMinutes: parseOptionalNumber(
        payload.autonomous_interval_minutes,
        "autonomous_interval_minutes"
      ) ?? null,
      autonomousFocus: parseOptionalString(
        payload.autonomous_focus,
        "autonomous_focus"
      ) ?? null,
      autonomousMaxQueuedTasks: parseOptionalNumber(
        payload.autonomous_max_queued_tasks,
        "autonomous_max_queued_tasks"
      ) ?? null
    })
  };
}

export function runDaemonShutdownEntrypoint(
  payload: DaemonShutdownEntrypointPayload
): DaemonShutdownEntrypointResultPayload {
  return {
    entrypoint: "daemon_shutdown_decision",
    ...daemonShutdownDecision({
      goalsSchedulerConfigured: parseBoolean(
        payload.goals_scheduler_configured,
        "goals_scheduler_configured"
      ),
      autonomousSchedulerConfigured: parseBoolean(
        payload.autonomous_scheduler_configured,
        "autonomous_scheduler_configured"
      ),
      progressLogActive: parseBoolean(
        payload.progress_log_active,
        "progress_log_active"
      )
    })
  };
}

export function runDaemonInstanceLockEntrypoint(
  payload: DaemonInstanceLockEntrypointPayload
): DaemonInstanceLockEntrypointResultPayload {
  return {
    entrypoint: "daemon_instance_lock_decision",
    ...daemonInstanceLockDecision({
      fcntlAvailable: parseBoolean(
        payload.fcntl_available,
        "fcntl_available"
      ),
      lockAcquired: parseBoolean(payload.lock_acquired, "lock_acquired"),
      promptPath: parseRequiredString(payload.prompt_path, "prompt_path"),
      existingPid: parseOptionalString(payload.existing_pid, "existing_pid") ?? null
    })
  };
}

export function runDaemonInstanceUnlockEntrypoint(
  payload: DaemonInstanceUnlockEntrypointPayload
): DaemonInstanceUnlockEntrypointResultPayload {
  return {
    entrypoint: "daemon_instance_unlock_decision",
    ...daemonInstanceUnlockDecision({
      fcntlAvailable: parseBoolean(
        payload.fcntl_available,
        "fcntl_available"
      ),
      lockHeld: parseBoolean(payload.lock_held, "lock_held")
    })
  };
}

export function runDaemonHeartbeatWriteEntrypoint(
  payload: DaemonHeartbeatWriteEntrypointPayload
): DaemonHeartbeatWriteEntrypointResultPayload {
  return {
    entrypoint: "daemon_heartbeat_write_decision",
    ...daemonHeartbeatWriteDecision({
      heartbeatPathConfigured: parseBoolean(
        payload.heartbeat_path_configured,
        "heartbeat_path_configured"
      ),
      pid: parseNumber(payload.pid, "pid"),
      status: parseHeartbeatStatus(payload.status),
      timestamp: parseRequiredString(payload.timestamp, "timestamp")
    })
  };
}

export function runDaemonHeartbeatRemoveEntrypoint(
  payload: DaemonHeartbeatRemoveEntrypointPayload
): DaemonHeartbeatRemoveEntrypointResultPayload {
  return {
    entrypoint: "daemon_heartbeat_remove_decision",
    ...daemonHeartbeatRemoveDecision({
      heartbeatPathConfigured: parseBoolean(
        payload.heartbeat_path_configured,
        "heartbeat_path_configured"
      )
    })
  };
}

export function runDaemonWatcherBackendEntrypoint(
  payload: DaemonWatcherBackendEntrypointPayload
): DaemonWatcherBackendEntrypointResultPayload {
  return {
    entrypoint: "daemon_watcher_backend_decision",
    ...daemonWatcherBackendDecision({
      requestedBackend: parseWatcherBackend(payload.requested_backend),
      inotifyAvailable: parseBoolean(
        payload.inotify_available,
        "inotify_available"
      )
    })
  };
}

export function runDaemonWatcherWaitEntrypoint(
  payload: DaemonWatcherWaitEntrypointPayload
): DaemonWatcherWaitEntrypointResultPayload {
  return {
    entrypoint: "daemon_watcher_wait_decision",
    ...daemonWatcherWaitDecision({
      waitRequested: parseBoolean(payload.wait_requested, "wait_requested"),
      shutdownRequested: parseBoolean(
        payload.shutdown_requested,
        "shutdown_requested"
      ),
      watcherBackend: parseRequiredString(
        payload.watcher_backend,
        "watcher_backend"
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

function parseRequestClass(value: unknown): RequestClass {
  if (
    value !== "direct_response" &&
    value !== "planning_only" &&
    value !== "light_edit" &&
    value !== "full_workflow"
  ) {
    throw new Error("request_class must be a supported request class");
  }
  return value;
}

function parseHeartbeatStatus(value: unknown): DaemonHeartbeatStatus {
  if (value !== "busy" && value !== "idle") {
    throw new Error("status must be busy or idle");
  }
  return value;
}

function parseWatcherBackend(value: unknown): DaemonWatcherBackend {
  if (value !== "auto" && value !== "inotify" && value !== "polling") {
    throw new Error("requested_backend must be auto, inotify, or polling");
  }
  return value;
}

function parseRunLifecycleEventKind(value: unknown): "requested" | "started" {
  if (value !== "requested" && value !== "started") {
    throw new Error("event_kind must be requested or started");
  }
  return value;
}

function parseStringArray(value: unknown, fieldName: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new Error(`${fieldName} must be a JSON array of strings`);
  }
  return value;
}

function parseRecord(
  value: unknown,
  fieldName: string
): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${fieldName} must be a JSON object`);
  }
  return value as Record<string, unknown>;
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
