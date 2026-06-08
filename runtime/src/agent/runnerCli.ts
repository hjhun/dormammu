#!/usr/bin/env node
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import { Writable } from "node:stream";

import {
  runDaemonAgentCliEntrypoint,
  runDaemonExistingResultEntrypoint,
  runDaemonGoalSourceEntrypoint,
  runDaemonHeartbeatRemoveEntrypoint,
  runDaemonHeartbeatWriteEntrypoint,
  runDaemonInstanceLockEntrypoint,
  runDaemonInstanceUnlockEntrypoint,
  runDaemonLoopIterationEntrypoint,
  runDaemonPlanStateEntrypoint,
  runDaemonPendingDecisionEntrypoint,
  runDaemonPromptLifecycleEntrypoint,
  runDaemonPromptPathEntrypoint,
  runDaemonPromptRouteEntrypoint,
  runDaemonPromptSettleEntrypoint,
  runDaemonQueueFileEntrypoint,
  runDaemonResultArtifactRefEntrypoint,
  runDaemonResultMarkdownEntrypoint,
  runDaemonResultReportFallbackEntrypoint,
  runDaemonResultReportEntrypoint,
  runDaemonResultStatusEntrypoint,
  runDaemonRoadmapPhaseEntrypoint,
  runDaemonRunFinishedEntrypoint,
  runDaemonShutdownEntrypoint,
  runDaemonStartupBannerEntrypoint,
  runDaemonStartupEntrypoint,
  runDaemonTerminalErrorEntrypoint,
  runDaemonTerminalStatusEntrypoint,
  runDaemonWatcherBackendEntrypoint,
  runDaemonWatcherWaitEntrypoint,
  runAgentRunnerEntrypoint,
  runGoalsProcessDecisionEntrypoint,
  runGoalsPromptProjectionEntrypoint,
  runGoalsQueueEntrypoint,
  runGoalsRoleDocumentProjectionEntrypoint,
  runGoalsRoleSequenceEntrypoint,
  runGoalsSingleGoalDecisionEntrypoint,
  runGoalsTimerDecisionEntrypoint,
  runGoalsTimerFiredDecisionEntrypoint,
  runGoalsTriggerDecisionEntrypoint,
  runGoalsWatcherStartDecisionEntrypoint,
  runGoalsWatcherStopDecisionEntrypoint,
  runGoalsWatchLoopDecisionEntrypoint,
  type AgentRunnerEntrypointPayload,
  type DaemonAgentCliEntrypointPayload,
  type DaemonExistingResultEntrypointPayload,
  type DaemonGoalSourceEntrypointPayload,
  type DaemonHeartbeatRemoveEntrypointPayload,
  type DaemonHeartbeatWriteEntrypointPayload,
  type DaemonInstanceLockEntrypointPayload,
  type DaemonInstanceUnlockEntrypointPayload,
  type DaemonLoopIterationEntrypointPayload,
  type DaemonPlanStateEntrypointPayload,
  type DaemonPendingDecisionEntrypointPayload,
  type DaemonPromptLifecycleEntrypointPayload,
  type DaemonPromptPathEntrypointPayload,
  type DaemonPromptRouteEntrypointPayload,
  type DaemonPromptSettleEntrypointPayload,
  type DaemonQueueFileEntrypointPayload,
  type DaemonResultArtifactRefEntrypointPayload,
  type DaemonResultMarkdownEntrypointPayload,
  type DaemonResultReportFallbackEntrypointPayload,
  type DaemonResultReportEntrypointPayload,
  type DaemonResultStatusEntrypointPayload,
  type DaemonRoadmapPhaseEntrypointPayload,
  type DaemonRunFinishedEntrypointPayload,
  type DaemonShutdownEntrypointPayload,
  type DaemonStartupBannerEntrypointPayload,
  type DaemonStartupEntrypointPayload,
  type DaemonTerminalErrorEntrypointPayload,
  type DaemonTerminalStatusEntrypointPayload,
  type DaemonWatcherBackendEntrypointPayload,
  type DaemonWatcherWaitEntrypointPayload,
  type GoalsProcessDecisionEntrypointPayload,
  type GoalsPromptProjectionEntrypointPayload,
  type GoalsRoleDocumentProjectionEntrypointPayload,
  type GoalsRoleSequenceEntrypointPayload,
  type GoalsSingleGoalDecisionEntrypointPayload,
  type GoalsTimerDecisionEntrypointPayload,
  type GoalsTimerFiredDecisionEntrypointPayload,
  type GoalsTriggerDecisionEntrypointPayload,
  type GoalsWatcherStartDecisionEntrypointPayload,
  type GoalsWatcherStopDecisionEntrypointPayload,
  type GoalsWatchLoopDecisionEntrypointPayload,
  type RunnerCliPayload,
  type RunnerCliResultPayload
} from "./runnerEntrypoint.js";
import type { AgentRunStarted } from "./runArtifacts.js";
import { agentRunStartedToDict } from "./runArtifacts.js";

