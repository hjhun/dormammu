import assert from "node:assert/strict";
import { chmod, mkdir, mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import test from "node:test";

const runnerCliPath = fileURLToPath(new URL("./runnerCli.js", import.meta.url));

test("dormammu-agent-runner reads stdin payloads and writes result JSON", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-runner-cli-"));
  const fakeCli = path.join(root, "fake-agent.cjs");
  await writeFile(
    fakeCli,
    [
      "#!/usr/bin/env node",
      "if (process.argv.includes('--help')) {",
      "  console.log('usage: fake-agent');",
      "  process.exit(0);",
      "}",
      "let text = '';",
      "process.stdin.setEncoding('utf8');",
      "process.stdin.on('data', (chunk) => { text += chunk; });",
      "process.stdin.on('end', () => { console.log(`agent saw: ${text.trim()}`); });",
      ""
    ].join("\n"),
    "utf8"
  );
  await chmod(fakeCli, 0o755);

  const payload = {
    config: {
      active_agent_cli: fakeCli
    },
    request: {
      prompt_text: "Run via CLI.",
      repo_root: root,
      input_mode: "stdin",
      run_label: "cli-entrypoint"
    },
    logs_dir: path.join(root, ".dev", "logs"),
    include_help_text: false
  };

  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify(payload),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");

  const result = JSON.parse(completed.stdout) as {
    exit_code: number;
    cli_path: string;
    prompt_mode: string;
    artifacts: { stdout: string };
    capabilities: { help_text?: string };
  };
  assert.equal(result.exit_code, 0);
  assert.equal(result.cli_path, fakeCli);
  assert.equal(result.prompt_mode, "stdin");
  assert.equal(result.capabilities.help_text, undefined);
  assert.match(await readFile(result.artifacts.stdout, "utf8"), /Run via CLI\./);
});

test("dormammu-agent-runner can emit structured started and output events", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-runner-events-"));
  const fakeCli = path.join(root, "fake-agent.cjs");
  await writeFile(
    fakeCli,
    [
      "#!/usr/bin/env node",
      "if (process.argv.includes('--help')) {",
      "  console.log('usage: fake-agent');",
      "  process.exit(0);",
      "}",
      "let text = '';",
      "process.stdin.setEncoding('utf8');",
      "process.stdin.on('data', (chunk) => { text += chunk; });",
      "process.stdin.on('end', () => { console.log(`event prompt: ${text.trim()}`); });",
      ""
    ].join("\n"),
    "utf8"
  );
  await chmod(fakeCli, 0o755);

  const payload = {
    config: {
      active_agent_cli: fakeCli
    },
    request: {
      prompt_text: "Stream events.",
      repo_root: root,
      input_mode: "stdin",
      run_label: "cli-events"
    },
    logs_dir: path.join(root, ".dev", "logs"),
    include_help_text: false,
    event_stream: true
  };

  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify(payload),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  const events = completed.stderr
    .trim()
    .split("\n")
    .filter(Boolean)
    .map((line) => {
      assert.match(line, /^DORMAMMU_EVENT /);
      return JSON.parse(line.slice("DORMAMMU_EVENT ".length)) as {
        type: string;
        data?: string;
        started?: { run_id: string };
      };
  });
  assert.equal(events[0].type, "started");
  assert.match(events[0].started?.run_id ?? "", /cli-events$/);
  const output = events
    .filter((event) => event.type === "output")
    .map((event) => Buffer.from(event.data ?? "", "base64").toString("utf8"))
    .join("");
  assert.match(output, /Stream events\./);

  const result = JSON.parse(completed.stdout) as { run_id: string; exit_code: number };
  assert.equal(result.run_id, events[0].started?.run_id);
  assert.equal(result.exit_code, 0);
});

test("dormammu-agent-runner can project goals queue payloads", async () => {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-runner-goals-"));
  const goalsPath = path.join(root, "goals");
  const promptPath = path.join(root, "prompts");
  await mkdir(goalsPath);
  await mkdir(promptPath);
  await writeFile(path.join(goalsPath, "goal.md"), "Goal", "utf8");
  await writeFile(path.join(promptPath, "20260412_goal.md"), "queued", "utf8");

  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "goals_queue",
      goals_path: goalsPath,
      prompt_path: promptPath,
      date_text: "20260412"
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  const result = JSON.parse(completed.stdout) as {
    entrypoint: string;
    goal_files: Array<{ name: string }>;
    candidates: Array<{ queuedPromptName: string; alreadyQueued: boolean }>;
  };
  assert.equal(result.entrypoint, "goals_queue");
  assert.deepEqual(result.goal_files, [
    {
      path: path.join(goalsPath, "goal.md"),
      name: "goal.md",
      stem: "goal"
    }
  ]);
  assert.deepEqual(result.candidates, [
    {
      path: path.join(goalsPath, "goal.md"),
      name: "goal.md",
      stem: "goal",
      queuedPromptName: "20260412_goal.md",
      alreadyQueued: true
    }
  ]);
});

