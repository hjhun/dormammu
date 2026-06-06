import path from "node:path";

import {
  projectLifecycleExecutionFact,
  type JsonRecord
} from "./executionProjection.js";
import { OperatorSync } from "./operatorSync.js";
import { readJson, writeJson, type JsonObject } from "./persistence.js";
import { SessionManager } from "./sessionManager.js";

export type StateRepositoryOptions = {
  baseDevDir: string;
  sessionsDir: string;
  sessionId?: string | null;
  repoRoot?: string;
};

function isRecord(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function normalizedActivePhase(value: unknown): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const normalized = value.trim();
  return normalized ? normalized : null;
}

function normalizedRoadmapPhaseIds(value: unknown): string[] | null {
  if (!Array.isArray(value)) {
    return null;
  }
  return value
    .filter((item): item is string => typeof item === "string")
    .map((item) => item.trim())
    .filter(Boolean);
}

function syncLoopRequestExpectedRoadmapPhaseId(
  payload: JsonObject,
  roadmapPhaseIds: readonly string[]
): void {
  const loopPayload = payload.loop;
  if (!isRecord(loopPayload)) {
    return;
  }
  const requestPayload = loopPayload.request;
  if (!isRecord(requestPayload)) {
    return;
  }
  requestPayload.expected_roadmap_phase_id = roadmapPhaseIds[0] ?? null;
}

function jsonObjectFrom(payload: Readonly<JsonObject>): JsonObject {
  return { ...payload };
}

function normalizedHistory(value: unknown): JsonObject[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.filter((item): item is JsonObject => isRecord(item)).map((item) => ({ ...item }));
}

export class StateRepository {
  readonly baseDevDir: string;
  readonly sessionsDir: string;
  readonly sessionId: string | null;
  readonly repoRoot: string;
  readonly devDir: string;
  readonly logsDir: string;
  readonly sessionManager: SessionManager;
  readonly operatorSync: OperatorSync;

  constructor(options: StateRepositoryOptions) {
    this.baseDevDir = options.baseDevDir;
    this.sessionsDir = options.sessionsDir;
    this.sessionId = options.sessionId ? SessionManager.normalizeSessionId(options.sessionId) : null;
    this.repoRoot = options.repoRoot ?? path.dirname(this.baseDevDir);
    this.devDir =
      this.sessionId === null ? this.baseDevDir : path.join(this.sessionsDir, this.sessionId);
    this.logsDir = path.join(this.devDir, "logs");
    this.sessionManager = new SessionManager({
      baseDevDir: this.baseDevDir,
      sessionsDir: this.sessionsDir
    });
    this.operatorSync = new OperatorSync({ baseDevDir: this.baseDevDir });
  }

  forSession(sessionId: string): StateRepository {
    return new StateRepository({
      baseDevDir: this.baseDevDir,
      sessionsDir: this.sessionsDir,
      repoRoot: this.repoRoot,
      sessionId
    });
  }

  stateFile(name: string): string {
    return path.join(this.devDir, name);
  }

  async readSessionState(): Promise<JsonObject> {
    if (this.sessionId === null) {
      const repository = await this.activeSessionRepository();
      return repository.readSessionState();
    }
    return readJson(this.stateFile("session.json"));
  }

  async writeSessionState(payload: Readonly<JsonObject>): Promise<void> {
    if (this.sessionId === null) {
      const repository = await this.activeSessionRepository();
      await repository.writeSessionState(payload);
      return;
    }

    const sessionPayload = jsonObjectFrom(payload);
    await writeJson(this.stateFile("session.json"), sessionPayload);

    const activePhase = normalizedActivePhase(sessionPayload.active_phase);
    const roadmapPhaseIds = normalizedRoadmapPhaseIds(sessionPayload.active_roadmap_phase_ids);
    if (activePhase !== null || roadmapPhaseIds !== null) {
      const workflowState = await readJson(this.stateFile("workflow_state.json"));
      if (activePhase !== null) {
        const workflowBlock = isRecord(workflowState.workflow) ? workflowState.workflow : {};
        workflowBlock.active_phase = activePhase;
        workflowState.workflow = workflowBlock;
      }
      if (roadmapPhaseIds !== null) {
        const roadmapBlock = isRecord(workflowState.roadmap) ? workflowState.roadmap : {};
        roadmapBlock.active_phase_ids = roadmapPhaseIds;
        workflowState.roadmap = roadmapBlock;
        syncLoopRequestExpectedRoadmapPhaseId(workflowState, roadmapPhaseIds);
      }
      if ("updated_at" in sessionPayload) {
        workflowState.updated_at = sessionPayload.updated_at;
      }
      await writeJson(this.stateFile("workflow_state.json"), workflowState);
    }
    await this.syncRootIndex();
  }

