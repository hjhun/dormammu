import path from "node:path";

import type { AutoApproveInfo, CliCapabilities, CommandPlan } from "./commandBuilder.js";

export type ArtifactRefPayload = {
  kind: string;
  path: string;
  label: string | null;
  content_type: string | null;
  created_at: string | null;
  run_id: string | null;
  role: string | null;
  stage_name: string | null;
  session_id: string | null;
  metadata: Record<string, unknown>;
};

export type CliCapabilitiesPayload = {
  help_flag: string;
  prompt_file_flag: string | null;
  prompt_arg_flag: string | null;
  workdir_flag: string | null;
  help_text?: string;
  help_exit_code: number;
  command_prefix: string[];
  prompt_positional: boolean;
  preset: {
    key: string | null;
    label: string | null;
    source: string | null;
  } | null;
  auto_approve: {
    supported: boolean;
    requires_confirmation: boolean;
    candidates: Array<{
      value: string;
      risk: string;
      source: string;
      summary: string;
    }>;
    notes: string[];
  };
};

export type AgentRunStarted = {
  runId: string;
  cliPath: string;
  workdir: string;
  promptMode: CommandPlan["promptMode"];
  command: readonly string[];
  startedAt: string;
  promptPath: string;
  stdoutPath: string;
  stderrPath: string;
  metadataPath: string;
  capabilities: CliCapabilities;
};

export type AgentRunStartedPayload = {
  run_id: string;
  cli_path: string;
  workdir: string;
  prompt_mode: string;
  command: string[];
  started_at: string;
  artifacts: Record<"prompt" | "stdout" | "stderr" | "metadata", string>;
  artifact_refs: ArtifactRefPayload[];
  capabilities: CliCapabilitiesPayload;
};

export type AgentRunResult = AgentRunStarted & {
  exitCode: number;
  completedAt: string;
  requestedCliPath?: string | null;
  attemptedCliPaths?: readonly string[];
  fallbackTrigger?: string | null;
  timedOut?: boolean;
};

export type AgentRunResultPayload = AgentRunStartedPayload & {
  requested_cli_path: string;
  attempted_cli_paths: string[];
  fallback_trigger: string | null;
  timed_out: boolean;
  exit_code: number;
  completed_at: string;
};

export function runPromptPath(logsDir: string, runId: string): string {
  return path.join(logsDir, `${runId}.prompt.txt`);
}

export function runStdoutPath(logsDir: string, runId: string): string {
  return path.join(logsDir, `${runId}.stdout.log`);
}

export function runStderrPath(logsDir: string, runId: string): string {
  return path.join(logsDir, `${runId}.stderr.log`);
}

export function runMetadataPath(logsDir: string, runId: string): string {
  return path.join(logsDir, `${runId}.meta.json`);
}

export function capabilitiesToDict(
  capabilities: CliCapabilities,
  options: { includeHelpText?: boolean } = {}
): CliCapabilitiesPayload {
  const payload: CliCapabilitiesPayload = {
    help_flag: capabilities.helpFlag,
    prompt_file_flag: capabilities.promptFileFlag,
    prompt_arg_flag: capabilities.promptArgFlag,
    workdir_flag: capabilities.workdirFlag,
    help_exit_code: capabilities.helpExitCode,
    command_prefix: [...(capabilities.commandPrefix ?? [])],
    prompt_positional: capabilities.promptPositional ?? false,
    preset:
      capabilities.presetKey !== null && capabilities.presetKey !== undefined
        ? {
            key: capabilities.presetKey,
            label: capabilities.presetLabel ?? null,
            source: capabilities.presetSource ?? null
          }
        : null,
    auto_approve: autoApproveToDict(capabilities.autoApprove)
  };
  if (options.includeHelpText) {
    payload.help_text = capabilities.helpText;
  }
  return payload;
}

function autoApproveToDict(
  autoApprove: AutoApproveInfo | undefined
): CliCapabilitiesPayload["auto_approve"] {
  if (autoApprove === undefined) {
    return {
      supported: false,
      requires_confirmation: false,
      candidates: [],
      notes: []
    };
  }
  return {
    supported: autoApprove.supported,
    requires_confirmation: autoApprove.requiresConfirmation,
    candidates: autoApprove.candidates.map((candidate) => ({
      value: candidate.value,
      risk: candidate.risk,
      source: candidate.source,
      summary: candidate.summary
    })),
    notes: [...autoApprove.notes]
  };
}

export function agentRunArtifactRefs(options: {
  runId: string;
  createdAt: string;
  promptPath: string;
  stdoutPath: string;
  stderrPath: string;
  metadataPath: string;
}): ArtifactRefPayload[] {
  return [
    artifactRef("prompt", options.promptPath, "prompt", "text/plain", options),
    artifactRef("stdout", options.stdoutPath, "stdout", "text/plain", options),
    artifactRef("stderr", options.stderrPath, "stderr", "text/plain", options),
    artifactRef("metadata", options.metadataPath, "metadata", "application/json", options)
  ];
}

export function agentRunStartedToDict(
  started: AgentRunStarted,
  options: { includeHelpText?: boolean } = {}
): AgentRunStartedPayload {
  return {
    run_id: started.runId,
    cli_path: started.cliPath,
    workdir: started.workdir,
    prompt_mode: started.promptMode,
    command: [...started.command],
    started_at: started.startedAt,
    artifacts: artifactPaths(started),
    artifact_refs: agentRunArtifactRefs({
      runId: started.runId,
      createdAt: started.startedAt,
      promptPath: started.promptPath,
      stdoutPath: started.stdoutPath,
      stderrPath: started.stderrPath,
      metadataPath: started.metadataPath
    }),
    capabilities: capabilitiesToDict(started.capabilities, options)
  };
}

export function agentRunResultToDict(
  result: AgentRunResult,
  options: { includeHelpText?: boolean } = {}
): AgentRunResultPayload {
  return {
    ...agentRunStartedToDict(
      {
        runId: result.runId,
        cliPath: result.cliPath,
        workdir: result.workdir,
        promptMode: result.promptMode,
        command: result.command,
        startedAt: result.startedAt,
        promptPath: result.promptPath,
        stdoutPath: result.stdoutPath,
        stderrPath: result.stderrPath,
        metadataPath: result.metadataPath,
        capabilities: result.capabilities
      },
      options
    ),
    requested_cli_path: result.requestedCliPath ?? result.cliPath,
    attempted_cli_paths: [...(result.attemptedCliPaths ?? [result.cliPath])],
    fallback_trigger: result.fallbackTrigger ?? null,
    timed_out: result.timedOut ?? false,
    exit_code: result.exitCode,
    completed_at: result.completedAt,
    artifact_refs: agentRunArtifactRefs({
      runId: result.runId,
      createdAt: result.completedAt,
      promptPath: result.promptPath,
      stdoutPath: result.stdoutPath,
      stderrPath: result.stderrPath,
      metadataPath: result.metadataPath
    })
  };
}

function artifactPaths(run: AgentRunStarted): Record<"prompt" | "stdout" | "stderr" | "metadata", string> {
  return {
    prompt: run.promptPath,
    stdout: run.stdoutPath,
    stderr: run.stderrPath,
    metadata: run.metadataPath
  };
}

function artifactRef(
  kind: string,
  artifactPath: string,
  label: string,
  contentType: string,
  options: { runId: string; createdAt: string }
): ArtifactRefPayload {
  return {
    kind,
    path: artifactPath,
    label,
    content_type: contentType,
    created_at: options.createdAt,
    run_id: options.runId,
    role: null,
    stage_name: null,
    session_id: null,
    metadata: {}
  };
}