test("dormammu-agent-runner can project goals prompt payloads", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "goals_prompt_projection",
      goal_file_path: "/repo/goals/ship-it.md",
      generated_prompt: "# Goal\n\nShip it",
      date_text: "20260412"
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "goals_prompt_projection",
    stem: "ship-it",
    filename: "20260412_ship-it.md",
    content: "<!-- dormammu:goal_source=/repo/goals/ship-it.md -->\n\n# Goal\n\nShip it"
  });
});

test("dormammu-agent-runner can project goals role document payloads", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "goals_role_document_projection",
      logs_dir: "/repo/.dev/logs",
      date_text: "20260412",
      role: "designer",
      stem: "ship-it",
      output: "Design output"
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "goals_role_document_projection",
    filename: "20260412_designer_ship-it.md",
    path: "/repo/.dev/logs/20260412_designer_ship-it.md",
    content: "# Designer \u2014 ship-it\n\nDesign output"
  });
});

test("dormammu-agent-runner can project goals role sequence payloads", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "goals_role_sequence",
      goal_text: "Ship it",
      analysis_text: "Analysis output",
      roles: {
        planner: { cli: "planner-cli", model: "careful" }
      }
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  const result = JSON.parse(completed.stdout) as {
    entrypoint: string;
    next_step: {
      role: string;
      cli: string;
      model: string;
      prompt: string;
    };
  };
  assert.equal(result.entrypoint, "goals_role_sequence");
  assert.equal(result.next_step.role, "planner");
  assert.equal(result.next_step.cli, "planner-cli");
  assert.equal(result.next_step.model, "careful");
  assert.match(result.next_step.prompt, /# Requirements Analysis/);
});

test("dormammu-agent-runner can project goals timer decision payloads", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "goals_timer_decision",
      has_goal_files: false,
      timer_active: true,
      interval_minutes: 7
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "goals_timer_decision",
    action: "cancel",
    intervalSeconds: null,
    reason: "no_goal_files_with_active_timer"
  });
});

test("dormammu-agent-runner can project goals trigger decision payloads", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "goals_trigger_decision",
      stop_requested: false,
      has_goal_files: true
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "goals_trigger_decision",
    action: "process",
    cancelTimerBeforeProcess: true,
    syncTimerAfterProcess: true,
    reason: "goal_files_present"
  });
});

test("dormammu-agent-runner can project goals process decision payloads", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "goals_process_decision",
      stop_requested: false,
      goal_file_count: 2
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "goals_process_decision",
    action: "process",
    goalFileCount: 2,
    reason: "goal_files_present"
  });
});

test("dormammu-agent-runner can project goals timer fired decision payloads", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "goals_timer_fired_decision",
      stop_requested: false
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "goals_timer_fired_decision",
    action: "process",
    clearTimerBeforeProcess: true,
    syncTimerAfterProcess: true,
    reason: "timer_fired"
  });
});

test("dormammu-agent-runner can project goals single goal decision payloads", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "goals_single_goal_decision",
      prompt_exists: true
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "goals_single_goal_decision",
    action: "skip",
    reason: "queued_prompt_exists"
  });
});

test("dormammu-agent-runner can project goals watcher start payloads", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "goals_watcher_start_decision",
      watcher_active: false
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "goals_watcher_start_decision",
    action: "start",
    threadName: "dormammu-goals-watcher",
    daemon: true,
    reason: "watcher_start_requested"
  });
});

test("dormammu-agent-runner can project goals watcher stop payloads", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "goals_watcher_stop_decision",
      timer_active: false
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "goals_watcher_stop_decision",
    action: "stop",
    setStopEvent: true,
    cancelTimer: true,
    reason: "stop_requested_without_active_timer"
  });
});

test("dormammu-agent-runner can project goals watch loop payloads", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "goals_watch_loop_decision",
      stop_requested: false,
      poll_seconds: 30
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "goals_watch_loop_decision",
    action: "sync",
    waitSeconds: 30,
    reason: "watcher_poll"
  });
});