const USAGE = [
  "Usage: dormammu-agent-runner [payload.json|-]",
  "",
  "Reads an agent runner JSON payload from stdin by default and writes the",
  "Python-compatible run result JSON to stdout."
].join("\n");

export async function runAgentRunnerCli(args: string[] = process.argv.slice(2)): Promise<number> {
  try {
    if (args.length === 1 && (args[0] === "--help" || args[0] === "-h")) {
      process.stdout.write(`${USAGE}\n`);
      return 0;
    }
    const payload = await readPayload(args);
    const eventStream = isAgentRunPayload(payload) && payload.event_stream === true
      ? new RunnerEventStream()
      : null;
    const abortController = new AbortController();
    const result = await runWithSignalHandlers(payload, eventStream, abortController);
    process.stdout.write(`${JSON.stringify(result)}\n`);
    return 0;
  } catch (error) {
    process.stderr.write(`dormammu-agent-runner: ${formatError(error)}\n`);
    return 1;
  }
}

async function runWithSignalHandlers(
  payload: RunnerCliPayload,
  eventStream: RunnerEventStream | null,
  abortController: AbortController
): Promise<RunnerCliResultPayload> {
  if (isGoalsPromptProjectionPayload(payload)) {
    return runGoalsPromptProjectionEntrypoint(payload);
  }
  if (isGoalsRoleDocumentProjectionPayload(payload)) {
    return runGoalsRoleDocumentProjectionEntrypoint(payload);
  }
  if (isGoalsRoleSequencePayload(payload)) {
    return runGoalsRoleSequenceEntrypoint(payload);
  }
  if (isGoalsTimerDecisionPayload(payload)) {
    return runGoalsTimerDecisionEntrypoint(payload);
  }
  if (isGoalsTriggerDecisionPayload(payload)) {
    return runGoalsTriggerDecisionEntrypoint(payload);
  }
  if (isGoalsProcessDecisionPayload(payload)) {
    return runGoalsProcessDecisionEntrypoint(payload);
  }
  if (isGoalsTimerFiredDecisionPayload(payload)) {
    return runGoalsTimerFiredDecisionEntrypoint(payload);
  }
  if (isGoalsSingleGoalDecisionPayload(payload)) {
    return runGoalsSingleGoalDecisionEntrypoint(payload);
  }
  if (isGoalsWatcherStartDecisionPayload(payload)) {
    return runGoalsWatcherStartDecisionEntrypoint(payload);
  }
  if (isGoalsWatcherStopDecisionPayload(payload)) {
    return runGoalsWatcherStopDecisionEntrypoint(payload);
  }
  if (isGoalsWatchLoopDecisionPayload(payload)) {
    return runGoalsWatchLoopDecisionEntrypoint(payload);
  }
  if (isDaemonHeartbeatWritePayload(payload)) {
    return runDaemonHeartbeatWriteEntrypoint(payload);
  }
  if (isDaemonHeartbeatRemovePayload(payload)) {
    return runDaemonHeartbeatRemoveEntrypoint(payload);
  }
  if (isDaemonWatcherBackendPayload(payload)) {
    return runDaemonWatcherBackendEntrypoint(payload);
  }
  if (isDaemonWatcherWaitPayload(payload)) {
    return runDaemonWatcherWaitEntrypoint(payload);
  }
  if (isDaemonInstanceLockPayload(payload)) {
    return runDaemonInstanceLockEntrypoint(payload);
  }
  if (isDaemonInstanceUnlockPayload(payload)) {
    return runDaemonInstanceUnlockEntrypoint(payload);
  }
  if (isDaemonLoopIterationPayload(payload)) {
    return runDaemonLoopIterationEntrypoint(payload);
  }
  if (isDaemonStartupPayload(payload)) {
    return runDaemonStartupEntrypoint(payload);
  }
  if (isDaemonShutdownPayload(payload)) {
    return runDaemonShutdownEntrypoint(payload);
  }
  if (isDaemonPendingDecisionPayload(payload)) {
    return runDaemonPendingDecisionEntrypoint(payload);
  }
  if (isDaemonPromptLifecyclePayload(payload)) {
    return runDaemonPromptLifecycleEntrypoint(payload);
  }
  if (isDaemonPromptPathPayload(payload)) {
    return runDaemonPromptPathEntrypoint(payload);
  }
  if (isDaemonPlanStatePayload(payload)) {
    return runDaemonPlanStateEntrypoint(payload);
  }
  if (isDaemonPromptRoutePayload(payload)) {
    return runDaemonPromptRouteEntrypoint(payload);
  }
  if (isDaemonPromptSettlePayload(payload)) {
    return runDaemonPromptSettleEntrypoint(payload);
  }
  if (isDaemonQueueFilePayload(payload)) {
    return runDaemonQueueFileEntrypoint(payload);
  }
  if (isDaemonResultArtifactRefPayload(payload)) {
    return runDaemonResultArtifactRefEntrypoint(payload);
  }
  if (isDaemonResultMarkdownPayload(payload)) {
    return runDaemonResultMarkdownEntrypoint(payload);
  }
  if (isDaemonResultReportFallbackPayload(payload)) {
    return runDaemonResultReportFallbackEntrypoint(payload);
  }
  if (isDaemonResultReportPayload(payload)) {
    return runDaemonResultReportEntrypoint(payload);
  }
  if (isDaemonResultStatusPayload(payload)) {
    return runDaemonResultStatusEntrypoint(payload);
  }
  if (isDaemonRoadmapPhasePayload(payload)) {
    return runDaemonRoadmapPhaseEntrypoint(payload);
  }
  if (isDaemonGoalSourcePayload(payload)) {
    return runDaemonGoalSourceEntrypoint(payload);
  }
  if (isDaemonAgentCliPayload(payload)) {
    return runDaemonAgentCliEntrypoint(payload);
  }
  if (isDaemonRunFinishedPayload(payload)) {
    return runDaemonRunFinishedEntrypoint(payload);
  }
  if (isDaemonStartupBannerPayload(payload)) {
    return runDaemonStartupBannerEntrypoint(payload);
  }
  if (isDaemonTerminalErrorPayload(payload)) {
    return runDaemonTerminalErrorEntrypoint(payload);
  }
  if (isDaemonTerminalStatusPayload(payload)) {
    return runDaemonTerminalStatusEntrypoint(payload);
  }
  if (isDaemonExistingResultPayload(payload)) {
    return runDaemonExistingResultEntrypoint(payload);
  }
  if (!isAgentRunPayload(payload)) {
    return runGoalsQueueEntrypoint(payload);
  }
  const shutdownHandler = (): void => {
    eventStream?.writeEvent({ type: "aborted" });
    abortController.abort();
  };
  process.once("SIGINT", shutdownHandler);
  process.once("SIGTERM", shutdownHandler);
  try {
    return await runAgentRunnerEntrypoint(payload, {
      abortSignal: abortController.signal,
      liveOutput: eventStream?.outputWriter ?? null,
      onStarted: eventStream
        ? (started: AgentRunStarted): void => {
            eventStream.writeEvent({
              type: "started",
              started: agentRunStartedToDict(started, {
                includeHelpText: payload.include_help_text ?? true
              })
            });
          }
        : undefined
    });
  } finally {
    process.removeListener("SIGINT", shutdownHandler);
    process.removeListener("SIGTERM", shutdownHandler);
  }
}

