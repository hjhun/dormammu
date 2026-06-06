import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import { writeJson } from "./persistence.js";
import { SessionManager } from "./sessionManager.js";

async function withTempDirectory(run: (root: string) => Promise<void>): Promise<void> {
  const root = await mkdtemp(path.join(tmpdir(), "dormammu-runtime-"));
  try {
    await run(root);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}

function makeManager(root: string): SessionManager {
  return new SessionManager({
    config: { appName: "dormammu" },
    baseDevDir: path.join(root, ".dev"),
    sessionsDir: path.join(root, ".dev", "sessions")
  });
}

test("normalizeSessionId strips unsafe chars and rejects empty values", () => {
  const result = SessionManager.normalizeSessionId("hello world/foo");
  assert.equal(result.includes(" "), false);
  assert.equal(result.includes("/"), false);
  assert.throws(
    () => SessionManager.normalizeSessionId("   ---   "),
    /session_id must contain/
  );
});

test("generatedSessionId is unique on collision", async () => {
  await withTempDirectory(async (root) => {
    const sessionsDir = path.join(root, ".dev", "sessions");
    await mkdir(sessionsDir, { recursive: true });
    const manager = makeManager(root);

    const timestamp = "2026-01-01T00:00:00+0000";
    const firstId = await manager.generatedSessionId(timestamp);
    await mkdir(path.join(sessionsDir, firstId));
    const secondId = await manager.generatedSessionId(timestamp);
    assert.notEqual(firstId, secondId);
    assert.match(secondId, /-01$/);
  });
});

test("currentSessionId reads session.json and tolerates missing or invalid JSON", async () => {
  await withTempDirectory(async (root) => {
    const sessionPath = path.join(root, "session.json");
    await writeJson(sessionPath, { session_id: "my-session" });
    assert.equal(await SessionManager.currentSessionId(sessionPath), "my-session");
    assert.equal(await SessionManager.currentSessionId(path.join(root, "missing.json")), null);

    const invalidPath = path.join(root, "invalid.json");
    await writeFile(invalidPath, "{", "utf8");
    assert.equal(await SessionManager.currentSessionId(invalidPath), null);
  });
});

test("readActiveSessionId reads the root index", async () => {
  await withTempDirectory(async (root) => {
    const devDir = path.join(root, ".dev");
    await mkdir(devDir);
    await writeJson(path.join(devDir, "session.json"), { session_id: "active-001" });
    assert.equal(await makeManager(root).readActiveSessionId(), "active-001");
  });
});

test("listSessions returns empty when no sessions directory exists", async () => {
  await withTempDirectory(async (root) => {
    assert.deepEqual(await makeManager(root).listSessions(), []);
  });
});

test("listSessions marks the active session and includes summaries", async () => {
  await withTempDirectory(async (root) => {
    const devDir = path.join(root, ".dev");
    const sessionsDir = path.join(devDir, "sessions");
    await mkdir(sessionsDir, { recursive: true });

    for (const sid of ["sess-a", "sess-b"]) {
      const sessionDir = path.join(sessionsDir, sid);
      await mkdir(sessionDir);
      await writeJson(path.join(sessionDir, "session.json"), {
        session_id: sid,
        created_at: sid === "sess-a" ? "2026-01-01T00:00:00" : "2026-01-02T00:00:00",
        updated_at: sid === "sess-a" ? "2026-01-01T00:00:00" : "2026-01-02T00:00:00",
        bootstrap: { goal: `Goal for ${sid}` },
        loop: { latest_supervisor_verdict: "approved", attempts_completed: 2 },
        worktrees: {
          active_worktree_id: `${sid}-wt`,
          managed: [{ worktree_id: `${sid}-wt`, status: "active" }]
        }
      });
    }

    await writeJson(path.join(devDir, "session.json"), { session_id: "sess-b" });
    const sessions = await makeManager(root).listSessions();
    const active = sessions.filter((session) => session.is_active);
    const inactive = sessions.filter((session) => !session.is_active);

    assert.equal(active.length, 1);
    assert.equal(active[0].session_id, "sess-b");
    assert.equal(active[0].supervisor_verdict, "approved");
    assert.equal(active[0].attempts_completed, 2);
    assert.equal(active[0].active_worktree_id, "sess-b-wt");
    assert.equal(active[0].managed_worktree_count, 1);
    assert.equal(inactive.length, 1);
    assert.equal(inactive[0].session_id, "sess-a");
  });
});

test("migrateLegacyRootSnapshot copies legacy root files into a session", async () => {
  await withTempDirectory(async (root) => {
    const devDir = path.join(root, ".dev");
    const sessionsDir = path.join(devDir, "sessions");
    await mkdir(sessionsDir, { recursive: true });
    await writeJson(path.join(devDir, "session.json"), {
      session_id: "legacy-001",
      created_at: "2026-01-01T00:00:00"
    });
    await writeJson(path.join(devDir, "workflow_state.json"), { version: 1 });
    await writeFile(path.join(devDir, "DASHBOARD.md"), "# Dashboard\n", "utf8");
    await writeFile(path.join(devDir, "PLAN.md"), "# Plan\n", "utf8");

    const resultId = await makeManager(root).migrateLegacyRootSnapshot({
      timestamp: "2026-01-01T00:00:00+0000"
    });

    assert.equal(resultId, "legacy-001");
    const migratedSession = path.join(sessionsDir, "legacy-001", "session.json");
    assert.equal(await SessionManager.currentSessionId(migratedSession), "legacy-001");
  });
});

test("hasLegacyRootSnapshot detects state files", async () => {
  await withTempDirectory(async (root) => {
    const devDir = path.join(root, ".dev");
    await mkdir(devDir);
    const manager = makeManager(root);
    assert.equal(await manager.hasLegacyRootSnapshot(), false);
    await writeFile(path.join(devDir, "DASHBOARD.md"), "x", "utf8");
    assert.equal(await manager.hasLegacyRootSnapshot(), true);
  });
});

test("copyStateSnapshot copies core files", async () => {
  await withTempDirectory(async (root) => {
    const source = path.join(root, "source");
    const target = path.join(root, "target");
    await mkdir(source);
    await writeJson(path.join(source, "session.json"), { session_id: "x" });
    await writeFile(path.join(source, "DASHBOARD.md"), "# D\n", "utf8");

    await SessionManager.copyStateSnapshot(source, target);

    assert.equal(await SessionManager.currentSessionId(path.join(target, "session.json")), "x");
    assert.equal(await readFile(path.join(target, "DASHBOARD.md"), "utf8"), "# D\n");
  });
});