test("dormammu-agent-runner can project daemon pending decisions", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "daemon_pending_decision",
      processed_count: 0,
      ready_prompt_paths: [
        "/repo/prompts/001-first.md",
        "/repo/prompts/002-second.md"
      ],
      retry_after_seconds: null
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "daemon_pending_decision",
    action: "process",
    promptPath: "/repo/prompts/001-first.md",
    queuedPromptNames: ["002-second.md"],
    retryAfterSeconds: null,
    reason: "ready_prompt_available"
  });
});

test("dormammu-agent-runner can project daemon prompt route decisions", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "daemon_prompt_route_decision",
      has_agents_config: false,
      request_class: "full_workflow",
      has_goal_file: true
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "daemon_prompt_route_decision",
    action: "prelude_then_loop",
    runner: "loop",
    requiresAgentCli: true,
    runRefineAndPlanPrelude: true,
    enablePlanEvaluator: true,
    useGoalsEvaluatorConfig: false,
    reason: "full_workflow_requires_supervised_loop"
  });
});

test("dormammu-agent-runner can project daemon prompt lifecycle decisions", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "daemon_prompt_lifecycle_decision",
      prompt_path: "/repo/prompts/001-first.md",
      result_path: "/repo/results/001-first_RESULT.md",
      prompt_exists: false
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "daemon_prompt_lifecycle_decision",
    action: "skip",
    status: "skipped",
    promptPath: "/repo/prompts/001-first.md",
    resultPath: "/repo/results/001-first_RESULT.md",
    removeExistingResult: false,
    errorMessage: "Prompt file was deleted before processing.",
    reason: "prompt_missing"
  });
});

test("dormammu-agent-runner can project daemon prompt path decisions", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "daemon_prompt_path_decision",
      prompt_path: "/repo/prompts/001-first.md",
      result_path_root: "/repo/results"
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "daemon_prompt_path_decision",
    promptStem: "001-first",
    resultPath: "/repo/results/001-first_RESULT.md",
    progressLogPath: "/repo/progress/001-first_progress.log",
    reason: "prompt_paths_projected"
  });
});

test("dormammu-agent-runner can project daemon result report decisions", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "daemon_result_report_decision",
      prompt_path: "/repo/prompts/001-first.md",
      result_path: "/repo/results/001-first_RESULT.md",
      prompt_exists: true,
      daemon_run_id: "daemon:run-1",
      latest_run_id: "agent:run-1",
      session_id: "session-1"
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "daemon_result_report_decision",
    action: "publish",
    writeReport: true,
    removePrompt: true,
    promptPath: "/repo/prompts/001-first.md",
    resultPath: "/repo/results/001-first_RESULT.md",
    artifactKind: "result_report",
    artifactLabel: "result_report",
    contentType: "text/markdown",
    runId: "daemon:run-1",
    role: "daemon",
    stageName: "daemon",
    sessionId: "session-1",
    reason: "publish_and_remove_prompt"
  });
});

test("dormammu-agent-runner can project daemon result artifact refs", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "daemon_result_artifact_ref_decision",
      result_path: "/repo/results/001-first_RESULT.md",
      result_exists: true,
      created_at: "2026-06-08T04:00:00+00:00",
      daemon_run_id: "daemon:run-1",
      latest_run_id: "agent:run-1",
      session_id: "session-1"
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "daemon_result_artifact_ref_decision",
    action: "reference",
    artifactRef: {
      kind: "result_report",
      path: "/repo/results/001-first_RESULT.md",
      label: "result_report",
      contentType: "text/markdown",
      createdAt: "2026-06-08T04:00:00+00:00",
      runId: "daemon:run-1",
      role: "daemon",
      stageName: "daemon",
      sessionId: "session-1"
    },
    reason: "result_report_referenced"
  });
});

test("dormammu-agent-runner can project daemon run-finished decisions", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "daemon_run_finished_decision",
      attempts_completed: 2.8,
      retries_used: 1,
      supervisor_verdict: "approved",
      outcome: "completed",
      error: null
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "daemon_run_finished_decision",
    source: "daemon_runner",
    runEntrypoint: "DaemonRunner._process_prompt",
    attemptsCompleted: 2,
    retriesUsed: 1,
    supervisorVerdict: "approved",
    outcome: "completed",
    error: null,
    reason: "daemon_run_finished"
  });
});