async function readPayload(args: string[]): Promise<RunnerCliPayload> {
  if (args.length > 1) {
    throw new Error("expected at most one payload path argument");
  }

  const source = args[0] ?? "-";
  const text = source === "-" ? await readStdin() : await readFile(source, "utf8");
  try {
    return JSON.parse(text) as RunnerCliPayload;
  } catch (error) {
    throw new Error(`Invalid JSON payload: ${formatError(error)}`);
  }
}

function isAgentRunPayload(payload: RunnerCliPayload): payload is AgentRunnerEntrypointPayload {
  return (
    !("entrypoint" in payload) ||
    (payload.entrypoint !== "daemon_existing_result_decision" &&
      payload.entrypoint !== "daemon_heartbeat_remove_decision" &&
      payload.entrypoint !== "daemon_heartbeat_write_decision" &&
      payload.entrypoint !== "daemon_instance_lock_decision" &&
      payload.entrypoint !== "daemon_instance_unlock_decision" &&
      payload.entrypoint !== "daemon_loop_iteration_decision" &&
      payload.entrypoint !== "daemon_pending_decision" &&
      payload.entrypoint !== "daemon_plan_state_decision" &&
      payload.entrypoint !== "daemon_prompt_lifecycle_decision" &&
      payload.entrypoint !== "daemon_prompt_path_decision" &&
      payload.entrypoint !== "daemon_prompt_route_decision" &&
      payload.entrypoint !== "daemon_prompt_settle_decision" &&
      payload.entrypoint !== "daemon_queue_file_decision" &&
      payload.entrypoint !== "daemon_result_artifact_ref_decision" &&
      payload.entrypoint !== "daemon_result_markdown_projection" &&
      payload.entrypoint !== "daemon_result_report_fallback_decision" &&
      payload.entrypoint !== "daemon_result_report_decision" &&
      payload.entrypoint !== "daemon_result_status_decision" &&
      payload.entrypoint !== "daemon_roadmap_phase_decision" &&
      payload.entrypoint !== "daemon_goal_source_decision" &&
      payload.entrypoint !== "daemon_agent_cli_decision" &&
      payload.entrypoint !== "daemon_run_finished_decision" &&
      payload.entrypoint !== "daemon_shutdown_decision" &&
      payload.entrypoint !== "daemon_startup_banner_decision" &&
      payload.entrypoint !== "daemon_startup_decision" &&
      payload.entrypoint !== "daemon_terminal_error_decision" &&
      payload.entrypoint !== "daemon_terminal_status_decision" &&
      payload.entrypoint !== "daemon_watcher_backend_decision" &&
      payload.entrypoint !== "daemon_watcher_wait_decision" &&
      payload.entrypoint !== "goals_queue" &&
      payload.entrypoint !== "goals_prompt_projection" &&
      payload.entrypoint !== "goals_role_document_projection" &&
      payload.entrypoint !== "goals_role_sequence" &&
      payload.entrypoint !== "goals_timer_decision" &&
      payload.entrypoint !== "goals_trigger_decision" &&
      payload.entrypoint !== "goals_process_decision" &&
      payload.entrypoint !== "goals_timer_fired_decision" &&
      payload.entrypoint !== "goals_single_goal_decision" &&
      payload.entrypoint !== "goals_watcher_start_decision" &&
      payload.entrypoint !== "goals_watcher_stop_decision" &&
      payload.entrypoint !== "goals_watch_loop_decision")
  );
}

