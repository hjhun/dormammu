import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
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
