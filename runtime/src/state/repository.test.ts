import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, stat, utimes, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import { readJson, writeJson, type JsonObject } from "./persistence.js";
import { promptFingerprint } from "./models.js";
import { StateRepository } from "./repository.js";

async function withTempDirectory(run: (root: string) => Promise<void>): Promise<void> {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-runtime-"));
  try {
    await run(root);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

async function seedRepository(root: string, sessionId = "session-001"): Promise<StateRepository> {
  const baseDevDir = path.join(root, ".dev");
  const sessionsDir = path.join(baseDevDir, "sessions");
  const sessionDir = path.join(sessionsDir, sessionId);
  await mkdir(sessionDir, { recursive: true });
  await writeJson(path.join(baseDevDir, "session.json"), { active_session_id: sessionId });
  await writeJson(path.join(sessionDir, "session.json"), {
    session_id: sessionId,
    state_schema_version: 9,
    updated_at: "2026-04-20T00:00:00+00:00",
    bootstrap: { goal: "Repository state sync" },
    active_phase: "plan",
    active_roadmap_phase_ids: ["phase_4"]
  });
  await writeJson(path.join(sessionDir, "workflow_state.json"), {
    version: 1,
    state_schema_version: 9,
    updated_at: "2026-04-20T00:00:00+00:00",
    bootstrap: { goal: "Repository state sync" },
    source_of_truth: { goal: ["Repository state sync"] },
    workflow: { active_phase: "plan" },
    roadmap: { active_phase_ids: ["phase_4"] }
  });
  await writeFile(path.join(sessionDir, "DASHBOARD.md"), "# Dashboard\n", "utf8");
  await writeFile(path.join(sessionDir, "PLAN.md"), "# Plan\n", "utf8");
  await writeFile(
    path.join(sessionDir, "TASKS.md"),
    "# TASKS\n\n## Prompt-Derived Development Queue\n\n- [ ] Phase 1. Work\n",
    "utf8"
  );
  return new StateRepository({
    baseDevDir,
    sessionsDir,
    repoRoot: root,
    sessionId
  });
}

function requireRecord(value: unknown): JsonObject {
  assert.equal(typeof value, "object");
  assert.notEqual(value, null);
  assert.equal(Array.isArray(value), false);
  return value as JsonObject;
}

async function writeRuntimeSkill(root: string, relativePath: string, name: string): Promise<void> {
  const skillPath = path.join(root, relativePath, "SKILL.md");
  await mkdir(path.dirname(skillPath), { recursive: true });
  await writeFile(
    skillPath,
    [
      "---",
      "schema_version: 1",
      `name: ${name}`,
      `description: ${name} description`,
      "---",
      "",
      `# ${name}`,
      "",
      "Use this skill in repository runtime skill tests.",
      ""
    ].join("\n"),
    "utf8"
  );
}

test("writeWorkflowState syncs session active phase and root index", async () => {
  await withTempDirectory(async (root) => {
    const repository = await seedRepository(root);
    const workflowState = await repository.readWorkflowState();
    workflowState.updated_at = "2026-04-20T21:20:00+09:00";
    requireRecord(workflowState.workflow).active_phase = "commit";

    await repository.writeWorkflowState(workflowState);

    const sessionState = await repository.readSessionState();
    const rootIndex = await readJson(path.join(root, ".dev", "session.json"));
    const currentSession = requireRecord(rootIndex.current_session);
    assert.equal(sessionState.active_phase, "commit");
    assert.equal(sessionState.updated_at, "2026-04-20T21:20:00+09:00");
    assert.equal(currentSession.active_phase, "commit");
  });
});

test("ensureBootstrapState creates an active session and root index", async () => {
  await withTempDirectory(async (root) => {
    const repository = new StateRepository({
      baseDevDir: path.join(root, ".dev"),
      sessionsDir: path.join(root, ".dev", "sessions"),
      repoRoot: root
    });

    const artifacts = await repository.ensureBootstrapState({
      goal: "Port repository bootstrap orchestration",
      promptText: "Port repository bootstrap orchestration\n- preserve operator files",
      activeRoadmapPhaseIds: ["phase_2"],
      timestamp: "2026-04-27T00:00:00.000Z"
    });

    const rootIndex = await readJson(path.join(root, ".dev", "session.json"));
    const activeSessionId = String(rootIndex.active_session_id);
    const sessionDir = path.join(root, ".dev", "sessions", activeSessionId);
    assert.equal(artifacts.dashboard, path.join(sessionDir, "DASHBOARD.md"));
    assert.equal(artifacts.logsDir, path.join(sessionDir, "logs"));
    assert.equal(requireRecord(rootIndex.current_session).goal, "Port repository bootstrap orchestration");
    assert.equal(requireRecord(rootIndex.current_session).state_root, `.dev/sessions/${activeSessionId}`);
    assert.match(await readFile(path.join(root, ".dev", "DASHBOARD.md"), "utf8"), /Port repository bootstrap orchestration/);
    assert.match(await readFile(path.join(sessionDir, "TASKS.md"), "utf8"), /preserve operator files/);
  });
});

test("ensureBootstrapState initializes session files and sync projections", async () => {
  await withTempDirectory(async (root) => {
    const repository = new StateRepository({
      baseDevDir: path.join(root, ".dev"),
      sessionsDir: path.join(root, ".dev", "sessions"),
      repoRoot: root,
      sessionId: "manual-session"
    });

    const artifacts = await repository.ensureBootstrapState({
      goal: "Initialize state files",
      activeRoadmapPhaseIds: ["phase_3"],
      timestamp: "2026-04-27T00:01:00.000Z"
    });

    for (const filePath of [
      artifacts.dashboard,
      artifacts.plan,
      artifacts.tasks,
      artifacts.session,
      artifacts.workflowState
    ]) {
      assert.match(await readFile(filePath, "utf8"), /\S/);
    }

    const sessionState = await readJson(artifacts.session);
    const workflowState = await readJson(artifacts.workflowState);
    assert.equal(sessionState.session_id, "manual-session");
    assert.equal(sessionState.active_phase, "plan");
    assert.deepEqual(sessionState.active_roadmap_phase_ids, ["phase_3"]);
    assert.equal(requireRecord(workflowState.workflow).active_phase, "plan");
    assert.deepEqual(requireRecord(workflowState.roadmap).active_phase_ids, ["phase_3"]);
    assert.equal(requireRecord(sessionState.task_sync).synced_at, "2026-04-27T00:01:00.000Z");
  });
});

test("ensureBootstrapState preserves existing operator markdown", async () => {
  await withTempDirectory(async (root) => {
    const repository = await seedRepository(root);
    const dashboardPath = repository.stateFile("DASHBOARD.md");
    await writeFile(dashboardPath, "# Dashboard\n\nManual operator note\n", "utf8");

    await repository.ensureBootstrapState({
      goal: "Repository state sync",
      promptText: "Repository state sync",
      activeRoadmapPhaseIds: ["phase_5"],
      timestamp: "2026-04-27T00:02:00.000Z"
    });

    assert.match(await readFile(dashboardPath, "utf8"), /Manual operator note/);
    const sessionState = await repository.readSessionState();
    const workflowState = await repository.readWorkflowState();
    assert.deepEqual(sessionState.active_roadmap_phase_ids, ["phase_5"]);
    assert.deepEqual(requireRecord(workflowState.roadmap).active_phase_ids, ["phase_5"]);
  });
});

test("ensureBootstrapState regenerates operator files when prompt fingerprint changes", async () => {
  await withTempDirectory(async (root) => {
    const repository = new StateRepository({
      baseDevDir: path.join(root, ".dev"),
      sessionsDir: path.join(root, ".dev", "sessions"),
      repoRoot: root,
      sessionId: "fingerprint-session"
    });

    await repository.ensureBootstrapState({
      goal: "Fingerprint reset",
      promptText: "old prompt",
      timestamp: "2026-04-27T00:03:00.000Z"
    });
    await writeFile(repository.stateFile("DASHBOARD.md"), "# Dashboard\n\nManual stale note\n", "utf8");

    await repository.ensureBootstrapState({
      goal: "Fingerprint reset",
      promptText: "new prompt\n- regenerate operator files",
      timestamp: "2026-04-27T00:04:00.000Z"
    });

    const dashboard = await readFile(repository.stateFile("DASHBOARD.md"), "utf8");
    const tasks = await readFile(repository.stateFile("TASKS.md"), "utf8");
    const sessionState = await repository.readSessionState();
    const bootstrap = requireRecord(sessionState.bootstrap);
    assert.doesNotMatch(dashboard, /Manual stale note/);
    assert.match(tasks, /regenerate operator files/);
    assert.equal(bootstrap.prompt_fingerprint, promptFingerprint("new prompt\n- regenerate operator files"));
  });
});

test("ensureBootstrapState includes supplied repo guidance in defaults and markdown", async () => {
  await withTempDirectory(async (root) => {
    const repository = new StateRepository({
      baseDevDir: path.join(root, ".dev"),
      sessionsDir: path.join(root, ".dev", "sessions"),
      repoRoot: root,
      sessionId: "guidance-session"
    });

    const artifacts = await repository.ensureBootstrapState({
      goal: "Guidance-aware defaults",
      promptText: "Guidance-aware defaults",
      repoGuidance: {
        ruleFiles: ["AGENTS.md", ".agents/AGENTS.md"],
        workflowFiles: [".github/workflows/test.yml"]
      },
      timestamp: "2026-04-27T00:05:00.000Z"
    });

    const dashboard = await readFile(artifacts.dashboard, "utf8");
    const sessionState = await repository.readSessionState();
    const workflowState = await repository.readWorkflowState();
    const sessionGuidance = requireRecord(requireRecord(sessionState.bootstrap).repo_guidance);
    const workflowGuidance = requireRecord(requireRecord(workflowState.bootstrap).repo_guidance);
    const sourceOfTruth = requireRecord(workflowState.source_of_truth);
    assert.deepEqual(sessionGuidance.rule_files, ["AGENTS.md", ".agents/AGENTS.md"]);
    assert.deepEqual(workflowGuidance.workflow_files, [".github/workflows/test.yml"]);
    assert.deepEqual(sourceOfTruth.goal, [
      ".dev/PROJECT.md",
      ".dev/ROADMAP.md",
      "AGENTS.md",
      ".agents/AGENTS.md"
    ]);
    assert.match(dashboard, /Repository rules to follow: AGENTS.md, \.agents\/AGENTS.md/);
    assert.match(dashboard, /Relevant repository workflows: \.github\/workflows\/test.yml/);
  });
});

test("ensureBootstrapState discovers repo guidance from filesystem", async () => {
  await withTempDirectory(async (root) => {
    await mkdir(path.join(root, ".agents"), { recursive: true });
    await mkdir(path.join(root, ".dev"), { recursive: true });
    await mkdir(path.join(root, ".github", "workflows"), { recursive: true });
    await writeFile(path.join(root, "AGENTS.md"), "# Rules\n", "utf8");
    await writeFile(path.join(root, ".agents", "AGENTS.md"), "# Agent Rules\n", "utf8");
    await writeFile(path.join(root, ".dev", "PROJECT.md"), "# Project\n", "utf8");
    await writeFile(path.join(root, ".dev", "ROADMAP.md"), "# Roadmap\n", "utf8");
    await writeFile(path.join(root, ".github", "workflows", "test.yml"), "name: test\n", "utf8");
    await writeFile(path.join(root, ".github", "workflows", "deploy.yaml"), "name: deploy\n", "utf8");

    const repository = new StateRepository({
      baseDevDir: path.join(root, ".dev"),
      sessionsDir: path.join(root, ".dev", "sessions"),
      repoRoot: root,
      sessionId: "discovered-guidance"
    });

    const artifacts = await repository.ensureBootstrapState({
      goal: "Discover guidance",
      promptText: "Discover guidance",
      timestamp: "2026-04-27T00:06:00.000Z"
    });

    const dashboard = await readFile(artifacts.dashboard, "utf8");
    const sessionState = await repository.readSessionState();
    const workflowState = await repository.readWorkflowState();
    const guidance = requireRecord(requireRecord(sessionState.bootstrap).repo_guidance);
    assert.deepEqual(guidance.rule_files, [
      "AGENTS.md",
      ".agents/AGENTS.md",
      ".dev/PROJECT.md",
      ".dev/ROADMAP.md"
    ]);
    assert.deepEqual(guidance.workflow_files, [
      ".github/workflows/deploy.yaml",
      ".github/workflows/test.yml"
    ]);
    assert.match(dashboard, /\.dev\/PROJECT.md/);
    assert.deepEqual(requireRecord(workflowState.source_of_truth).goal, [
      ".dev/PROJECT.md",
      ".dev/ROADMAP.md",
      "AGENTS.md",
      ".agents/AGENTS.md"
    ]);
  });
});

test("restoreSession selects an existing session and mirrors operator files", async () => {
  await withTempDirectory(async (root) => {
    await seedRepository(root, "old-session");
    const rootRepository = new StateRepository({
      baseDevDir: path.join(root, ".dev"),
      sessionsDir: path.join(root, ".dev", "sessions"),
      repoRoot: root
    });
    const target = await seedRepository(root, "restore-me");
    await writeFile(target.stateFile("DASHBOARD.md"), "# Restored Dashboard\n", "utf8");
    await writeFile(target.stateFile("PLAN.md"), "# Restored Plan\n", "utf8");
    await writeFile(target.stateFile("TASKS.md"), "# Restored Tasks\n- [ ] Phase 1. Restore\n", "utf8");

    const artifacts = await rootRepository.restoreSession("restore-me");

    const rootIndex = await readJson(path.join(root, ".dev", "session.json"));
    assert.equal(rootIndex.active_session_id, "restore-me");
    assert.equal(requireRecord(rootIndex.current_session).state_root, ".dev/sessions/restore-me");
    assert.equal(artifacts.dashboard, path.join(root, ".dev", "sessions", "restore-me", "DASHBOARD.md"));
    assert.match(await readFile(path.join(root, ".dev", "DASHBOARD.md"), "utf8"), /Restored Dashboard/);
    assert.match(await readFile(path.join(root, ".dev", "TASKS.md"), "utf8"), /Restore/);
  });
});

test("startNewSession creates a fresh active session with prompt state", async () => {
  await withTempDirectory(async (root) => {
    await seedRepository(root, "old-session");
    const rootRepository = new StateRepository({
      baseDevDir: path.join(root, ".dev"),
      sessionsDir: path.join(root, ".dev", "sessions"),
      repoRoot: root
    });

    const artifacts = await rootRepository.startNewSession({
      goal: "Start fresh work",
      promptText: "Start fresh work\n- create a new active session",
      activeRoadmapPhaseIds: ["phase_6"],
      sessionId: "Fresh Session!",
      timestamp: "2026-04-27T00:07:00.000Z"
    });

    const sessionDir = path.join(root, ".dev", "sessions", "Fresh-Session");
    const rootIndex = await readJson(path.join(root, ".dev", "session.json"));
    const sessionState = await readJson(path.join(sessionDir, "session.json"));
    const workflowState = await readJson(path.join(sessionDir, "workflow_state.json"));
    assert.equal(artifacts.dashboard, path.join(sessionDir, "DASHBOARD.md"));
    assert.equal(rootIndex.active_session_id, "Fresh-Session");
    assert.equal(sessionState.session_id, "Fresh-Session");
    assert.equal(requireRecord(sessionState.bootstrap).goal, "Start fresh work");
    assert.deepEqual(sessionState.active_roadmap_phase_ids, ["phase_6"]);
    assert.deepEqual(requireRecord(workflowState.roadmap).active_phase_ids, ["phase_6"]);
    assert.match(await readFile(path.join(root, ".dev", "TASKS.md"), "utf8"), /create a new active session/);
  });
});

test("startNewSession rejects session-scoped repositories", async () => {
  await withTempDirectory(async (root) => {
    const repository = new StateRepository({
      baseDevDir: path.join(root, ".dev"),
      sessionsDir: path.join(root, ".dev", "sessions"),
      repoRoot: root,
      sessionId: "scoped"
    });

    await assert.rejects(
      () => repository.startNewSession({ goal: "Nope" }),
      /active repository/
    );
  });
});

test("writeWorkflowState syncs roadmap phase ids and loop request", async () => {
  await withTempDirectory(async (root) => {
    const repository = await seedRepository(root);
    const sessionState = await repository.readSessionState();
    sessionState.loop = {
      status: "running",
      request: { expected_roadmap_phase_id: "phase_4" }
    };
    await repository.writeSessionState(sessionState);
    const workflowState = await repository.readWorkflowState();
    workflowState.loop = {
      status: "running",
      request: { expected_roadmap_phase_id: "phase_4" }
    };
    requireRecord(workflowState.roadmap).active_phase_ids = ["phase_6"];

    await repository.writeWorkflowState(workflowState);

    const syncedSession = await repository.readSessionState();
    const loop = requireRecord(syncedSession.loop);
    const request = requireRecord(loop.request);
    assert.deepEqual(syncedSession.active_roadmap_phase_ids, ["phase_6"]);
    assert.equal(request.expected_roadmap_phase_id, "phase_6");
  });
});

test("writeSessionState syncs workflow active phase and roadmap phase ids", async () => {
  await withTempDirectory(async (root) => {
    const repository = await seedRepository(root);
    const sessionState = await repository.readSessionState();
    sessionState.updated_at = "2026-04-20T21:21:01+09:00";
    sessionState.active_phase = "final_verification";
    sessionState.active_roadmap_phase_ids = ["phase_7"];

    await repository.writeSessionState(sessionState);

    const workflowState = await repository.readWorkflowState();
    const workflow = requireRecord(workflowState.workflow);
    const roadmap = requireRecord(workflowState.roadmap);
    assert.equal(workflow.active_phase, "final_verification");
    assert.deepEqual(roadmap.active_phase_ids, ["phase_7"]);
    assert.equal(workflowState.updated_at, "2026-04-20T21:21:01+09:00");
  });
});

test("writeStatePair keeps pointers consistent when payloads disagree", async () => {
  await withTempDirectory(async (root) => {
    const repository = await seedRepository(root);
    const sessionState = await repository.readSessionState();
    const workflowState = await repository.readWorkflowState();
    sessionState.active_phase = "plan";
    sessionState.updated_at = "2026-04-22T01:10:00+09:00";
    requireRecord(workflowState.workflow).active_phase = "final_verification";
    workflowState.updated_at = "2026-04-22T01:10:00+09:00";

    await repository.writeStatePair({
      sessionPayload: sessionState,
      workflowPayload: workflowState
    });

    const pairedSession = await repository.readSessionState();
    const pairedWorkflow = await repository.readWorkflowState();
    const rootSession = await readJson(path.join(root, ".dev", "session.json"));
    const currentSession = requireRecord(rootSession.current_session);
    assert.equal(pairedSession.active_phase, "final_verification");
    assert.equal(requireRecord(pairedWorkflow.workflow).active_phase, "final_verification");
    assert.equal(currentSession.active_phase, "final_verification");
  });
});

test("recordHookEvent appends bounded hook history to both state files", async () => {
  await withTempDirectory(async (root) => {
    const repository = await seedRepository(root);

    await repository.recordHookEvent({ recorded_at: "2026-04-25T00:00:00+00:00", name: "a" });
    await repository.recordHookEvent(
      { recorded_at: "2026-04-25T00:01:00+00:00", name: "b" },
      { historyLimit: 1 }
    );

    const sessionHooks = requireRecord((await repository.readSessionState()).hooks);
    const workflowHooks = requireRecord((await repository.readWorkflowState()).hooks);
    assert.deepEqual(sessionHooks.latest_event, {
      recorded_at: "2026-04-25T00:01:00+00:00",
      name: "b"
    });
    assert.deepEqual(sessionHooks.history, [
      { recorded_at: "2026-04-25T00:01:00+00:00", name: "b" }
    ]);
    assert.deepEqual(workflowHooks.history, sessionHooks.history);
  });
});

test("recordLifecycleEvent updates lifecycle and execution projections", async () => {
  await withTempDirectory(async (root) => {
    const repository = await seedRepository(root);

    await repository.recordLifecycleEvent({
      timestamp: "2026-04-25T00:00:00+00:00",
      event_type: "stage.failed",
      run_id: "run-1",
      role: "reviewer",
      stage: "reviewer",
      status: "completed",
      payload: { verdict: "needs_work", reason: "review failed" },
      artifact_refs: [{ kind: "stage_report", path: "/tmp/review.md" }]
    });

    const sessionState = await repository.readSessionState();
    const lifecycle = requireRecord(sessionState.lifecycle);
    const execution = requireRecord(sessionState.execution);
    const latestStage = requireRecord(execution.latest_stage_result);
    assert.equal(requireRecord(lifecycle.latest_event).event_type, "stage.failed");
    assert.equal(execution.latest_run_id, "run-1");
    assert.equal(latestStage.verdict, "needs_work");
    assert.equal(latestStage.stage_name, "reviewer");
  });
});

test("writeSupervisorReportRef writes markdown and returns artifact metadata", async () => {
  await withTempDirectory(async (root) => {
    const repository = await seedRepository(root);

    const artifact = await repository.writeSupervisorReportRef("# Supervisor\n\nApproved\n", {
      runId: "run-123",
      role: "reviewer",
      stageName: "review"
    });

    assert.equal(artifact.kind, "supervisor_report");
    assert.equal(artifact.path, repository.stateFile("supervisor_report.md"));
    assert.equal(artifact.label, "supervisor_report");
    assert.equal(artifact.content_type, "text/markdown");
    assert.equal(artifact.run_id, "run-123");
    assert.equal(artifact.role, "reviewer");
    assert.equal(artifact.stage_name, "review");
    assert.equal(artifact.session_id, "session-001");
    assert.equal(await readFile(repository.stateFile("supervisor_report.md"), "utf8"), "# Supervisor\n\nApproved\n");
  });
});

test("writeContinuationPromptRef writes prompt text and returns artifact metadata", async () => {
  await withTempDirectory(async (root) => {
    const repository = await seedRepository(root);

    const artifact = await repository.writeContinuationPromptRef("Continue from review\n", {
      runId: "run-456",
      role: "supervisor",
      stageName: "continuation"
    });

    assert.equal(artifact.kind, "continuation_prompt");
    assert.equal(artifact.path, repository.stateFile("continuation_prompt.txt"));
    assert.equal(artifact.label, "continuation_prompt");
    assert.equal(artifact.content_type, "text/plain");
    assert.equal(artifact.run_id, "run-456");
    assert.equal(artifact.role, "supervisor");
    assert.equal(artifact.stage_name, "continuation");
    assert.equal(artifact.session_id, "session-001");
    assert.equal(await readFile(repository.stateFile("continuation_prompt.txt"), "utf8"), "Continue from review\n");
  });
});

test("root artifact writers delegate to the active session", async () => {
  await withTempDirectory(async (root) => {
    const sessionRepository = await seedRepository(root);
    const rootRepository = new StateRepository({
      baseDevDir: path.join(root, ".dev"),
      sessionsDir: path.join(root, ".dev", "sessions"),
      repoRoot: root
    });

    const reportPath = await rootRepository.writeSupervisorReport("# Root delegated\n");
    const continuationPath = await rootRepository.writeContinuationPrompt("Continue active session\n");

    assert.equal(reportPath, sessionRepository.stateFile("supervisor_report.md"));
    assert.equal(continuationPath, sessionRepository.stateFile("continuation_prompt.txt"));
    assert.equal(await readFile(reportPath, "utf8"), "# Root delegated\n");
    assert.equal(await readFile(continuationPath, "utf8"), "Continue active session\n");
  });
});

test("persistInputPrompt writes session prompt, mirror, and state pointers", async () => {
  await withTempDirectory(async (root) => {
    const repository = await seedRepository(root);
    const promptPath = await repository.persistInputPrompt({
      promptText: "Build prompt persistence\n- keep state pointers"
    });

    const mirrorPath = path.join(root, ".dev", "sessions", "session-001", ".dev", "PROMPT.md");
    assert.equal(promptPath, repository.stateFile("PROMPT.md"));
    assert.equal(await readFile(promptPath, "utf8"), "Build prompt persistence\n- keep state pointers");
    assert.equal(await readFile(mirrorPath, "utf8"), "Build prompt persistence\n- keep state pointers");

    const sessionState = await repository.readSessionState();
    const workflowState = await repository.readWorkflowState();
    const sessionBootstrap = requireRecord(sessionState.bootstrap);
    const workflowBootstrap = requireRecord(workflowState.bootstrap);
    assert.equal(sessionBootstrap.prompt_path, ".dev/sessions/session-001/PROMPT.md");
    assert.equal(sessionBootstrap.global_prompt_path, mirrorPath);
    assert.equal(workflowBootstrap.prompt_path, ".dev/sessions/session-001/PROMPT.md");
    assert.equal(workflowBootstrap.global_prompt_path, mirrorPath);
    assert.equal(requireRecord(workflowState.artifacts).prompt, ".dev/sessions/session-001/PROMPT.md");
  });
});

test("upsertManagedWorktree tracks the active worktree and root summary", async () => {
  await withTempDirectory(async (root) => {
    const repository = await seedRepository(root);
    const worktree = {
      worktree_id: "wt-dev",
      source_repo_root: root,
      isolated_path: path.join(root, ".worktrees", "wt-dev"),
      owner: {
        session_id: "session-001",
        run_id: "run-dev",
        agent_role: "developer"
      },
      status: "planned"
    };

    await repository.upsertManagedWorktree(worktree, {
      active: true,
      timestamp: "2026-04-25T04:00:00+00:00"
    });

    const sessionWorktrees = requireRecord((await repository.readSessionState()).worktrees);
    const workflowWorktrees = requireRecord((await repository.readWorkflowState()).worktrees);
    const rootIndex = await readJson(path.join(root, ".dev", "session.json"));
    const currentSession = requireRecord(rootIndex.current_session);
    assert.equal(sessionWorktrees.active_worktree_id, "wt-dev");
    assert.equal(workflowWorktrees.active_worktree_id, "wt-dev");
    assert.deepEqual(requireRecord((sessionWorktrees.managed as unknown[])[0] as JsonObject).owner, {
      session_id: "session-001",
      run_id: "run-dev",
      agent_role: "developer"
    });
    assert.equal(requireRecord((sessionWorktrees.managed as unknown[])[0] as JsonObject).status, "active");
    assert.equal(currentSession.active_worktree_id, "wt-dev");
    assert.equal(currentSession.managed_worktree_count, 1);
  });
});

test("upsertManagedWorktree normalizes duplicate and stale active worktrees", async () => {
  await withTempDirectory(async (root) => {
    const repository = await seedRepository(root);
    const sessionState = await repository.readSessionState();
    sessionState.worktrees = {
      active_worktree_id: "wt-old",
      managed: [
        {
          worktree_id: "wt-old",
          source_repo_root: root,
          isolated_path: path.join(root, ".worktrees", "old-a"),
          owner: { session_id: "session-001", run_id: "run-old-a", agent_role: "developer" },
          status: "active"
        },
        {
          worktree_id: "wt-old",
          source_repo_root: root,
          isolated_path: path.join(root, ".worktrees", "old-b"),
          owner: { session_id: "session-001", run_id: "run-old-b", agent_role: "developer" },
          status: "active"
        }
      ]
    };
    await repository.writeSessionState(sessionState);

    await repository.upsertManagedWorktree(
      {
        worktree_id: "wt-next",
        source_repo_root: root,
        isolated_path: path.join(root, ".worktrees", "next"),
        owner: { session_id: "session-001", run_id: "run-next", agent_role: "developer" },
        status: "active"
      },
      { active: true, timestamp: "2026-04-25T04:01:00+00:00" }
    );

    const worktrees = requireRecord((await repository.readSessionState()).worktrees);
    const managed = worktrees.managed as JsonObject[];
    assert.equal(worktrees.active_worktree_id, "wt-next");
    assert.equal(managed.length, 2);
    assert.equal(requireRecord(managed[0]).worktree_id, "wt-old");
    assert.equal(requireRecord(managed[0]).isolated_path, path.join(root, ".worktrees", "old-b"));
    assert.equal(requireRecord(managed[0]).status, "planned");
    assert.equal(requireRecord(managed[1]).worktree_id, "wt-next");
    assert.equal(requireRecord(managed[1]).status, "active");
  });
});

test("forgetManagedWorktree clears active state and removes empty worktree blocks", async () => {
  await withTempDirectory(async (root) => {
    const repository = await seedRepository(root);
    await repository.upsertManagedWorktree(
      {
        worktree_id: "wt-dev",
        source_repo_root: root,
        isolated_path: path.join(root, ".worktrees", "wt-dev"),
        owner: { session_id: "session-001", run_id: "run-dev", agent_role: "developer" },
        status: "active"
      },
      { active: true, timestamp: "2026-04-25T04:02:00+00:00" }
    );

    await repository.forgetManagedWorktree("wt-dev", {
      timestamp: "2026-04-25T04:03:00+00:00"
    });

    const sessionState = await repository.readSessionState();
    const workflowState = await repository.readWorkflowState();
    const rootIndex = await readJson(path.join(root, ".dev", "session.json"));
    assert.equal("worktrees" in sessionState, false);
    assert.equal("worktrees" in workflowState, false);
    assert.equal(requireRecord(rootIndex.current_session).active_worktree_id, null);
    assert.equal(requireRecord(rootIndex.current_session).managed_worktree_count, 0);
  });
});

test("recordRuntimeSkillResolution stores latest and by-role payloads", async () => {
  await withTempDirectory(async (root) => {
    const repository = await seedRepository(root);
    const resolution = {
      role: "developer",
      profile: {
        name: "codex",
        source: "project",
        description: "Developer profile",
        preloaded_skills: ["developer"],
        runtime_metadata: {}
      },
      summary: {
        role: "developer",
        profile_name: "codex",
        profile_source: "project",
        candidate_count: 3,
        selected_count: 2,
        invalid_count: 0,
        visible_count: 2,
        hidden_count: 0,
        preloaded_count: 1,
        missing_preload_count: 0,
        shadowed_count: 0,
        custom_selected_count: 1,
        custom_visible_count: 1,
        interesting_for_operator: true
      },
      discovery: {},
      visibility: {},
      prompt_lines: ["Runtime skills for developer / codex (project profile):"]
    };

    const runtimeSkills = await repository.recordRuntimeSkillResolution({
      role: "developer",
      resolution,
      timestamp: "2026-04-25T05:00:00+00:00"
    });

    const sessionRuntimeSkills = requireRecord((await repository.readSessionState()).runtime_skills);
    const workflowRuntimeSkills = requireRecord((await repository.readWorkflowState()).runtime_skills);
    const rootIndex = await readJson(path.join(root, ".dev", "session.json"));
    const currentSession = requireRecord(rootIndex.current_session);
    const rootRuntimeSkills = requireRecord(currentSession.runtime_skills);
    assert.deepEqual(runtimeSkills, sessionRuntimeSkills);
    assert.deepEqual(workflowRuntimeSkills, sessionRuntimeSkills);
    assert.equal(sessionRuntimeSkills.updated_at, "2026-04-25T05:00:00+00:00");
    assert.equal(sessionRuntimeSkills.active_role, "developer");
    assert.deepEqual(sessionRuntimeSkills.latest, resolution);
    assert.deepEqual(requireRecord(sessionRuntimeSkills.by_role).developer, resolution);
    assert.equal(rootRuntimeSkills.active_role, "developer");
    assert.equal(rootRuntimeSkills.profile_name, "codex");
    assert.equal(rootRuntimeSkills.selected_count, 2);
    assert.equal(rootRuntimeSkills.interesting_for_operator, true);
  });
});

test("recordRuntimeSkillResolution can resolve profile skills from search roots", async () => {
  await withTempDirectory(async (root) => {
    const repository = await seedRepository(root);
    const projectSkills = path.join(root, ".agents", "skills");
    const userSkills = path.join(root, "home", ".agents", "skills");
    await writeRuntimeSkill(projectSkills, "designing-agent", "designing-agent");
    await writeRuntimeSkill(userSkills, "reviewer-agent", "reviewer-agent");

    const runtimeSkills = await repository.recordRuntimeSkillResolution({
      role: "designer",
      profile: {
        name: "designer",
        source: "project",
        description: "Designer profile",
        preloaded_skills: ["designing-agent", "missing-skill"],
        permission_policy: {
          skills: {
            rules: [{ skill: "reviewer-agent", decision: "deny" }]
          }
        }
      },
      skillSearchRoots: [
        { scope: "project", path: projectSkills },
        { scope: "user", path: userSkills }
      ],
      timestamp: "2026-04-25T05:30:00+00:00"
    });

    const latest = requireRecord(runtimeSkills.latest);
    const summary = requireRecord(latest.summary);
    const byRole = requireRecord(runtimeSkills.by_role);
    const sessionRuntimeSkills = requireRecord((await repository.readSessionState()).runtime_skills);
    assert.deepEqual(runtimeSkills, sessionRuntimeSkills);
    assert.deepEqual(requireRecord(byRole.designer), latest);
    assert.equal(runtimeSkills.active_role, "designer");
    assert.equal(summary.profile_name, "designer");
    assert.equal(summary.custom_visible_count, 1);
    assert.equal(summary.hidden_count, 1);
    assert.equal(summary.preloaded_count, 1);
    assert.equal(summary.missing_preload_count, 1);
    assert.deepEqual(latest.prompt_lines, [
      "Runtime skills for designer / designer (project profile):",
      "Visible project/user skills: designing-agent [project]",
      "Preloaded skills: designing-agent",
      "Hidden by profile policy: reviewer-agent",
      "Missing requested preloads: missing-skill"
    ]);
  });
});

test("syncOperatorState imports active root tasks and updates task projections", async () => {
  await withTempDirectory(async (root) => {
    const repository = await seedRepository(root);
    const rootTasks = path.join(root, ".dev", "TASKS.md");
    const rootPlan = path.join(root, ".dev", "PLAN.md");
    const operatorText =
      "# TASKS\n\n## Prompt-Derived Development Queue\n\n- [O] Phase 1. Work\n- [ ] Phase 2. Review\n";
    await writeFile(
      rootTasks,
      operatorText,
      "utf8"
    );
    await writeFile(rootPlan, operatorText.replace("# TASKS", "# PLAN"), "utf8");
    const sessionTaskStats = await stat(repository.stateFile("TASKS.md"), { bigint: true });
    const bumped = Number(sessionTaskStats.mtimeNs + 5_000_000n) / 1_000_000_000;
    await utimes(rootTasks, bumped, bumped);
    await utimes(rootPlan, bumped, bumped);

    await repository.syncOperatorState({ timestamp: "2026-04-25T06:00:00+00:00" });

    const sessionTasks = await readFile(repository.stateFile("TASKS.md"), "utf8");
    const sessionState = await repository.readSessionState();
    const workflowState = await repository.readWorkflowState();
    const taskSync = requireRecord(sessionState.task_sync);
    const workflowTaskSync = requireRecord(requireRecord(workflowState.operator_sync).tasks);
    assert.match(sessionTasks, /Phase 2\. Review/);
    assert.equal(taskSync.synced_at, "2026-04-25T06:00:00+00:00");
    assert.equal(taskSync.completed_tasks, 1);
    assert.equal(taskSync.pending_tasks, 1);
    assert.equal(taskSync.next_pending_task, "Phase 2. Review");
    assert.deepEqual(workflowTaskSync, taskSync);
  });
});

test("recordCurrentRun stores current run and execution projection", async () => {
  await withTempDirectory(async (root) => {
    const repository = await seedRepository(root);
    const started = {
      run_id: "run-current",
      prompt_mode: "stdin",
      workdir: root,
      command: ["codex", "run"],
      started_at: "2026-04-25T07:00:00+00:00"
    };

    await repository.recordCurrentRun(started);

    const sessionState = await repository.readSessionState();
    const workflowState = await repository.readWorkflowState();
    assert.deepEqual(sessionState.current_run, started);
    assert.deepEqual(workflowState.current_run, started);
    const executionCurrent = requireRecord(requireRecord(sessionState.execution).current_run);
    assert.equal(executionCurrent.run_id, "run-current");
    assert.equal(executionCurrent.status, "started");
    assert.equal(executionCurrent.workdir, root);
  });
});

test("recordLatestRun clears current run and stores latest run projection", async () => {
  await withTempDirectory(async (root) => {
    const repository = await seedRepository(root);
    await repository.recordCurrentRun({
      run_id: "run-latest",
      prompt_mode: "stdin",
      workdir: root,
      command: ["codex", "run"],
      started_at: "2026-04-25T07:01:00+00:00"
    });
    const result = {
      run_id: "run-latest",
      prompt_mode: "stdin",
      workdir: root,
      command: ["codex", "run"],
      exit_code: 0,
      started_at: "2026-04-25T07:01:00+00:00",
      completed_at: "2026-04-25T07:02:00+00:00",
      artifact_refs: [{ kind: "stdout", path: "/tmp/stdout.log" }]
    };

    await repository.recordLatestRun(result);

    const sessionState = await repository.readSessionState();
    const workflowState = await repository.readWorkflowState();
    assert.equal(sessionState.current_run, null);
    assert.deepEqual(sessionState.latest_run, result);
    assert.deepEqual(workflowState.latest_run, result);
    const execution = requireRecord(sessionState.execution);
    assert.equal(execution.current_run, null);
    const latestAgentRun = requireRecord(execution.latest_agent_run);
    assert.equal(latestAgentRun.run_id, "run-latest");
    assert.equal(latestAgentRun.status, "completed");
    assert.deepEqual(latestAgentRun.artifacts, [{ kind: "stdout", path: "/tmp/stdout.log" }]);
  });
});

test("recordStageResult and recordRunResult update execution projections", async () => {
  await withTempDirectory(async (root) => {
    const repository = await seedRepository(root);

    await repository.recordStageResult(
      {
        role: "tester",
        stageName: "test",
        status: "completed",
        verdict: "pass",
        summary: "Tests passed",
        timing: {
          startedAt: "2026-04-25T08:00:00+00:00",
          completedAt: "2026-04-25T08:01:00+00:00"
        },
        metadata: { pipeline_run_id: "pipeline-1" }
      },
      { timestamp: "2026-04-25T08:01:00+00:00" }
    );

    const afterStage = await repository.readSessionState();
    const stageExecution = requireRecord(afterStage.execution);
    assert.equal(stageExecution.latest_run_id, "pipeline-1");
    assert.equal(requireRecord(stageExecution.latest_stage_result).verdict, "pass");
    assert.equal(requireRecord(requireRecord(stageExecution.stage_results).test).summary, "Tests passed");

    await repository.recordRunResult(
      {
        status: "completed",
        latestRunId: "pipeline-1",
        supervisorVerdict: "approved",
        stageResults: [
          {
            role: "developer",
            stageName: "develop",
            status: "completed",
            verdict: "approved",
            summary: "Implemented"
          },
          {
            role: "tester",
            stageName: "test",
            status: "completed",
            verdict: "pass",
            summary: "Tests passed"
          }
        ],
        timing: {
          startedAt: "2026-04-25T08:00:00+00:00",
          completedAt: "2026-04-25T08:02:00+00:00"
        }
      },
      { timestamp: "2026-04-25T08:02:00+00:00" }
    );

    const sessionExecution = requireRecord((await repository.readSessionState()).execution);
    const workflowExecution = requireRecord((await repository.readWorkflowState()).execution);
    assert.equal(sessionExecution.latest_run_id, "pipeline-1");
    assert.equal(requireRecord(sessionExecution.latest_run).supervisor_verdict, "approved");
    assert.equal(requireRecord(sessionExecution.stage_results).develop != null, true);
    assert.equal(requireRecord(sessionExecution.stage_results).test != null, true);
    assert.deepEqual(workflowExecution, sessionExecution);
  });
});

test("root repository delegates reads and writes to the active session", async () => {
  await withTempDirectory(async (root) => {
    const sessionRepository = await seedRepository(root);
    const rootRepository = new StateRepository({
      baseDevDir: path.join(root, ".dev"),
      sessionsDir: path.join(root, ".dev", "sessions"),
      repoRoot: root
    });
    const sessionState = await rootRepository.readSessionState();
    sessionState.active_phase = "review";

    await rootRepository.writeSessionState(sessionState);

    assert.equal((await sessionRepository.readSessionState()).active_phase, "review");
  });
});

test("root hook events are ignored before an active session exists", async () => {
  await withTempDirectory(async (root) => {
    const repository = new StateRepository({
      baseDevDir: path.join(root, ".dev"),
      sessionsDir: path.join(root, ".dev", "sessions"),
      repoRoot: root
    });

    await repository.recordHookEvent({ recorded_at: "2026-04-25T00:00:00+00:00" });

    await assert.rejects(() => readFile(path.join(root, ".dev", "session.json"), "utf8"));
  });
});
