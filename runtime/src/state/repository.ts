import path from "node:path";
import { mkdir, readdir, readFile, stat, writeFile } from "node:fs/promises";

import {
  projectLifecycleExecutionFact,
  type JsonRecord
} from "./executionProjection.js";
import { OperatorSync } from "./operatorSync.js";
import { ensureJsonFile, readJson, writeJson, type JsonObject } from "./persistence.js";
import { SessionManager } from "./sessionManager.js";
import {
  defaultDashboardContext,
  defaultPlanContext,
  discoverRepoGuidanceFromFiles,
  promptFingerprint,
  type RepoGuidance,
  renderDashboardValues,
  renderPlanValues,
  STATE_SCHEMA_VERSION,
  summarizePromptGoal
} from "./models.js";
import { defaultWorkflowPolicyState, type RequestClass } from "../workflowPolicy.js";

export type StateRepositoryOptions = {
  baseDevDir: string;
  sessionsDir: string;
  sessionId?: string | null;
  repoRoot?: string;
};

export type BootstrapArtifacts = {
  dashboard: string;
  plan: string;
  tasks: string;
  session: string;
  workflowState: string;
  logsDir: string;
  prompt?: string;
};

export type EnsureBootstrapStateOptions = {
  goal?: string | null;
  promptText?: string | null;
  activeRoadmapPhaseIds?: readonly string[] | null;
  timestamp?: string;
  repoGuidance?: RepoGuidance | null;
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

async function writeIfMissing(filePath: string, text: string): Promise<void> {
  if (await exists(filePath)) {
    return;
  }
  await writeFile(filePath, text, "utf8");
}

async function listRelativeFiles(root: string): Promise<string[]> {
  const files: string[] = [];
  async function walk(relativeDir: string): Promise<void> {
    const absoluteDir = path.join(root, relativeDir);
    let entries;
    try {
      entries = await readdir(absoluteDir, { withFileTypes: true });
    } catch (error) {
      if (
        error instanceof Error &&
        "code" in error &&
        (error as NodeJS.ErrnoException).code === "ENOENT"
      ) {
        return;
      }
      throw error;
    }
    for (const entry of entries) {
      const relativePath = relativeDir ? path.join(relativeDir, entry.name) : entry.name;
      if (entry.isDirectory()) {
        if ([".git", "node_modules", "__pycache__", "sessions"].includes(entry.name)) {
          continue;
        }
        await walk(relativePath);
      } else if (entry.isFile()) {
        files.push(relativePath.split(path.sep).join("/"));
      }
    }
  }
  await walk("");
  return files.sort();
}

function substitute(template: string, values: Readonly<Record<string, string>>): string {
  return template.replace(/\$\{([^}]+)\}/g, (_match, key: string) => values[key] ?? "");
}

function renderDashboardMarkdown(values: Readonly<Record<string, string>>): string {
  return substitute(
    `# DASHBOARD

## Actual Progress

- Goal: \${goal}
- Prompt-driven scope: \${active_delivery_slice}
- Active roadmap focus:
\${active_roadmap_focus}
- Current workflow phase: \${active_phase}
- Last completed workflow phase: \${last_completed_phase}
- Supervisor verdict: \`\${supervisor_verdict}\`
- Escalation status: \`\${escalation_status}\`
- Resume point: \${resume_point}

## In Progress

\${next_action}

## Progress Notes

\${notes}

## Risks And Watchpoints

\${risks_and_watchpoints}
`,
    values
  );
}

function renderPlanMarkdown(values: Readonly<Record<string, string>>): string {
  return substitute(
    `# PLAN

## Prompt-Derived Implementation Plan

\${task_items}

## Resume Checkpoint

\${resume_checkpoint}
`,
    values
  );
}

function renderTasksMarkdown(values: Readonly<Record<string, string>>): string {
  return substitute(
    `# TASKS

## Prompt-Derived Development Queue

\${task_items}

## Resume Checkpoint

\${resume_checkpoint}
`,
    values
  );
}

function statePath(stateRoot: string, filename: string): string {
  return stateRoot === ".dev" ? `.dev/${filename}` : `${stateRoot}/${filename}`;
}

function repoGuidancePayload(repoGuidance: RepoGuidance | null | undefined): JsonObject {
  return {
    rule_files: repoGuidance ? [...repoGuidance.ruleFiles] : [],
    workflow_files: repoGuidance ? [...repoGuidance.workflowFiles] : []
  };
}