function isDaemonHeartbeatWritePayload(
  payload: RunnerCliPayload
): payload is DaemonHeartbeatWriteEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "daemon_heartbeat_write_decision"
  );
}

function isDaemonHeartbeatRemovePayload(
  payload: RunnerCliPayload
): payload is DaemonHeartbeatRemoveEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "daemon_heartbeat_remove_decision"
  );
}

function isDaemonInstanceLockPayload(
  payload: RunnerCliPayload
): payload is DaemonInstanceLockEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "daemon_instance_lock_decision"
  );
}

function isDaemonInstanceUnlockPayload(
  payload: RunnerCliPayload
): payload is DaemonInstanceUnlockEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "daemon_instance_unlock_decision"
  );
}

function isDaemonWatcherBackendPayload(
  payload: RunnerCliPayload
): payload is DaemonWatcherBackendEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "daemon_watcher_backend_decision"
  );
}

function isDaemonWatcherWaitPayload(
  payload: RunnerCliPayload
): payload is DaemonWatcherWaitEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "daemon_watcher_wait_decision"
  );
}

function isDaemonPendingDecisionPayload(
  payload: RunnerCliPayload
): payload is DaemonPendingDecisionEntrypointPayload {
  return (
    "entrypoint" in payload && payload.entrypoint === "daemon_pending_decision"
  );
}

