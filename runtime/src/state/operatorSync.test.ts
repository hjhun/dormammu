import assert from "node:assert/strict";
import {
  mkdir,
  mkdtemp,
  readFile,
  rm,
  stat,
  utimes,
  writeFile
} from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import { readJson, writeJson } from "./persistence.js";
import { OperatorSync, runtimeSkillSummary } from "./operatorSync.js";

async function withTempDirectory(run: (root: string) => Promise<void>): Promise<void> {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-runtime-"));
  try {
    await run(root);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

async function seedSession(root: string, sessionId = "session-001"): Promise<{
  baseDevDir: string;
  sessionDevDir: string;
}> {
  const baseDevDir = path.join(root, ".dev");
  const sessionDevDir = path.join(baseDevDir, "sessions", sessionId);
  await mkdir(sessionDevDir, { recursive: true });
  await writeJson(path.join(sessionDevDir, "session.json"), {
    session_id: sessionId,
    state_schema_version: 9,
    updated_at: "2026-04-25T00:00:00+00:00",
    bootstrap: { goal: "Ship operator sync" },
    active_phase: "develop",
    active_roadmap_phase_ids: ["phase_2"],
    worktrees: {
      active_worktree_id: "wt-1",
      managed: [{ worktree_id: "wt-1", status: "active" }]
    },
    runtime_skills: {
      active_role: "developer",
      latest: {
        profile: { name: "codex", source: "default" },
        summary: {
          selected_count: 1,
          visible_count: 2,
          hidden_count: 0,
          preloaded_count: 1,
          missing_preload_count: 0,
          shadowed_count: 0,
          custom_visible_count: 1,
          interesting_for_operator: true
        }
      }
    }
  });
  await writeJson(path.join(sessionDevDir, "workflow_state.json"), {
    version: 1,
    state_schema_version: 9,
    updated_at: "2026-04-25T00:00:00+00:00",
    mode: "supervised",
    bootstrap: { goal: "Ship operator sync" },
    source_of_truth: { goal: ["Ship operator sync"] },
    worktrees: {
      active_worktree_id: "wt-2",
      managed: [{ worktree_id: "wt-2", status: "active" }]
    }
  });
  await writeFile(path.join(sessionDevDir, "DASHBOARD.md"), "# Dashboard\n", "utf8");
  await writeFile(
    path.join(sessionDevDir, "TASKS.md"),
    "# TASKS\n\n## Prompt-Derived Development Queue\n\n- [ ] Phase 1. Do work\n",
    "utf8"
  );
  await writeFile(path.join(sessionDevDir, "PLAN.md"), "# Plan\n", "utf8");
  return { baseDevDir, sessionDevDir };
}

test("runtimeSkillSummary extracts operator-visible profile counts", () => {
  const summary = runtimeSkillSummary({
    active_role: "developer",
    latest: {
      profile: { name: "codex", source: "project" },
      summary: {
        selected_count: 1,
        visible_count: 2,
        hidden_count: 3,
        preloaded_count: 4,
        missing_preload_count: 5,
        shadowed_count: 6,
        custom_visible_count: 7,
        interesting_for_operator: false
      }
    }
  });

  assert.deepEqual(summary, {
    active_role: "developer",
    profile_name: "codex",
    profile_source: "project",
    selected_count: 1,
    visible_count: 2,
    hidden_count: 3,
    preloaded_count: 4,
    missing_preload_count: 5,
    shadowed_count: 6,
    custom_visible_count: 7,
    interesting_for_operator: false
  });
});

test("writeRootIndexForSession writes root index and mirrors operator files", async () => {
  await withTempDirectory(async (root) => {
    const { baseDevDir, sessionDevDir } = await seedSession(root);
    const operatorSync = new OperatorSync({ baseDevDir });

    await operatorSync.writeRootIndexForSession({
      sessionDevDir,
      sessionId: "session-001",
      stateRoot: ".dev/sessions/session-001",
      timestamp: "2026-04-25T01:00:00+00:00",
      listSessions: () => [{ session_id: "session-001" }]
    });

    const rootSession = await readJson(path.join(baseDevDir, "session.json"));
    const currentSession = rootSession.current_session as Record<string, unknown>;
    assert.equal(rootSession.active_session_id, "session-001");
    assert.equal(currentSession.goal, "Ship operator sync");
    assert.equal(currentSession.active_worktree_id, "wt-1");
    assert.equal(currentSession.managed_worktree_count, 1);
    assert.equal(await readFile(path.join(baseDevDir, "DASHBOARD.md"), "utf8"), "# Dashboard\n");
    assert.equal((await stat(path.join(baseDevDir, ".dev_lock"))).isFile(), true);

    const rootWorkflow = await readJson(path.join(baseDevDir, "workflow_state.json"));
    const sourceOfTruth = rootWorkflow.source_of_truth as Record<string, unknown>;
    assert.equal(rootWorkflow.active_session_id, "session-001");
    assert.equal(sourceOfTruth.session_machine_state, ".dev/sessions/session-001/workflow_state.json");
  });
});

test("rootIndexLock serializes concurrent operations in one process", async () => {
  await withTempDirectory(async (root) => {
    const operatorSync = new OperatorSync({ baseDevDir: path.join(root, ".dev") });
    const events: string[] = [];
    let releaseFirst: () => void = () => undefined;
    const firstMayFinish = new Promise<void>((resolve) => {
      releaseFirst = resolve;
    });
    let markFirstStarted: () => void = () => undefined;
    const firstStarted = new Promise<void>((resolve) => {
      markFirstStarted = resolve;
    });

    const first = operatorSync.rootIndexLock(async () => {
      events.push("first:start");
      markFirstStarted();
      await firstMayFinish;
      events.push("first:end");
    });
    await firstStarted;
    const second = operatorSync.rootIndexLock(async () => {
      events.push("second:start");
      events.push("second:end");
    });

    assert.deepEqual(events, ["first:start"]);
    releaseFirst();
    await Promise.all([first, second]);
    assert.deepEqual(events, ["first:start", "first:end", "second:start", "second:end"]);
  });
});

test("syncActiveRootOperatorMirrorsIntoSession imports newer active root mirror", async () => {
  await withTempDirectory(async (root) => {
    const { baseDevDir, sessionDevDir } = await seedSession(root);
    const operatorSync = new OperatorSync({ baseDevDir });
    await writeJson(path.join(baseDevDir, "session.json"), { active_session_id: "session-001" });
    const rootTasks = path.join(baseDevDir, "TASKS.md");
    const sessionTasks = path.join(sessionDevDir, "TASKS.md");
    await writeFile(
      rootTasks,
      "# TASKS\n\n## Prompt-Derived Development Queue\n\n- [O] Phase 1. Do work\n",
      "utf8"
    );
    const sessionStats = await stat(sessionTasks, { bigint: true });
    const bumped = Number(sessionStats.mtimeNs + 5_000_000n) / 1_000_000_000;
    await utimes(rootTasks, bumped, bumped);

    await operatorSync.syncActiveRootOperatorMirrorsIntoSession({
      sessionDevDir,
      activeSessionId: "session-001"
    });

    assert.equal(await readFile(sessionTasks, "utf8"), await readFile(rootTasks, "utf8"));
  });
});

test("syncOperatorState prefers the file with fewer pending tasks", async () => {
  await withTempDirectory(async (root) => {
    const { baseDevDir, sessionDevDir } = await seedSession(root);
    const sessionPath = path.join(sessionDevDir, "session.json");
    const workflowPath = path.join(sessionDevDir, "workflow_state.json");
    const planPath = path.join(sessionDevDir, "PLAN.md");
    const tasksPath = path.join(sessionDevDir, "TASKS.md");
    await writeFile(
      planPath,
      "# PLAN\n\n## Prompt-Derived Implementation Plan\n\n- [O] Phase 1. Done item\n",
      "utf8"
    );
    await writeFile(
      tasksPath,
      "# TASKS\n\n## Prompt-Derived Development Queue\n\n- [ ] Phase 1. Pending item\n",
      "utf8"
    );
    const tasksStats = await stat(tasksPath, { bigint: true });
    const bumped = Number(tasksStats.mtimeNs + 5_000_000n) / 1_000_000_000;
    await utimes(tasksPath, bumped, bumped);

    const operatorSync = new OperatorSync({ baseDevDir });
    await operatorSync.syncOperatorState({
      sessionPath,
      workflowPath,
      operatorTaskPath: tasksPath,
      timestamp: "2026-04-25T02:00:00+00:00",
      devDir: sessionDevDir,
      displayStatePath: (filePath) => path.relative(root, filePath)
    });

    const sessionState = await readJson(sessionPath);
    const taskSync = sessionState.task_sync as Record<string, unknown>;
    assert.equal(taskSync.source, path.relative(root, planPath));
    assert.equal(taskSync.all_completed, true);
    assert.equal(taskSync.next_pending_task, null);
    assert.equal(typeof sessionState.operator_state_mtime, "number");
  });
});

test("syncOperatorState emits warning when operator mtime drift is detected", async () => {
  await withTempDirectory(async (root) => {
    const { baseDevDir, sessionDevDir } = await seedSession(root);
    const sessionPath = path.join(sessionDevDir, "session.json");
    const workflowPath = path.join(sessionDevDir, "workflow_state.json");
    const tasksPath = path.join(sessionDevDir, "TASKS.md");
    const taskStats = await stat(tasksPath);
    const oldMtime = taskStats.mtimeMs / 1000 - 86400;
    const sessionState = await readJson(sessionPath);
    sessionState.operator_state_mtime = oldMtime;
    await writeJson(sessionPath, sessionState);
    const warnings: string[] = [];

    await new OperatorSync({ baseDevDir }).syncOperatorState({
      sessionPath,
      workflowPath,
      operatorTaskPath: tasksPath,
      timestamp: "2026-04-25T03:00:00+00:00",
      devDir: sessionDevDir,
      displayStatePath: (filePath) => path.relative(root, filePath),
      warn: (message) => warnings.push(message)
    });

    assert.equal(warnings.length, 1);
    assert.match(warnings[0], /Warning/);
    assert.match(warnings[0], /modified externally/);
  });
});