function sourceGoalFiles(repoGuidance: RepoGuidance | null | undefined): string[] {
  return [
    ...new Set([
      ".dev/PROJECT.md",
      ".dev/ROADMAP.md",
      ...(repoGuidance ? repoGuidance.ruleFiles : ["AGENTS.md", ".agents/AGENTS.md"])
    ])
  ];
}

function defaultIntakeState(promptText: string | null | undefined): JsonObject {
  if (promptText && promptText.trim()) {
    return {
      request_class: "full_workflow",
      confidence: 0.5,
      rationale: "Prompt provided during TypeScript bootstrap; defaulting to full_workflow until intake classification is ported.",
      has_interface_risk: false,
      requires_test_strategy: true,
      execution_mode: "standard"
    };
  }
  return {
    request_class: "direct_response",
    confidence: 0.5,
    rationale: "No prompt provided at bootstrap; defaulting to direct_response.",
    has_interface_risk: false,
    requires_test_strategy: false,
    execution_mode: "standard"
  };
}

function defaultSessionState(options: {
  timestamp: string;
  roadmapPhaseIds: readonly string[];
  goal: string;
  stateRoot: string;
  promptText?: string | null;
  sessionId: string;
  runType: string;
  repoGuidance?: RepoGuidance | null;
}): JsonObject {
  return {
    session_id: options.sessionId,
    created_at: options.timestamp,
    updated_at: options.timestamp,
    run_type: options.runType,
    status: "active",
    state_schema_version: STATE_SCHEMA_VERSION,
    active_phase: "plan",
    active_roadmap_phase_ids: [...options.roadmapPhaseIds],
    resume_token: "plan:bootstrap",
    last_safe_checkpoint: {
      phase: "plan",
      timestamp: options.timestamp,
      description: "Bootstrap files were initialized."
    },
    bootstrap: {
      goal: options.goal,
      captured_at: options.timestamp,
      state_root: options.stateRoot,
      prompt_summary: summarizePromptGoal(options.promptText, options.goal),
      prompt_fingerprint: promptFingerprint(options.promptText),
      repo_guidance: repoGuidancePayload(options.repoGuidance)
    },
    task_sync: {
      source: statePath(options.stateRoot, "TASKS.md"),
      synced_at: options.timestamp,
      current_workflow: null,
      resume_checkpoint: null,
      pending_count: 0,
      completed_count: 0,
      next_pending_task: null,
      items: []
    },
    next_action: "Review the generated workflow files and continue planning.",
    notes: [
      "Resume from planning unless supervisor evidence requires an earlier phase.",
      "Interpret a retry limit of -1 as infinite repetition once loop support exists."
    ],
    loop: { status: "idle" },
    lifecycle: {
      updated_at: options.timestamp,
      latest_event: null,
      history: []
    },
    supervisor_report: {
      path: statePath(options.stateRoot, "supervisor_report.md"),
      status: "not_run"
    },
    latest_continuation_prompt: null
  };
}