  async readWorkflowState(): Promise<JsonObject> {
    if (this.sessionId === null) {
      const repository = await this.activeSessionRepository();
      return repository.readWorkflowState();
    }
    return readJson(this.stateFile("workflow_state.json"));
  }

  async writeWorkflowState(payload: Readonly<JsonObject>): Promise<void> {
    if (this.sessionId === null) {
      const repository = await this.activeSessionRepository();
      await repository.writeWorkflowState(payload);
      return;
    }

    const workflowPayload = jsonObjectFrom(payload);
    await writeJson(this.stateFile("workflow_state.json"), workflowPayload);

    const workflowBlock = isRecord(workflowPayload.workflow) ? workflowPayload.workflow : {};
    const roadmapBlock = isRecord(workflowPayload.roadmap) ? workflowPayload.roadmap : {};
    const activePhase = normalizedActivePhase(workflowBlock.active_phase);
    const roadmapPhaseIds = normalizedRoadmapPhaseIds(roadmapBlock.active_phase_ids);
    if (activePhase !== null || roadmapPhaseIds !== null) {
      const sessionState = await readJson(this.stateFile("session.json"));
      if (activePhase !== null) {
        sessionState.active_phase = activePhase;
      }
      if (roadmapPhaseIds !== null) {
        sessionState.active_roadmap_phase_ids = roadmapPhaseIds;
        syncLoopRequestExpectedRoadmapPhaseId(sessionState, roadmapPhaseIds);
      }
      if ("updated_at" in workflowPayload) {
        sessionState.updated_at = workflowPayload.updated_at;
      }
      await writeJson(this.stateFile("session.json"), sessionState);
    }
    await this.syncRootIndex();
  }

  async writeStatePair(options: {
    sessionPayload: Readonly<JsonObject>;
    workflowPayload: Readonly<JsonObject>;
  }): Promise<void> {
    if (this.sessionId === null) {
      const repository = await this.activeSessionRepository();
      await repository.writeStatePair(options);
      return;
    }

    const sessionState = jsonObjectFrom(options.sessionPayload);
    const workflowState = jsonObjectFrom(options.workflowPayload);
    const workflowBlock = isRecord(workflowState.workflow) ? workflowState.workflow : {};
    const roadmapBlock = isRecord(workflowState.roadmap) ? workflowState.roadmap : {};
    workflowState.workflow = workflowBlock;
    workflowState.roadmap = roadmapBlock;

    let activePhase = normalizedActivePhase(workflowBlock.active_phase);
    if (activePhase === null) {
      activePhase = normalizedActivePhase(sessionState.active_phase);
    }
    if (activePhase !== null) {
      sessionState.active_phase = activePhase;
      workflowBlock.active_phase = activePhase;
    }

    let roadmapPhaseIds = normalizedRoadmapPhaseIds(roadmapBlock.active_phase_ids);
    if (roadmapPhaseIds === null) {
      roadmapPhaseIds = normalizedRoadmapPhaseIds(sessionState.active_roadmap_phase_ids);
    }
    if (roadmapPhaseIds !== null) {
      sessionState.active_roadmap_phase_ids = roadmapPhaseIds;
      roadmapBlock.active_phase_ids = roadmapPhaseIds;
      syncLoopRequestExpectedRoadmapPhaseId(sessionState, roadmapPhaseIds);
      syncLoopRequestExpectedRoadmapPhaseId(workflowState, roadmapPhaseIds);
    }

    const updatedAt = workflowState.updated_at ?? sessionState.updated_at;
    if (updatedAt !== undefined) {
      sessionState.updated_at = updatedAt;
      workflowState.updated_at = updatedAt;
    }

    const sessionId = this.sessionId;
    await this.operatorSync.rootIndexLock(async () => {
      await writeJson(this.stateFile("session.json"), sessionState);
      await writeJson(this.stateFile("workflow_state.json"), workflowState);
      if ((await this.sessionManager.readActiveSessionId()) === sessionId) {
        await this.operatorSync.writeRootIndexLocked({
          sessionDevDir: this.devDir,
          sessionId,
          stateRoot: this.stateRootDisplay(),
          timestamp: String(updatedAt ?? new Date().toISOString()),
          listSessions: () => this.sessionManager.listSessions()
        });
      }
    });
  }