function isDaemonLoopIterationPayload(
  payload: RunnerCliPayload
): payload is DaemonLoopIterationEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "daemon_loop_iteration_decision"
  );
}

function isDaemonStartupPayload(
  payload: RunnerCliPayload
): payload is DaemonStartupEntrypointPayload {
  return (
    "entrypoint" in payload && payload.entrypoint === "daemon_startup_decision"
  );
}

function isDaemonShutdownPayload(
  payload: RunnerCliPayload
): payload is DaemonShutdownEntrypointPayload {
  return (
    "entrypoint" in payload && payload.entrypoint === "daemon_shutdown_decision"
  );
}

function isDaemonPromptRoutePayload(
  payload: RunnerCliPayload
): payload is DaemonPromptRouteEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "daemon_prompt_route_decision"
  );
}

function isDaemonPromptLifecyclePayload(
  payload: RunnerCliPayload
): payload is DaemonPromptLifecycleEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "daemon_prompt_lifecycle_decision"
  );
}

function isDaemonPromptPathPayload(
  payload: RunnerCliPayload
): payload is DaemonPromptPathEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "daemon_prompt_path_decision"
  );
}

function isDaemonPlanStatePayload(
  payload: RunnerCliPayload
): payload is DaemonPlanStateEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "daemon_plan_state_decision"
  );
}

function isDaemonResultReportPayload(
  payload: RunnerCliPayload
): payload is DaemonResultReportEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "daemon_result_report_decision"
  );
}

function isDaemonResultArtifactRefPayload(
  payload: RunnerCliPayload
): payload is DaemonResultArtifactRefEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "daemon_result_artifact_ref_decision"
  );
}

function isDaemonResultMarkdownPayload(
  payload: RunnerCliPayload
): payload is DaemonResultMarkdownEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "daemon_result_markdown_projection"
  );
}

function isDaemonResultReportFallbackPayload(
  payload: RunnerCliPayload
): payload is DaemonResultReportFallbackEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "daemon_result_report_fallback_decision"
  );
}

function isDaemonRoadmapPhasePayload(
  payload: RunnerCliPayload
): payload is DaemonRoadmapPhaseEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "daemon_roadmap_phase_decision"
  );
}

function isDaemonGoalSourcePayload(
  payload: RunnerCliPayload
): payload is DaemonGoalSourceEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "daemon_goal_source_decision"
  );
}

function isDaemonAgentCliPayload(
  payload: RunnerCliPayload
): payload is DaemonAgentCliEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "daemon_agent_cli_decision"
  );
}

function isDaemonStartupBannerPayload(
  payload: RunnerCliPayload
): payload is DaemonStartupBannerEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "daemon_startup_banner_decision"
  );
}

function isDaemonPromptSettlePayload(
  payload: RunnerCliPayload
): payload is DaemonPromptSettleEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "daemon_prompt_settle_decision"
  );
}

function isDaemonQueueFilePayload(
  payload: RunnerCliPayload
): payload is DaemonQueueFileEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "daemon_queue_file_decision"
  );
}