test("dormammu-agent-runner can project daemon roadmap phase decisions", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "daemon_roadmap_phase_decision",
      active_phase_ids: ["", "phase_7"]
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "daemon_roadmap_phase_decision",
    expectedRoadmapPhaseId: "phase_7",
    reason: "active_phase_selected"
  });
});

test("dormammu-agent-runner can project daemon goal-source decisions", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "daemon_goal_source_decision",
      prompt_text: [
        "<!-- dormammu:goal_source=/repo/goals/ship-it.md -->",
        "",
        "# Goal"
      ].join("\n")
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "daemon_goal_source_decision",
    goalSourcePath: "/repo/goals/ship-it.md",
    reason: "goal_source_found"
  });
});

test("dormammu-agent-runner can project daemon agent CLI decisions", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "daemon_agent_cli_decision",
      active_agent_cli: null
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "daemon_agent_cli_decision",
    action: "error",
    agentCli: null,
    errorMessage: [
      "daemonize requires active_agent_cli in dormammu.json or ~/.dormammu/config. ",
      "It now reuses the normal dormammu run loop instead of per-phase daemon CLI settings."
    ].join(""),
    reason: "active_agent_cli_missing"
  });
});

test("dormammu-agent-runner can project daemon terminal error decisions", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "daemon_terminal_error_decision",
      status: "failed",
      next_pending_task: "Phase 4. Review"
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "daemon_terminal_error_decision",
    status: "failed",
    nextPendingTask: "Phase 4. Review",
    message: [
      "Loop retry budget was exhausted before PLAN.md completed.",
      " Next pending PLAN task: Phase 4. Review."
    ].join(""),
    reason: "retry_budget_exhausted"
  });
});

test("dormammu-agent-runner can project daemon terminal status decisions", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "daemon_terminal_status_decision",
      status: "completed",
      plan_all_completed: false,
      has_clean_terminal_stage_evidence: true,
      next_pending_task: "Phase 4. Review"
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "daemon_terminal_status_decision",
    status: "completed",
    error: null,
    preserveCompleted: true,
    reason: "clean_terminal_stage_evidence"
  });
});

test("dormammu-agent-runner can project daemon existing result decisions", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "daemon_existing_result_decision",
      prompt_path: "/repo/prompts/001-first.md",
      result_path: "/repo/results/001-first_RESULT.md",
      result_exists: true,
      existing_result_status: "completed"
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "daemon_existing_result_decision",
    action: "remove",
    removeExistingResult: true,
    promptPath: "/repo/prompts/001-first.md",
    resultPath: "/repo/results/001-first_RESULT.md",
    existingResultStatus: "completed",
    reason: "completed_result_reprocess"
  });
});

test("dormammu-agent-runner can project daemon result status decisions", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "daemon_result_status_decision",
      result_text: "# Result\n\n- Status: `blocked`\n"
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "daemon_result_status_decision",
    status: "blocked",
    reason: "status_line_found"
  });
});

test("dormammu-agent-runner can project daemon prompt settle decisions", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "daemon_prompt_settle_decision",
      prompt_path: "/repo/prompts/001-first.md",
      settle_seconds: 4,
      age_seconds: 1.25
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "daemon_prompt_settle_decision",
    action: "defer",
    promptPath: "/repo/prompts/001-first.md",
    retryAfterSeconds: 2.75,
    reason: "settle_window_pending"
  });
});

test("dormammu-agent-runner can project daemon queue file decisions", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "daemon_queue_file_decision",
      prompt_path: "/repo/prompts/readme.txt",
      in_progress: false,
      prompt_candidate: false
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "daemon_queue_file_decision",
    action: "skip",
    promptPath: "/repo/prompts/readme.txt",
    reason: "not_prompt_candidate"
  });
});

test("dormammu-agent-runner can project daemon loop iteration decisions", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "daemon_loop_iteration_decision",
      processed_count: 1,
      in_progress_count: 0,
      shutdown_requested: false
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "daemon_loop_iteration_decision",
    action: "continue",
    heartbeatStatus: "idle",
    waitForChanges: false,
    reason: "prompt_processed"
  });
});

test("dormammu-agent-runner can project daemon startup decisions", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "daemon_startup_decision",
      goals_scheduler_configured: true,
      autonomous_scheduler_configured: true
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "daemon_startup_decision",
    action: "start",
    initialHeartbeatStatus: "idle",
    startGoalsScheduler: true,
    triggerGoalsScheduler: true,
    startAutonomousScheduler: true,
    triggerAutonomousScheduler: true,
    reason: "daemon_startup"
  });
});

