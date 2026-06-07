import assert from "node:assert/strict";
import path from "node:path";
import test from "node:test";

import type { CliCapabilities } from "./commandBuilder.js";
import {
  agentRunResultToDict,
  agentRunStartedToDict,
  runMetadataPath,
  runPromptPath,
  runStderrPath,
  runStdoutPath
} from "./runArtifacts.js";

const capabilities: CliCapabilities = {
  helpFlag: "--help",
  promptFileFlag: "--prompt-file",
  promptArgFlag: "--prompt",
  workdirFlag: "--cwd",
  helpText: "usage: fake",
  helpExitCode: 0,
  commandPrefix: ["run"]
};

test("run artifact path helpers match Python naming", () => {
  const logsDir = path.join("/repo", ".dev", "logs");
  assert.equal(runPromptPath(logsDir, "run-1"), path.join(logsDir, "run-1.prompt.txt"));
  assert.equal(runStdoutPath(logsDir, "run-1"), path.join(logsDir, "run-1.stdout.log"));
  assert.equal(runStderrPath(logsDir, "run-1"), path.join(logsDir, "run-1.stderr.log"));
  assert.equal(runMetadataPath(logsDir, "run-1"), path.join(logsDir, "run-1.meta.json"));
});

test("agentRunStartedToDict emits Python-compatible payload and artifact refs", () => {
  const logsDir = path.join("/repo", ".dev", "logs");
  const payload = agentRunStartedToDict(
    {
      runId: "run-1",
      cliPath: "/bin/fake-agent",
      workdir: "/repo",
      promptMode: "file",
      command: ["/bin/fake-agent", "--prompt-file", runPromptPath(logsDir, "run-1")],
      startedAt: "2026-04-25T00:00:00+00:00",
      promptPath: runPromptPath(logsDir, "run-1"),
      stdoutPath: runStdoutPath(logsDir, "run-1"),
      stderrPath: runStderrPath(logsDir, "run-1"),
      metadataPath: runMetadataPath(logsDir, "run-1"),
      capabilities
    },
    { includeHelpText: true }
  );

  assert.equal(payload.run_id, "run-1");
  assert.equal(payload.cli_path, "/bin/fake-agent");
  assert.equal(payload.prompt_mode, "file");
  assert.deepEqual(payload.artifacts, {
    prompt: runPromptPath(logsDir, "run-1"),
    stdout: runStdoutPath(logsDir, "run-1"),
    stderr: runStderrPath(logsDir, "run-1"),
    metadata: runMetadataPath(logsDir, "run-1")
  });
  assert.deepEqual(payload.artifact_refs, [
    {
      kind: "prompt",
      path: runPromptPath(logsDir, "run-1"),
      label: "prompt",
      content_type: "text/plain",
      created_at: "2026-04-25T00:00:00+00:00",
      run_id: "run-1",
      role: null,
      stage_name: null,
      session_id: null,
      metadata: {}
    },
    {
      kind: "stdout",
      path: runStdoutPath(logsDir, "run-1"),
      label: "stdout",
      content_type: "text/plain",
      created_at: "2026-04-25T00:00:00+00:00",
      run_id: "run-1",
      role: null,
      stage_name: null,
      session_id: null,
      metadata: {}
    },
    {
      kind: "stderr",
      path: runStderrPath(logsDir, "run-1"),
      label: "stderr",
      content_type: "text/plain",
      created_at: "2026-04-25T00:00:00+00:00",
      run_id: "run-1",
      role: null,
      stage_name: null,
      session_id: null,
      metadata: {}
    },
    {
      kind: "metadata",
      path: runMetadataPath(logsDir, "run-1"),
      label: "metadata",
      content_type: "application/json",
      created_at: "2026-04-25T00:00:00+00:00",
      run_id: "run-1",
      role: null,
      stage_name: null,
      session_id: null,
      metadata: {}
    }
  ]);
  assert.deepEqual(payload.capabilities, {
    help_flag: "--help",
    prompt_file_flag: "--prompt-file",
    prompt_arg_flag: "--prompt",
    workdir_flag: "--cwd",
    help_text: "usage: fake",
    help_exit_code: 0,
    command_prefix: ["run"],
    prompt_positional: false,
    preset: null,
    auto_approve: {
      supported: false,
      requires_confirmation: false,
      candidates: [],
      notes: []
    }
  });
});

test("agentRunResultToDict includes fallback and completion metadata", () => {
  const logsDir = path.join("/repo", ".dev", "logs");
  const payload = agentRunResultToDict({
    runId: "run-2",
    cliPath: "/bin/fallback-agent",
    requestedCliPath: "/bin/requested-agent",
    attemptedCliPaths: ["/bin/requested-agent", "/bin/fallback-agent"],
    fallbackTrigger: "non-zero exit code 1",
    timedOut: true,
    workdir: "/repo",
    promptMode: "stdin",
    command: ["/bin/fallback-agent"],
    exitCode: -1,
    startedAt: "2026-04-25T00:00:00+00:00",
    completedAt: "2026-04-25T00:01:00+00:00",
    promptPath: runPromptPath(logsDir, "run-2"),
    stdoutPath: runStdoutPath(logsDir, "run-2"),
    stderrPath: runStderrPath(logsDir, "run-2"),
    metadataPath: runMetadataPath(logsDir, "run-2"),
    capabilities
  });

  assert.equal(payload.run_id, "run-2");
  assert.equal(payload.cli_path, "/bin/fallback-agent");
  assert.equal(payload.requested_cli_path, "/bin/requested-agent");
  assert.deepEqual(payload.attempted_cli_paths, ["/bin/requested-agent", "/bin/fallback-agent"]);
  assert.equal(payload.fallback_trigger, "non-zero exit code 1");
  assert.equal(payload.timed_out, true);
  assert.equal(payload.exit_code, -1);
  assert.equal(payload.completed_at, "2026-04-25T00:01:00+00:00");
  assert.equal(payload.artifact_refs[0].created_at, "2026-04-25T00:01:00+00:00");
});