function isDaemonRunFinishedPayload(
  payload: RunnerCliPayload
): payload is DaemonRunFinishedEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "daemon_run_finished_decision"
  );
}

function isDaemonResultStatusPayload(
  payload: RunnerCliPayload
): payload is DaemonResultStatusEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "daemon_result_status_decision"
  );
}

function isDaemonExistingResultPayload(
  payload: RunnerCliPayload
): payload is DaemonExistingResultEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "daemon_existing_result_decision"
  );
}

function isDaemonTerminalErrorPayload(
  payload: RunnerCliPayload
): payload is DaemonTerminalErrorEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "daemon_terminal_error_decision"
  );
}

function isDaemonTerminalStatusPayload(
  payload: RunnerCliPayload
): payload is DaemonTerminalStatusEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "daemon_terminal_status_decision"
  );
}

function isGoalsPromptProjectionPayload(
  payload: RunnerCliPayload
): payload is GoalsPromptProjectionEntrypointPayload {
  return "entrypoint" in payload && payload.entrypoint === "goals_prompt_projection";
}

function isGoalsRoleDocumentProjectionPayload(
  payload: RunnerCliPayload
): payload is GoalsRoleDocumentProjectionEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "goals_role_document_projection"
  );
}

function isGoalsRoleSequencePayload(
  payload: RunnerCliPayload
): payload is GoalsRoleSequenceEntrypointPayload {
  return "entrypoint" in payload && payload.entrypoint === "goals_role_sequence";
}

function isGoalsTimerDecisionPayload(
  payload: RunnerCliPayload
): payload is GoalsTimerDecisionEntrypointPayload {
  return "entrypoint" in payload && payload.entrypoint === "goals_timer_decision";
}

function isGoalsTriggerDecisionPayload(
  payload: RunnerCliPayload
): payload is GoalsTriggerDecisionEntrypointPayload {
  return "entrypoint" in payload && payload.entrypoint === "goals_trigger_decision";
}

function isGoalsProcessDecisionPayload(
  payload: RunnerCliPayload
): payload is GoalsProcessDecisionEntrypointPayload {
  return "entrypoint" in payload && payload.entrypoint === "goals_process_decision";
}

function isGoalsTimerFiredDecisionPayload(
  payload: RunnerCliPayload
): payload is GoalsTimerFiredDecisionEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "goals_timer_fired_decision"
  );
}

function isGoalsSingleGoalDecisionPayload(
  payload: RunnerCliPayload
): payload is GoalsSingleGoalDecisionEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "goals_single_goal_decision"
  );
}

function isGoalsWatcherStartDecisionPayload(
  payload: RunnerCliPayload
): payload is GoalsWatcherStartDecisionEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "goals_watcher_start_decision"
  );
}

function isGoalsWatcherStopDecisionPayload(
  payload: RunnerCliPayload
): payload is GoalsWatcherStopDecisionEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "goals_watcher_stop_decision"
  );
}

function isGoalsWatchLoopDecisionPayload(
  payload: RunnerCliPayload
): payload is GoalsWatchLoopDecisionEntrypointPayload {
  return (
    "entrypoint" in payload &&
    payload.entrypoint === "goals_watch_loop_decision"
  );
}

async function readStdin(): Promise<string> {
  let text = "";
  process.stdin.setEncoding("utf8");
  for await (const chunk of process.stdin) {
    text += chunk;
  }
  return text;
}

function formatError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

class RunnerEventStream {
  readonly outputWriter = new Writable({
    write: (chunk, _encoding, callback) => {
      this.writeEvent({
        type: "output",
        data: Buffer.isBuffer(chunk)
          ? chunk.toString("base64")
          : Buffer.from(String(chunk)).toString("base64")
      });
      callback();
    }
  });

  writeEvent(payload: Record<string, unknown>): void {
    process.stderr.write(`DORMAMMU_EVENT ${JSON.stringify(payload)}\n`);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  runAgentRunnerCli().then((exitCode) => {
    if (process.exitCode === undefined) {
      process.exitCode = exitCode;
    }
  });
}