function defaultWorkflowState(options: {
  timestamp: string;
  roadmapPhaseIds: readonly string[];
  goal: string;
  stateRoot: string;
  promptText?: string | null;
  repoGuidance?: RepoGuidance | null;
}): JsonObject {
  const intakeState = defaultIntakeState(options.promptText);
  const requestClass = String(intakeState.request_class ?? "direct_response") as RequestClass;
  return {
    version: 1,
    state_schema_version: STATE_SCHEMA_VERSION,
    initialized_at: options.timestamp,
    updated_at: options.timestamp,
    mode: "supervised",
    source_of_truth: {
      goal: sourceGoalFiles(options.repoGuidance),
      machine_state: statePath(options.stateRoot, "workflow_state.json"),
      operator_state: [
        statePath(options.stateRoot, "DASHBOARD.md"),
        statePath(options.stateRoot, "PLAN.md"),
        statePath(options.stateRoot, "TASKS.md")
      ]
    },
    state_schema: {
      dashboard_template: "templates/dev/dashboard.md.tmpl",
      plan_template: "templates/dev/plan.md.tmpl",
      task_markers: {
        pending: "[ ]",
        completed: "[O]"
      },
      task_sync_source: statePath(options.stateRoot, "TASKS.md")
    },
    workflow: {
      active_phase: "plan",
      last_completed_phase: "none",
      allowed_sequence: [
        "plan",
        "design",
        "develop",
        "test_authoring",
        "build_and_deploy",
        "test_and_review",
        "final_verification",
        "commit"
      ],
      resume_from_phase: "plan"
    },
    roadmap: {
      active_phase_ids: [...options.roadmapPhaseIds],
      priority_order: [
        "phase_1",
        "phase_2",
        "phase_3",
        "phase_4",
        "phase_5",
        "phase_6",
        "phase_7"
      ]
    },
    supervisor: {
      skill: "supervising-agent",
      verdict: "approved",
      escalation: "approved",
      reason: "Bootstrap state was initialized successfully."
    },
    bootstrap: {
      goal: options.goal,
      captured_at: options.timestamp,
      state_root: options.stateRoot,
      prompt_summary: summarizePromptGoal(options.promptText, options.goal),
      prompt_fingerprint: promptFingerprint(options.promptText),
      repo_guidance: repoGuidancePayload(options.repoGuidance)
    },
    intake: intakeState,
    workflow_policy: defaultWorkflowPolicyState(requestClass),
    lifecycle: {
      updated_at: options.timestamp,
      latest_event: null,
      history: []
    },
    execution: {
      latest_run_id: null,
      latest_stage_result: null,
      stage_results: {}
    }
  };
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

  async restoreSession(sessionId: string, options: { timestamp?: string } = {}): Promise<BootstrapArtifacts> {
    if (this.sessionId !== null) {
      throw new Error("restoreSession must be called from the active repository.");
    }
    const normalizedSessionId = SessionManager.normalizeSessionId(sessionId);
    const targetDir = path.join(this.sessionsDir, normalizedSessionId);
    if (!(await exists(targetDir))) {
      throw new Error(`Saved session was not found: ${normalizedSessionId}`);
    }
    const sessionRepository = this.forSession(normalizedSessionId);
    await sessionRepository.ensurePlanFile(path.join(targetDir, "PLAN.md"));
    for (const filename of ["DASHBOARD.md", "PLAN.md", "session.json", "workflow_state.json"]) {
      if (!(await exists(path.join(targetDir, filename)))) {
        throw new Error(`Saved session ${normalizedSessionId} is missing required file: ${filename}`);
      }
    }

    await mkdir(this.baseDevDir, { recursive: true });
    await mkdir(this.sessionsDir, { recursive: true });
    await this.sessionManager.migrateLegacyRootSnapshot({ timestamp: options.timestamp });
    const timestamp = options.timestamp ?? new Date().toISOString();
    const restoredRoadmapPhaseIds = await sessionRepository.existingRoadmapPhaseIds();
    if (restoredRoadmapPhaseIds.length) {
      await sessionRepository.operatorSync.refreshActiveRoadmapPhaseIds({
        sessionPath: sessionRepository.stateFile("session.json"),
        workflowPath: sessionRepository.stateFile("workflow_state.json"),
        roadmapPhaseIds: restoredRoadmapPhaseIds,
        timestamp
      });
    }
    await this.operatorSync.writeRootIndexForSession({
      sessionDevDir: sessionRepository.devDir,
      sessionId: normalizedSessionId,
      stateRoot: sessionRepository.stateRootDisplay(),
      timestamp,
      listSessions: () => this.sessionManager.listSessions()
    });
    return sessionRepository.artifactsForDir(targetDir);
  }

  async ensureBootstrapState(
    options: EnsureBootstrapStateOptions = {}
  ): Promise<BootstrapArtifacts> {
    if (this.sessionId === null) {
      return this.ensureRootBootstrapState(options);
    }
    return this.ensureSessionBootstrapState(options);
  }

  private async ensureRootBootstrapState(
    options: EnsureBootstrapStateOptions
  ): Promise<BootstrapArtifacts> {
    const timestamp = options.timestamp ?? new Date().toISOString();
    await mkdir(this.baseDevDir, { recursive: true });
    await mkdir(this.sessionsDir, { recursive: true });

    let activeSessionId = await this.sessionManager.readActiveSessionId();
    if (activeSessionId === null) {
      activeSessionId = await this.sessionManager.migrateLegacyRootSnapshot({ timestamp });
    }
    if (activeSessionId === null) {
      activeSessionId = await this.sessionManager.generatedSessionId(timestamp);
    }

    const sessionRepository = this.forSession(activeSessionId);
    const artifacts = await sessionRepository.ensureSessionBootstrapState({
      ...options,
      timestamp
    });
    await this.operatorSync.writeRootIndexForSession({
      sessionDevDir: sessionRepository.devDir,
      sessionId: activeSessionId,
      stateRoot: sessionRepository.stateRootDisplay(),
      timestamp,
      listSessions: () => this.sessionManager.listSessions()
    });
    return artifacts;
  }

  private async ensureSessionBootstrapState(
    options: EnsureBootstrapStateOptions
  ): Promise<BootstrapArtifacts> {
    if (this.sessionId === null) {
      throw new Error("ensureSessionBootstrapState requires a session repository.");
    }

    const timestamp = options.timestamp ?? new Date().toISOString();
    const repoGuidance =
      options.repoGuidance ?? (await this.discoverRepoGuidance());
    const roadmapPhaseIds = await this.resolveActiveRoadmapPhaseIds(
      options.activeRoadmapPhaseIds
    );
    const goal =
      options.goal?.trim() ||
      (await this.existingGoal()) ||
      summarizePromptGoal(
        options.promptText,
        "Bootstrap dormammu in the current repository."
      );
    const stateRoot = this.stateRootDisplay();

    await mkdir(this.devDir, { recursive: true });
    await mkdir(this.logsDir, { recursive: true });
    await mkdir(this.sessionsDir, { recursive: true });

    const dashboardContext = defaultDashboardContext({
      goal,
      roadmapPhaseIds,
      promptText: options.promptText,
      repoGuidance
    });
    const planContext = defaultPlanContext({
      goal,
      promptText: options.promptText,
      repoGuidance
    });
    const dashboardValues = renderDashboardValues(dashboardContext);
    const planValues = renderPlanValues(planContext);

    const sessionPath = this.stateFile("session.json");
    const workflowPath = this.stateFile("workflow_state.json");
    const sessionDefaults = defaultSessionState({
      timestamp,
      roadmapPhaseIds,
      goal,
      stateRoot,
      promptText: options.promptText,
      sessionId: this.sessionId,
      runType: "session",
      repoGuidance
    });
    const workflowDefaults = defaultWorkflowState({
      timestamp,
      roadmapPhaseIds,
      goal,
      stateRoot,
      promptText: options.promptText,
      repoGuidance
    });
    const shouldReset = await this.shouldRegenerateOperatorState(options.promptText);

    if (shouldReset) {
      await writeFile(this.stateFile("DASHBOARD.md"), renderDashboardMarkdown(dashboardValues), "utf8");
      await writeFile(this.stateFile("PLAN.md"), renderPlanMarkdown(planValues), "utf8");
      await writeFile(this.stateFile("TASKS.md"), renderTasksMarkdown(planValues), "utf8");
      await writeJson(sessionPath, sessionDefaults);
      await writeJson(workflowPath, workflowDefaults);
    } else {
      await writeIfMissing(this.stateFile("DASHBOARD.md"), renderDashboardMarkdown(dashboardValues));
      await writeIfMissing(this.stateFile("PLAN.md"), renderPlanMarkdown(planValues));
      await writeIfMissing(this.stateFile("TASKS.md"), renderTasksMarkdown(planValues));
      await ensureJsonFile(sessionPath, sessionDefaults);
      await ensureJsonFile(workflowPath, workflowDefaults);
    }
    await this.operatorSync.refreshActiveRoadmapPhaseIds({
      sessionPath,
      workflowPath,
      roadmapPhaseIds,
      timestamp
    });
    await this.operatorSync.syncOperatorState({
      sessionPath,
      workflowPath,
      operatorTaskPath: this.stateFile("TASKS.md"),
      timestamp,
      devDir: this.devDir,
      displayStatePath: (filePath) => this.displayStatePath(filePath)
    });
    await this.syncRootIndex(timestamp);
    return this.artifactsForDir(this.devDir);
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

  private displayStatePath(filePath: string): string {
    const relative = path.relative(this.repoRoot, filePath);
    if (relative && !relative.startsWith("..") && !path.isAbsolute(relative)) {
      return relative.split(path.sep).join("/");
    }
    return filePath;
  }

  private async discoverRepoGuidance(): Promise<RepoGuidance> {
    return discoverRepoGuidanceFromFiles(this.repoRoot, await listRelativeFiles(this.repoRoot));
  }

  private async artifactsForDir(directory: string): Promise<BootstrapArtifacts> {
    const promptPath = path.join(directory, "PROMPT.md");
    const artifacts: BootstrapArtifacts = {
      dashboard: path.join(directory, "DASHBOARD.md"),
      plan: path.join(directory, "PLAN.md"),
      tasks: path.join(directory, "TASKS.md"),
      session: path.join(directory, "session.json"),
      workflowState: path.join(directory, "workflow_state.json"),
      logsDir: path.join(directory, "logs")
    };
    if (await exists(promptPath)) {
      artifacts.prompt = promptPath;
    }
    return artifacts;
  }

  private async ensurePlanFile(planPath: string): Promise<void> {
    if (await exists(planPath)) {
      return;
    }
    const tasksPath = this.stateFile("TASKS.md");
    if (await exists(tasksPath)) {
      await writeFile(planPath, await readFile(tasksPath, "utf8"), "utf8");
    }
  }

  private async resolveActiveRoadmapPhaseIds(
    activeRoadmapPhaseIds: readonly string[] | null | undefined
  ): Promise<string[]> {
    const explicit = normalizedRoadmapPhaseIds(activeRoadmapPhaseIds);
    if (explicit !== null && explicit.length) {
      return explicit;
    }
    const existing = await this.existingRoadmapPhaseIds();
    if (existing.length) {
      return existing;
    }
    return ["phase_1"];
  }

  private async existingRoadmapPhaseIds(): Promise<string[]> {
    for (const filename of ["workflow_state.json", "session.json"]) {
      const candidate = this.stateFile(filename);
      if (!(await exists(candidate))) {
        continue;
      }
      let payload: JsonObject;
      try {
        payload = await readJson(candidate);
      } catch {
        continue;
      }
      const direct = normalizedRoadmapPhaseIds(payload.active_roadmap_phase_ids);
      if (direct !== null && direct.length) {
        return direct;
      }
      const roadmap = isRecord(payload.roadmap) ? payload.roadmap : {};
      const roadmapPhaseIds = normalizedRoadmapPhaseIds(roadmap.active_phase_ids);
      if (roadmapPhaseIds !== null && roadmapPhaseIds.length) {
        return roadmapPhaseIds;
      }
    }
    return [];
  }

  private async existingGoal(): Promise<string | null> {
    for (const filename of ["session.json", "workflow_state.json"]) {
      const candidate = this.stateFile(filename);
      if (!(await exists(candidate))) {
        continue;
      }
      let payload: JsonObject;
      try {
        payload = await readJson(candidate);
      } catch {
        continue;
      }
      const bootstrap = isRecord(payload.bootstrap) ? payload.bootstrap : {};
      if (typeof bootstrap.goal === "string" && bootstrap.goal.trim()) {
        return bootstrap.goal.trim();
      }
    }
    return null;
  }

  private async shouldRegenerateOperatorState(
    promptText: string | null | undefined
  ): Promise<boolean> {
    if (
      !(await exists(this.stateFile("DASHBOARD.md"))) ||
      !(await exists(this.stateFile("PLAN.md")))
    ) {
      return false;
    }
    const incomingFingerprint = promptFingerprint(promptText);
    if (incomingFingerprint === null) {
      return false;
    }
    const storedFingerprint = await this.storedPromptFingerprint();
    return storedFingerprint !== null && storedFingerprint !== incomingFingerprint;
  }

  private async storedPromptFingerprint(): Promise<string | null> {
    for (const filename of ["session.json", "workflow_state.json"]) {
      const candidate = this.stateFile(filename);
      if (!(await exists(candidate))) {
        continue;
      }
      let payload: JsonObject;
      try {
        payload = await readJson(candidate);
      } catch {
        continue;
      }
      const bootstrap = isRecord(payload.bootstrap) ? payload.bootstrap : {};
      if (typeof bootstrap.prompt_fingerprint === "string") {
        const fingerprint = bootstrap.prompt_fingerprint.trim();
        if (fingerprint) {
          return fingerprint;
        }
      }
    }
    return null;
  }
}
