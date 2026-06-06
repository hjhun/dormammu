import { cp, mkdir, readdir, readFile, stat, unlink, writeFile } from "node:fs/promises";
import path from "node:path";

import { STATE_SCHEMA_VERSION } from "./models.js";
import { readJson, writeJson, type JsonObject } from "./persistence.js";

const CORE_STATE_FILENAMES = [
  "DASHBOARD.md",
  "PLAN.md",
  "session.json",
  "workflow_state.json"
] as const;

const OPTIONAL_STATE_FILENAMES = [
  "supervisor_report.md",
  "continuation_prompt.txt"
] as const;

export type SessionManagerConfig = {
  appName?: string;
};

export type SessionSummary = {
  session_id: unknown;
  snapshot_dir: string;
  created_at: unknown;
  updated_at: unknown;
  goal: string;
  is_active: boolean;
  supervisor_verdict: unknown;
  attempts_completed: unknown;
  active_worktree_id: string | null;
  managed_worktree_count: number;
};

type WorktreeSummary = {
  activeWorktreeId: string | null;
  managedCount: number;
};

async function exists(filePath: string): Promise<boolean> {
  try {
    await stat(filePath);
    return true;
  } catch (error) {
    if (
      error instanceof Error &&
      "code" in error &&
      (error as NodeJS.ErrnoException).code === "ENOENT"
    ) {
      return false;
    }
    throw error;
  }
}

