import {
  copyFile,
  mkdir,
  readFile,
  stat,
  unlink,
  writeFile
} from "node:fs/promises";
import path from "node:path";

import { ensureJsonFile, readJson, writeJson, type JsonObject } from "./persistence.js";
import { SessionManager, managedWorktreeSummaryFromDict } from "./sessionManager.js";
import { operatorTaskSyncToDict, parseTasksDocument } from "./tasks.js";

export const ROOT_OPERATOR_MIRROR_FILENAMES = [
  "DASHBOARD.md",
  "PLAN.md",
  "TASKS.md",
  "WORKFLOWS.md"
] as const;

type RuntimeSkillSummary = {
  active_role: unknown;
  profile_name: unknown;
  profile_source: unknown;
  selected_count: unknown;
  visible_count: unknown;
  hidden_count: unknown;
  preloaded_count: unknown;
  missing_preload_count: unknown;
  shadowed_count: unknown;
  custom_visible_count: unknown;
  interesting_for_operator: unknown;
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

function getRecord(payload: JsonObject, key: string): JsonObject {
  const value = payload[key];
  return isRecord(value) ? value : {};
}

export function runtimeSkillSummary(payload: unknown): RuntimeSkillSummary | null {
  if (!isRecord(payload)) {
    return null;
  }
  const latest = payload.latest;
  if (!isRecord(latest)) {
    return null;
  }
  const summary = latest.summary;
  const profile = latest.profile;
  if (!isRecord(summary) || !isRecord(profile)) {
    return null;
  }
  return {
    active_role: payload.active_role,
    profile_name: profile.name,
    profile_source: profile.source,
    selected_count: summary.selected_count,
    visible_count: summary.visible_count,
    hidden_count: summary.hidden_count,
    preloaded_count: summary.preloaded_count,
    missing_preload_count: summary.missing_preload_count,
    shadowed_count: summary.shadowed_count,
    custom_visible_count: summary.custom_visible_count,
    interesting_for_operator: summary.interesting_for_operator
  };
}

async function copyIfPresent(source: string, target: string): Promise<void> {
  if (await exists(source)) {
    await copyFile(source, target);
  } else if (await exists(target)) {
    await unlink(target);
  }
}

async function mtimeNs(filePath: string): Promise<bigint> {
  const stats = await stat(filePath, { bigint: true });
  return stats.mtimeNs;
}

function pendingCount(text: string): number {
  return text.split("- [ ] ").length - 1;
}

let rootIndexQueue: Promise<void> = Promise.resolve();

export class OperatorSync {
  readonly baseDevDir: string;

  constructor(options: { baseDevDir: string }) {
    this.baseDevDir = options.baseDevDir;
  }

  async rootIndexLock<T>(run: () => Promise<T>): Promise<T> {
    await mkdir(this.baseDevDir, { recursive: true });
    await writeFile(path.join(this.baseDevDir, ".dev_lock"), "", { flag: "a" });
    const ready = rootIndexQueue.catch(() => undefined);
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    rootIndexQueue = ready.then(() => held);
    await ready;
    try {
      return await run();
    } finally {
      release();
    }
  }

  async writeRootIndexForSession(options: {
    sessionDevDir: string;
    sessionId: string;
    stateRoot: string;
    timestamp: string;
    listSessions: () => Promise<unknown[]> | unknown[];
  }): Promise<void> {
    await this.rootIndexLock(() => this.writeRootIndexLocked(options));
  }

  async writeRootIndexLocked(options: {
    sessionDevDir: string;
    sessionId: string;
    stateRoot: string;
    timestamp: string;
    listSessions: () => Promise<unknown[]> | unknown[];
  }): Promise<void> {
    const sessionState = await readJson(path.join(options.sessionDevDir, "session.json"));
    const workflowState = await readJson(path.join(options.sessionDevDir, "workflow_state.json"));
    const sessionWorktrees = managedWorktreeSummaryFromDict(sessionState.worktrees);
    const workflowWorktrees = managedWorktreeSummaryFromDict(workflowState.worktrees);
    const sessionBootstrap = getRecord(sessionState, "bootstrap");
    const workflowBootstrap = getRecord(workflowState, "bootstrap");
    const workflowSourceOfTruth = getRecord(workflowState, "source_of_truth");

    const sessionDefaults: JsonObject = {
      active_session_id: options.sessionId,
      default_session_id: options.sessionId,
      selected_at: options.timestamp,
      updated_at: options.timestamp,
      state_schema_version: sessionState.state_schema_version,
      current_session: {
        session_id: options.sessionId,
        state_root: options.stateRoot,
        session_path: `${options.stateRoot}/session.json`,
        workflow_path: `${options.stateRoot}/workflow_state.json`,
        dashboard_path: `${options.stateRoot}/DASHBOARD.md`,
        plan_path: `${options.stateRoot}/PLAN.md`,
        tasks_path: `${options.stateRoot}/TASKS.md`,
        logs_dir: `${options.stateRoot}/logs`,
        goal: sessionBootstrap.goal,
        updated_at: sessionState.updated_at,
        active_phase: sessionState.active_phase,
        active_roadmap_phase_ids: sessionState.active_roadmap_phase_ids ?? [],
        active_worktree_id: sessionWorktrees.activeWorktreeId,
        managed_worktree_count: sessionWorktrees.managedCount,
        runtime_skills: runtimeSkillSummary(sessionState.runtime_skills)
      }
    };
    const workflowDefaults: JsonObject = {
      version: workflowState.version ?? 1,
      state_schema_version: workflowState.state_schema_version,
      updated_at: options.timestamp,
      mode: workflowState.mode ?? "supervised",
      active_session_id: options.sessionId,
      default_session_id: options.sessionId,
      source_of_truth: {
        goal: workflowSourceOfTruth.goal ?? [],
        machine_state: ".dev/workflow_state.json",
        operator_state: [],
        session_machine_state: `${options.stateRoot}/workflow_state.json`,
        session_operator_state: [
          `${options.stateRoot}/DASHBOARD.md`,
          `${options.stateRoot}/PLAN.md`,
          `${options.stateRoot}/TASKS.md`
        ]
      },
      session_index: {
        active_session_id: options.sessionId,
        sessions_dir: ".dev/sessions"
      },
      current_session: {
        session_id: options.sessionId,
        state_root: options.stateRoot,
        workflow_path: `${options.stateRoot}/workflow_state.json`,
        session_path: `${options.stateRoot}/session.json`,
        tasks_path: `${options.stateRoot}/TASKS.md`,
        goal: workflowBootstrap.goal,
        updated_at: workflowState.updated_at,
        active_worktree_id: workflowWorktrees.activeWorktreeId,
        managed_worktree_count: workflowWorktrees.managedCount,
        runtime_skills: runtimeSkillSummary(workflowState.runtime_skills)
      },
      sessions: await options.listSessions()
    };

    const rootSessionPath = path.join(this.baseDevDir, "session.json");
    await ensureJsonFile(rootSessionPath, sessionDefaults);
    const rootSession = await readJson(rootSessionPath);
    rootSession.state_schema_version = sessionDefaults.state_schema_version;
    rootSession.active_session_id = options.sessionId;
    rootSession.default_session_id = options.sessionId;
    rootSession.selected_at = options.timestamp;
    rootSession.updated_at = options.timestamp;
    rootSession.current_session = sessionDefaults.current_session;
    await writeJson(rootSessionPath, rootSession);

    const rootWorkflowPath = path.join(this.baseDevDir, "workflow_state.json");
    await ensureJsonFile(rootWorkflowPath, workflowDefaults);
    const rootWorkflow = await readJson(rootWorkflowPath);
    rootWorkflow.state_schema_version = workflowDefaults.state_schema_version;
    rootWorkflow.updated_at = options.timestamp;
    rootWorkflow.active_session_id = options.sessionId;
    rootWorkflow.default_session_id = options.sessionId;
    rootWorkflow.source_of_truth = workflowDefaults.source_of_truth;
    rootWorkflow.session_index = workflowDefaults.session_index;
    rootWorkflow.current_session = workflowDefaults.current_session;
    rootWorkflow.sessions = await options.listSessions();
    for (const key of ["bootstrap", "intake", "workflow_policy", "roadmap"]) {
      const value = workflowState[key];
      if (isRecord(value)) {
        rootWorkflow[key] = { ...value };
      } else {
        delete rootWorkflow[key];
      }
    }
    await writeJson(rootWorkflowPath, rootWorkflow);

    await this.syncRootOperatorMirrors({
      sessionDevDir: options.sessionDevDir,
      activeSessionId: options.sessionId
    });
  }

  async readActiveSessionId(): Promise<string | null> {
    return SessionManager.currentSessionId(path.join(this.baseDevDir, "session.json"));
  }

  async syncRootOperatorMirrors(options: {
    sessionDevDir: string;
    activeSessionId: string;
  }): Promise<void> {
    if ((await this.readActiveSessionId()) !== options.activeSessionId) {
      return;
    }
    await mkdir(this.baseDevDir, { recursive: true });
    for (const filename of ROOT_OPERATOR_MIRROR_FILENAMES) {
      await copyIfPresent(
        path.join(options.sessionDevDir, filename),
        path.join(this.baseDevDir, filename)
      );
    }
  }

  async syncActiveRootOperatorMirrorsIntoSession(options: {
    sessionDevDir: string;
    activeSessionId: string;
  }): Promise<void> {
    if ((await this.readActiveSessionId()) !== options.activeSessionId) {
      return;
    }
    for (const filename of ROOT_OPERATOR_MIRROR_FILENAMES) {
      const rootPath = path.join(this.baseDevDir, filename);
      const sessionPath = path.join(options.sessionDevDir, filename);
      if (!(await exists(rootPath))) {
        continue;
      }
      if (!(await exists(sessionPath))) {
        await copyFile(rootPath, sessionPath);
        continue;
      }
      if ((await mtimeNs(rootPath)) <= (await mtimeNs(sessionPath))) {
        continue;
      }
      const [rootText, sessionText] = await Promise.all([
        readFile(rootPath, "utf8"),
        readFile(sessionPath, "utf8")
      ]);
      if (rootText !== sessionText) {
        await copyFile(rootPath, sessionPath);
      }
    }
  }

  async refreshActiveRoadmapPhaseIds(options: {
    sessionPath: string;
    workflowPath: string;
    roadmapPhaseIds: readonly string[];
    timestamp: string;
  }): Promise<void> {
    const normalizedPhaseIds = [...options.roadmapPhaseIds];

    const sessionState = await readJson(options.sessionPath);
    sessionState.updated_at = options.timestamp;
    sessionState.active_roadmap_phase_ids = normalizedPhaseIds;
    const sessionLoop = sessionState.loop;
    if (isRecord(sessionLoop) && isRecord(sessionLoop.request)) {
      sessionLoop.request.expected_roadmap_phase_id = normalizedPhaseIds[0] ?? null;
    }
    await writeJson(options.sessionPath, sessionState);

    const workflowState = await readJson(options.workflowPath);
    workflowState.updated_at = options.timestamp;
    const roadmap = isRecord(workflowState.roadmap) ? workflowState.roadmap : {};
    roadmap.active_phase_ids = normalizedPhaseIds;
    workflowState.roadmap = roadmap;
    const workflowLoop = workflowState.loop;
    if (isRecord(workflowLoop) && isRecord(workflowLoop.request)) {
      workflowLoop.request.expected_roadmap_phase_id = normalizedPhaseIds[0] ?? null;
    }
    await writeJson(options.workflowPath, workflowState);
  }

  async syncOperatorState(options: {
    sessionPath: string;
    workflowPath: string;
    operatorTaskPath: string;
    timestamp: string;
    devDir: string;
    displayStatePath: (filePath: string) => string;
    warn?: (message: string) => void;
  }): Promise<void> {
    const resolvedPath = await OperatorSync.resolveOperatorSyncSource({
      preferredPath: options.operatorTaskPath,
      devDir: options.devDir
    });
    const sourceExists = await exists(resolvedPath);
    const operatorText = sourceExists ? await readFile(resolvedPath, "utf8") : "";
    const operatorMtime = sourceExists ? (await stat(resolvedPath)).mtimeMs / 1000 : null;

    if (operatorMtime !== null && (await exists(options.sessionPath))) {
      try {
        const stored = await readJson(options.sessionPath);
        const storedMtime = stored.operator_state_mtime;
        if (
          storedMtime !== undefined &&
          Math.abs(operatorMtime - Number(storedMtime)) > 1.0
        ) {
          const message =
            `[dormammu] Warning: ${path.basename(resolvedPath)} was modified externally ` +
            `(stored mtime=${Number(storedMtime).toFixed(3)}, ` +
            `current=${operatorMtime.toFixed(3)}). ` +
            "Manual edits will be preserved by re-reading the file.";
          if (options.warn) {
            options.warn(message);
          } else {
            console.error(message);
          }
        }
      } catch {
        // Warning detection is best effort and must not block state sync.
      }
    }

    const parsedTasks = parseTasksDocument(operatorText, {
      source: options.displayStatePath(resolvedPath)
    });
    const taskSync = operatorTaskSyncToDict(parsedTasks.currentWorkflow, {
      syncedAt: options.timestamp
    });

    const sessionState = await readJson(options.sessionPath);
    sessionState.updated_at = options.timestamp;
    sessionState.task_sync = taskSync;
    if (operatorMtime !== null) {
      sessionState.operator_state_mtime = operatorMtime;
    }
    await writeJson(options.sessionPath, sessionState);

    const workflowState = await readJson(options.workflowPath);
    workflowState.updated_at = options.timestamp;
    const operatorSync = isRecord(workflowState.operator_sync)
      ? workflowState.operator_sync
      : {};
    operatorSync.tasks = taskSync;
    workflowState.operator_sync = operatorSync;
    await writeJson(options.workflowPath, workflowState);
  }

  static async resolveOperatorSyncSource(options: {
    preferredPath: string;
    devDir: string;
  }): Promise<string> {
    const candidates: string[] = [];
    const seen = new Set<string>();
    for (const candidate of [
      options.preferredPath,
      path.join(options.devDir, "PLAN.md"),
      path.join(options.devDir, "TASKS.md")
    ]) {
      const resolved = path.resolve(candidate);
      if (seen.has(resolved) || !(await exists(candidate))) {
        continue;
      }
      seen.add(resolved);
      candidates.push(candidate);
    }

    if (!candidates.length) {
      return options.preferredPath;
    }
    if (candidates.length === 1) {
      return candidates[0];
    }

    const ranked = await Promise.all(
      candidates.map(async (candidate) => {
        let pending = 999;
        try {
          pending = pendingCount(await readFile(candidate, "utf8"));
        } catch {
          pending = 999;
        }
        const stats = await stat(candidate, { bigint: true });
        return {
          candidate,
          pending,
          mtimeNs: stats.mtimeNs,
          tasksPenalty: path.basename(candidate) === "TASKS.md" ? 0 : 1
        };
      })
    );
    ranked.sort((left, right) => {
      if (left.pending !== right.pending) {
        return left.pending - right.pending;
      }
      if (left.mtimeNs !== right.mtimeNs) {
        return left.mtimeNs > right.mtimeNs ? -1 : 1;
      }
      return left.tasksPenalty - right.tasksPenalty;
    });
    return ranked[0].candidate;
  }
}