  async recordHookEvent(
    payload: Readonly<JsonObject>,
    options: { historyLimit?: number } = {}
  ): Promise<void> {
    if (this.sessionId === null) {
      const activeSessionId = await this.sessionManager.readActiveSessionId();
      if (activeSessionId === null) {
        return;
      }
      await this.forSession(activeSessionId).recordHookEvent(payload, options);
      return;
    }

    const historyLimit = options.historyLimit ?? 25;
    const timestamp = String(payload.recorded_at ?? new Date().toISOString());
    const entry = jsonObjectFrom(payload);
    const sessionState = await readJson(this.stateFile("session.json"));
    const workflowState = await readJson(this.stateFile("workflow_state.json"));
    for (const state of [sessionState, workflowState]) {
      state.updated_at = timestamp;
      const hooksBlock = isRecord(state.hooks) ? state.hooks : {};
      const history = normalizedHistory(hooksBlock.history);
      history.push(entry);
      state.hooks = {
        updated_at: timestamp,
        latest_event: entry,
        history: history.slice(-historyLimit)
      };
    }
    await writeJson(this.stateFile("session.json"), sessionState);
    await writeJson(this.stateFile("workflow_state.json"), workflowState);
    await this.syncRootIndex(timestamp);
  }

  async recordLifecycleEvent(
    event: Readonly<JsonObject> | { toDict: () => JsonObject },
    options: { historyLimit?: number } = {}
  ): Promise<void> {
    if (this.sessionId === null) {
      const activeSessionId = await this.sessionManager.readActiveSessionId();
      if (activeSessionId === null) {
        return;
      }
      await this.forSession(activeSessionId).recordLifecycleEvent(event, options);
      return;
    }

    const eventPayload =
      "toDict" in event && typeof event.toDict === "function"
        ? event.toDict()
        : jsonObjectFrom(event);
    const timestamp = String(eventPayload.timestamp ?? new Date().toISOString());
    const sessionState = await readJson(this.stateFile("session.json"));
    const workflowState = await readJson(this.stateFile("workflow_state.json"));
    for (const state of [sessionState, workflowState]) {
      state.updated_at = timestamp;
      const lifecycleBlock = isRecord(state.lifecycle) ? state.lifecycle : {};
      const history = normalizedHistory(lifecycleBlock.history);
      history.push(eventPayload);
      state.lifecycle = {
        updated_at: timestamp,
        latest_event: eventPayload,
        history: history.slice(-(options.historyLimit ?? 200))
      };
      projectLifecycleExecutionFact(state as JsonRecord, {
        eventPayload,
        timestamp
      });
    }
    await writeJson(this.stateFile("session.json"), sessionState);
    await writeJson(this.stateFile("workflow_state.json"), workflowState);
    await this.syncRootIndex(timestamp);
  }

  private async activeSessionRepository(): Promise<StateRepository> {
    const sessionId = await this.sessionManager.readActiveSessionId();
    if (sessionId === null) {
      throw new Error("No active session is available.");
    }
    return this.forSession(sessionId);
  }

  private async syncRootIndex(timestamp?: string): Promise<void> {
    if (this.sessionId === null) {
      return;
    }
    if ((await this.sessionManager.readActiveSessionId()) !== this.sessionId) {
      return;
    }
    await this.operatorSync.syncActiveRootOperatorMirrorsIntoSession({
      sessionDevDir: this.devDir,
      activeSessionId: this.sessionId
    });
    await this.operatorSync.writeRootIndexForSession({
      sessionDevDir: this.devDir,
      sessionId: this.sessionId,
      stateRoot: this.stateRootDisplay(),
      timestamp: timestamp ?? new Date().toISOString(),
      listSessions: () => this.sessionManager.listSessions()
    });
  }

  private stateRootDisplay(): string {
    const relative = path.relative(this.repoRoot, this.devDir);
    if (relative && !relative.startsWith("..") && !path.isAbsolute(relative)) {
      return relative.split(path.sep).join("/");
    }
    return this.devDir;
  }
}