function isRecord(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function normalizeWorktrees(payload: unknown): WorktreeSummary {
  if (!isRecord(payload)) {
    return { activeWorktreeId: null, managedCount: 0 };
  }
  const managedPayload = payload.managed;
  const managedIds = Array.isArray(managedPayload)
    ? managedPayload
        .filter((item): item is JsonObject => isRecord(item))
        .map((item) => item.worktree_id)
        .filter((value): value is string | number | boolean => value != null)
        .map((value) => String(value).trim())
        .filter(Boolean)
    : [];
  const ids = new Set(managedIds);
  const rawActiveId = payload.active_worktree_id;
  const activeWorktreeId =
    rawActiveId == null || !ids.has(String(rawActiveId).trim())
      ? null
      : String(rawActiveId).trim();
  return {
    activeWorktreeId,
    managedCount: ids.size
  };
}

async function copyTextFileIfPresent(source: string, target: string): Promise<void> {
  if (await exists(source)) {
    await writeFile(target, await readFile(source, "utf8"), "utf8");
  } else if (await exists(target)) {
    await unlink(target);
  }
}

export class SessionManager {
  readonly config: Required<SessionManagerConfig>;
  readonly baseDevDir: string;
  readonly sessionsDir: string;
  readonly legacyBaseDevDir: string;

  constructor(options: {
    config?: SessionManagerConfig;
    baseDevDir: string;
    sessionsDir: string;
    legacyBaseDevDir?: string;
  }) {
    this.config = { appName: options.config?.appName ?? "dormammu" };
    this.baseDevDir = options.baseDevDir;
    this.sessionsDir = options.sessionsDir;
    this.legacyBaseDevDir = options.legacyBaseDevDir ?? options.baseDevDir;
  }

  static normalizeSessionId(value: string): string {
    const normalized = value
      .trim()
      .replace(/[^a-zA-Z0-9._-]+/g, "-")
      .replace(/^[-._]+|[-._]+$/g, "");
    if (!normalized) {
      throw new Error("session_id must contain at least one safe filename character.");
    }
    return normalized;
  }

  async generatedSessionId(timestamp: string): Promise<string> {
    const compact = timestamp
      .replaceAll("-", "")
      .replaceAll(":", "")
      .replaceAll("+", "-")
      .replaceAll("T", "-");
    const base = `${this.config.appName}-${compact}`;
    let candidate = base;
    let sequence = 1;
    while (await exists(path.join(this.sessionsDir, candidate))) {
      candidate = `${base}-${String(sequence).padStart(2, "0")}`;
      sequence += 1;
    }
    return candidate;
  }

  static async currentSessionId(sessionPath: string): Promise<string | null> {
    if (!(await exists(sessionPath))) {
      return null;
    }
    let payload: JsonObject;
    try {
      payload = await readJson(sessionPath);
    } catch (error) {
      if (error instanceof SyntaxError) {
        return null;
      }
      throw error;
    }
    const sessionId = payload.session_id ?? payload.active_session_id;
    return sessionId ? String(sessionId) : null;
  }

  async readActiveSessionId(): Promise<string | null> {
    return SessionManager.currentSessionId(path.join(this.baseDevDir, "session.json"));
  }

  async listSessions(): Promise<SessionSummary[]> {
    const activeSessionId = await this.readActiveSessionId();
    if (!(await exists(this.sessionsDir))) {
      return [];
    }

    const sessions: SessionSummary[] = [];
    for (const entry of await readdir(this.sessionsDir, { withFileTypes: true })) {
      if (!entry.isDirectory()) {
        continue;
      }
      const sessionDir = path.join(this.sessionsDir, entry.name);
      const sessionPath = path.join(sessionDir, "session.json");
      if (!(await exists(sessionPath))) {
        continue;
      }

      const sessionState = await readJson(sessionPath);
      const workflowPath = path.join(sessionDir, "workflow_state.json");
      const workflowState = (await exists(workflowPath)) ? await readJson(workflowPath) : {};
      const bootstrap = isRecord(sessionState.bootstrap) ? sessionState.bootstrap : {};
      const rawGoal = bootstrap.goal ?? sessionState.goal ?? "";
      const goal = String(rawGoal);
      const goalSummary = goal.length > 120 ? `${goal.slice(0, 120)}...` : goal;
      const loopState = isRecord(sessionState.loop)
        ? sessionState.loop
        : isRecord(workflowState.loop)
          ? workflowState.loop
          : {};
      const worktrees = normalizeWorktrees(sessionState.worktrees);
      const sessionId = sessionState.session_id;
      sessions.push({
        session_id: sessionId,
        snapshot_dir: sessionDir,
        created_at: sessionState.created_at,
        updated_at: sessionState.updated_at,
        goal: goalSummary,
        is_active: sessionId === activeSessionId,
        supervisor_verdict: loopState.latest_supervisor_verdict,
        attempts_completed: loopState.attempts_completed,
        active_worktree_id: worktrees.activeWorktreeId,
        managed_worktree_count: worktrees.managedCount
      });
    }

    return sessions.sort((left, right) => {
      const leftKey = String(left.updated_at ?? left.created_at ?? "");
      const rightKey = String(right.updated_at ?? right.created_at ?? "");
      return leftKey.localeCompare(rightKey);
    });
  }

  async hasLegacyRootSnapshot(): Promise<boolean> {
    for (const filename of [...CORE_STATE_FILENAMES, "TASKS.md"]) {
      if (await exists(path.join(this.legacyBaseDevDir, filename))) {
        return true;
      }
    }
    return false;
  }

  static async copyStateSnapshot(sourceDir: string, targetDir: string): Promise<void> {
    await mkdir(targetDir, { recursive: true });
    for (const filename of [...CORE_STATE_FILENAMES, ...OPTIONAL_STATE_FILENAMES]) {
      await copyTextFileIfPresent(path.join(sourceDir, filename), path.join(targetDir, filename));
    }

    const sourceTasksPath = path.join(sourceDir, "TASKS.md");
    const targetTasksPath = path.join(targetDir, "TASKS.md");
    await copyTextFileIfPresent(sourceTasksPath, targetTasksPath);

    const targetPlanPath = path.join(targetDir, "PLAN.md");
    if ((await exists(sourceTasksPath)) && !(await exists(targetPlanPath))) {
      await writeFile(targetPlanPath, await readFile(sourceTasksPath, "utf8"), "utf8");
    }
  }

  async migrateLegacyRootSnapshot(options: { timestamp?: string } = {}): Promise<string | null> {
    const activeSessionId = await this.readActiveSessionId();
    if (
      activeSessionId !== null &&
      (await exists(path.join(this.sessionsDir, activeSessionId)))
    ) {
      return activeSessionId;
    }
    const legacySessionId = await SessionManager.currentSessionId(
      path.join(this.legacyBaseDevDir, "session.json")
    );
    if (
      legacySessionId !== null &&
      (await exists(path.join(this.sessionsDir, legacySessionId)))
    ) {
      return legacySessionId;
    }
    if (!(await this.hasLegacyRootSnapshot())) {
      return null;
    }

    const sessionId =
      legacySessionId ??
      (await this.generatedSessionId(options.timestamp ?? new Date().toISOString()));
    const targetDir = path.join(this.sessionsDir, sessionId);
    await SessionManager.copyStateSnapshot(this.legacyBaseDevDir, targetDir);

    const legacyLogsDir = path.join(this.legacyBaseDevDir, "logs");
    const targetLogsDir = path.join(targetDir, "logs");
    if ((await exists(legacyLogsDir)) && !(await exists(targetLogsDir))) {
      await cp(legacyLogsDir, targetLogsDir, { recursive: true });
    }

    const sessionPath = path.join(targetDir, "session.json");
    if (await exists(sessionPath)) {
      const sessionState = await readJson(sessionPath);
      sessionState.session_id = sessionId;
      sessionState.state_schema_version ??= STATE_SCHEMA_VERSION;
      await writeJson(sessionPath, sessionState);
    }
    return sessionId;
  }

  async readLegacyRootSessionPayload(): Promise<JsonObject | null> {
    const sessionPath = path.join(this.legacyBaseDevDir, "session.json");
    if (!(await exists(sessionPath))) {
      return null;
    }
    const payload = await readJson(sessionPath);
    if ("active_session_id" in payload) {
      return null;
    }
    if (!("session_id" in payload)) {
      return null;
    }
    return payload;
  }

}