test("dormammu-agent-runner can project daemon startup banner decisions", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "daemon_startup_banner_decision",
      repo_root: "/repo",
      config_path: "/repo/daemonize.json",
      prompt_path: "/repo/prompts",
      result_path: "/repo/results",
      watcher_backend: "polling",
      requested_watcher_backend: "auto",
      poll_interval_seconds: 30,
      settle_seconds: 2,
      ignore_hidden_files: true,
      allowed_extensions: [".md"],
      goals_path: "/repo/goals",
      goals_interval_minutes: 10,
      autonomous_enabled: false
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  const payload = JSON.parse(completed.stdout);
  assert.equal(payload.entrypoint, "daemon_startup_banner_decision");
  assert.equal(payload.allowedExtensionsDescription, ".md");
  assert.equal(payload.lines.at(-2), "goals: /repo/goals (interval=10m, watching for .md files)");
  assert.equal(payload.lines.at(-1), "autonomous: disabled");
});

test("dormammu-agent-runner can project daemon shutdown decisions", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "daemon_shutdown_decision",
      goals_scheduler_configured: true,
      autonomous_scheduler_configured: false,
      progress_log_active: false
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "daemon_shutdown_decision",
    action: "shutdown",
    stopGoalsScheduler: true,
    stopAutonomousScheduler: false,
    closeWatcher: true,
    removeHeartbeat: true,
    closeProgressLog: false,
    reason: "daemon_shutdown"
  });
});

test("dormammu-agent-runner can project daemon instance lock decisions", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "daemon_instance_lock_decision",
      fcntl_available: true,
      lock_acquired: false,
      prompt_path: "/repo/prompts",
      existing_pid: "4321"
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "daemon_instance_lock_decision",
    action: "reject",
    writePidFile: false,
    errorMessage: [
      "Another dormammu daemon is already running against "
        + "/repo/prompts (existing daemon PID: 4321).",
      "Stop it first or use a different prompt_path."
    ].join("\n"),
    reason: "instance_lock_busy"
  });
});

test("dormammu-agent-runner can project daemon instance unlock decisions", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "daemon_instance_unlock_decision",
      fcntl_available: true,
      lock_held: true
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "daemon_instance_unlock_decision",
    action: "release",
    unlockFcntl: true,
    closeLockFile: true,
    clearPidLockFile: true,
    removePidFile: true,
    reason: "instance_lock_release"
  });
});

test("dormammu-agent-runner can project daemon heartbeat write decisions", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "daemon_heartbeat_write_decision",
      heartbeat_path_configured: true,
      pid: 42,
      status: "idle",
      timestamp: "2026-06-08T03:10:00+00:00"
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "daemon_heartbeat_write_decision",
    action: "write",
    ensureParent: true,
    heartbeatPayload: {
      pid: 42,
      status: "idle",
      ts: "2026-06-08T03:10:00+00:00"
    },
    reason: "heartbeat_write"
  });
});

test("dormammu-agent-runner can project daemon heartbeat remove decisions", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "daemon_heartbeat_remove_decision",
      heartbeat_path_configured: true
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "daemon_heartbeat_remove_decision",
    action: "remove",
    removeHeartbeat: true,
    reason: "heartbeat_remove"
  });
});

test("dormammu-agent-runner can project daemon watcher backend decisions", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "daemon_watcher_backend_decision",
      requested_backend: "auto",
      inotify_available: false
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "daemon_watcher_backend_decision",
    action: "use",
    backend: "polling",
    errorMessage: null,
    reason: "auto_falls_back_to_polling"
  });
});

test("dormammu-agent-runner can project daemon watcher wait decisions", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: JSON.stringify({
      entrypoint: "daemon_watcher_wait_decision",
      wait_requested: true,
      shutdown_requested: false,
      watcher_backend: "polling"
    }),
    encoding: "utf8"
  });

  assert.equal(completed.status, 0, completed.stderr);
  assert.equal(completed.stderr, "");
  assert.deepEqual(JSON.parse(completed.stdout), {
    entrypoint: "daemon_watcher_wait_decision",
    action: "wait",
    waitForChanges: true,
    watcherBackend: "polling",
    reason: "wait_requested"
  });
});

test("dormammu-agent-runner reports malformed JSON payloads", () => {
  const completed = spawnSync(process.execPath, [runnerCliPath], {
    input: "{",
    encoding: "utf8"
  });

  assert.equal(completed.status, 1);
  assert.equal(completed.stdout, "");
  assert.match(completed.stderr, /Invalid JSON payload/);
});
