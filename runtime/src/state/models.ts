import { createHash } from "node:crypto";
import path from "node:path";

export const STATE_SCHEMA_VERSION = 9;

export const ROADMAP_PHASE_LABELS: Record<string, string> = {
  phase_1: "Phase 1. Core Foundation and Repository Bootstrap",
  phase_2: "Phase 2. `.dev` State Model and Template Generation",
  phase_3: "Phase 3. Agent CLI Adapter and Single-Run Execution",
  phase_4: "Phase 4. Supervisor Validation, Continuation Loop, and Resume",
  phase_5: "Phase 5. CLI Operator Experience and Progress Visibility",
  phase_6: "Phase 6. Installer, Commands, and Environment Diagnostics",
  phase_7: "Phase 7. Hardening, Multi-Session, and Productization"
};

const PHASE_ID_INFERENCE_RE = /\bphase(?:\s+|[_-])0*([1-7])\b/i;

export type RepoGuidance = {
  ruleFiles: readonly string[];
  workflowFiles: readonly string[];
};

export type RepoGuidancePayload = {
  rule_files: string[];
  workflow_files: string[];
};

export type WorktreeLifecycleStatus = "planned" | "active" | "removed";

export type WorktreeOwner = {
  session_id?: string | null;
  run_id?: string | null;
  agent_role?: string | null;
};

export type ManagedWorktree = {
  worktree_id: string;
  source_repo_root: string;
  isolated_path: string;
  owner: WorktreeOwner;
  status?: WorktreeLifecycleStatus | string | null;
};

export type ManagedWorktreeState = {
  active_worktree_id: string | null;
  managed: ManagedWorktree[];
};

export function repoGuidanceToDict(guidance: RepoGuidance): RepoGuidancePayload {
  return {
    rule_files: [...guidance.ruleFiles],
    workflow_files: [...guidance.workflowFiles]
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function normalizedWorktreeId(value: unknown): string | null {
  if (value == null) {
    return null;
  }
  const normalized = String(value).trim();
  return normalized ? normalized : null;
}

function normalizedWorktreeStatus(value: unknown): WorktreeLifecycleStatus {
  return value === "active" || value === "removed" ? value : "planned";
}

function managedWorktreeFromUnknown(value: unknown): ManagedWorktree | null {
  if (!isRecord(value)) {
    return null;
  }
  const worktreeId = normalizedWorktreeId(value.worktree_id);
  if (worktreeId === null) {
    return null;
  }
  const sourceRepoRoot =
    value.source_repo_root == null ? "" : String(value.source_repo_root);
  const isolatedPath =
    value.isolated_path == null ? "" : String(value.isolated_path);
  const owner = isRecord(value.owner) ? value.owner : {};
  return {
    worktree_id: worktreeId,
    source_repo_root: sourceRepoRoot,
    isolated_path: isolatedPath,
    owner: {
      session_id: owner.session_id == null ? null : String(owner.session_id),
      run_id: owner.run_id == null ? null : String(owner.run_id),
      agent_role: owner.agent_role == null ? null : String(owner.agent_role)
    },
    status: normalizedWorktreeStatus(value.status)
  };
}

function normalizedManagedWorktree(worktree: ManagedWorktree): ManagedWorktree {
  const worktreeId = normalizedWorktreeId(worktree.worktree_id);
  if (worktreeId === null) {
    throw new Error("worktree_id must contain a non-empty value.");
  }
  return {
    worktree_id: worktreeId,
    source_repo_root: String(worktree.source_repo_root),
    isolated_path: String(worktree.isolated_path),
    owner: {
      session_id: worktree.owner.session_id == null ? null : String(worktree.owner.session_id),
      run_id: worktree.owner.run_id == null ? null : String(worktree.owner.run_id),
      agent_role: worktree.owner.agent_role == null ? null : String(worktree.owner.agent_role)
    },
    status: normalizedWorktreeStatus(worktree.status)
  };
}

function normalizeWorktreeRegistry(options: {
  managed: readonly ManagedWorktree[];
  activeWorktreeId: string | null;
}): ManagedWorktreeState {
  const deduped = new Map<string, ManagedWorktree>();
  for (const record of options.managed) {
    deduped.set(record.worktree_id, record);
  }
  let activeWorktreeId = options.activeWorktreeId;
  if (activeWorktreeId !== null && !deduped.has(activeWorktreeId)) {
    activeWorktreeId = null;
  }
  const managed = [...deduped.values()].map((record) => {
    if (record.worktree_id === activeWorktreeId) {
      return { ...record, status: "active" as const };
    }
    if (record.status === "active") {
      return { ...record, status: "planned" as const };
    }
    return record;
  });
  return { active_worktree_id: activeWorktreeId, managed };
}

export function managedWorktreeStateFromDict(payload: unknown): ManagedWorktreeState {
  if (!isRecord(payload)) {
    return { active_worktree_id: null, managed: [] };
  }
  const activeWorktreeId = normalizedWorktreeId(payload.active_worktree_id);
  const managed = Array.isArray(payload.managed)
    ? payload.managed
        .map(managedWorktreeFromUnknown)
        .filter((item): item is ManagedWorktree => item !== null)
    : [];
  return normalizeWorktreeRegistry({ managed, activeWorktreeId });
}

export function managedWorktreeStateIsEmpty(state: ManagedWorktreeState): boolean {
  return state.active_worktree_id === null && state.managed.length === 0;
}

export function managedWorktreeStateToDict(state: ManagedWorktreeState): ManagedWorktreeState {
  return {
    active_worktree_id: state.active_worktree_id,
    managed: state.managed.map((record) => ({ ...record, owner: { ...record.owner } }))
  };
}

export function upsertManagedWorktreeInState(
  state: ManagedWorktreeState,
  worktree: ManagedWorktree,
  options: { active?: boolean | null } = {}
): ManagedWorktreeState {
  const normalized = normalizedManagedWorktree(worktree);
  const managed = state.managed.map((record) =>
    record.worktree_id === normalized.worktree_id ? normalized : record
  );
  if (!managed.some((record) => record.worktree_id === normalized.worktree_id)) {
    managed.push(normalized);
  }

  let activeWorktreeId = state.active_worktree_id;
  if (options.active === true) {
    activeWorktreeId = normalized.worktree_id;
  } else if (options.active === false && activeWorktreeId === normalized.worktree_id) {
    activeWorktreeId = null;
  } else if (options.active == null && activeWorktreeId === normalized.worktree_id) {
    if (normalized.status !== "active") {
      activeWorktreeId = null;
    }
  }
  return normalizeWorktreeRegistry({ managed, activeWorktreeId });
}

export function forgetManagedWorktreeInState(
  state: ManagedWorktreeState,
  worktreeId: string
): ManagedWorktreeState {
  const normalizedId = normalizedWorktreeId(worktreeId);
  if (normalizedId === null) {
    return state;
  }
  const activeWorktreeId =
    state.active_worktree_id === normalizedId ? null : state.active_worktree_id;
  return normalizeWorktreeRegistry({
    managed: state.managed.filter((record) => record.worktree_id !== normalizedId),
    activeWorktreeId
  });
}

function asPosix(value: string): string {
  return value.split(path.sep).join("/");
}

export function discoverRepoGuidanceFromFiles(
  repoRoot: string,
  existingRelativeFiles: readonly string[],
  rulePaths: readonly string[] = []
): RepoGuidance {
  const existing = new Set(existingRelativeFiles.map(asPosix));
  let ruleFiles: string[];
  if (rulePaths.length) {
    const normalizedRoot = path.resolve(repoRoot);
    ruleFiles = rulePaths.map((candidate) => {
      const resolved = path.resolve(candidate);
      if (resolved.startsWith(`${normalizedRoot}${path.sep}`)) {
        return asPosix(path.relative(normalizedRoot, resolved));
      }
      return asPosix(candidate);
    });
  } else {
    ruleFiles = ["AGENTS.md", ".agents/AGENTS.md", ".dev/PROJECT.md", ".dev/ROADMAP.md"]
      .filter((candidate) => existing.has(candidate));
  }

  const workflowFiles = [...existing]
    .filter(
      (candidate) =>
        candidate.startsWith(".github/workflows/") &&
        (candidate.endsWith(".yml") || candidate.endsWith(".yaml"))
    )
    .sort();

  return { ruleFiles, workflowFiles };
}

function bulletLines(items: readonly string[]): string {
  return items.map((item) => `- ${item}`).join("\n");
}

function taskLines(items: readonly string[]): string {
  return items.map((item) => `- [ ] ${item}`).join("\n");
}

function guidanceNoteLines(repoGuidance?: RepoGuidance | null): string[] {
  const notes: string[] = [];
  if (!repoGuidance) {
    return notes;
  }
  if (repoGuidance.ruleFiles.length) {
    notes.push(`Repository rules to follow: ${repoGuidance.ruleFiles.join(", ")}`);
  }
  if (repoGuidance.workflowFiles.length) {
    notes.push(`Relevant repository workflows: ${repoGuidance.workflowFiles.join(", ")}`);
  }
  return notes;
}

function guidanceReviewTask(repoGuidance?: RepoGuidance | null): string {
  if (!repoGuidance || (!repoGuidance.ruleFiles.length && !repoGuidance.workflowFiles.length)) {
    return "Review the repository guidance that applies to the current goal";
  }
  return `Review repository guidance from ${[
    ...repoGuidance.ruleFiles,
    ...repoGuidance.workflowFiles
  ].join(", ")}`;
}

function activeRoadmapFocus(roadmapPhaseIds: readonly string[]): string[] {
  if (!roadmapPhaseIds.length) {
    return [ROADMAP_PHASE_LABELS.phase_2];
  }
  return roadmapPhaseIds.map((phaseId) => ROADMAP_PHASE_LABELS[phaseId] ?? phaseId);
}

export function summarizePromptGoal(promptText: string | null | undefined, fallback: string): string {
  if (promptText == null) {
    return fallback;
  }
  for (const rawLine of promptText.split(/\r?\n/)) {
    const stripped = rawLine.trim();
    if (!stripped || stripped === "```") {
      continue;
    }
    let normalized = stripped.replace(/^#+\s*/, "");
    normalized = normalized.replace(/^[-*+]\s+/, "");
    normalized = normalized.replace(/^\d+[.)]\s+/, "");
    normalized = normalized.split(/\s+/).join(" ");
    if (!normalized) {
      continue;
    }
    if (normalized.length > 120) {
      return `${normalized.slice(0, 117).trimEnd()}...`;
    }
    return normalized;
  }
  return fallback;
}

function roadmapPhaseInferenceCandidates(
  goal?: string | null,
  promptText?: string | null
): string[] {
  const candidates: string[] = [];
  if (typeof goal === "string" && goal.trim()) {
    candidates.push(goal.trim());
  }
  if (typeof promptText !== "string" || !promptText.trim()) {
    return candidates;
  }

  const summary = summarizePromptGoal(promptText, "");
  if (summary) {
    candidates.push(summary);
  }

  for (const marker of ["Task prompt:", "Original prompt:"]) {
    if (!promptText.includes(marker)) {
      continue;
    }
    const extracted = promptText.split(marker, 2)[1].trim();
    const extractedSummary = summarizePromptGoal(extracted, "");
    if (extractedSummary) {
      candidates.push(extractedSummary);
    }
  }
  return candidates;
}

export function inferPrimaryRoadmapPhaseId(options: {
  goal?: string | null;
  promptText?: string | null;
}): string | null {
  for (const candidate of roadmapPhaseInferenceCandidates(options.goal, options.promptText)) {
    const match = PHASE_ID_INFERENCE_RE.exec(candidate);
    if (match) {
      return `phase_${match[1]}`;
    }
  }
  return null;
}

export function normalizePromptText(promptText: string | null | undefined): string {
  if (promptText == null) {
    return "";
  }
  return promptText
    .trim()
    .split(/\r?\n/)
    .map((line) => line.trimEnd())
    .join("\n")
    .trim();
}

export function promptFingerprint(promptText: string | null | undefined): string | null {
  const normalized = normalizePromptText(promptText);
  if (!normalized) {
    return null;
  }
  return createHash("sha256").update(normalized, "utf8").digest("hex");
}

function promptRequirementLines(promptText: string | null | undefined): string[] {
  if (promptText == null) {
    return [];
  }
  const items: string[] = [];
  const seen = new Set<string>();
  for (const rawLine of promptText.split(/\r?\n/)) {
    const stripped = rawLine.trim();
    if (!stripped || stripped === "```") {
      continue;
    }
    let normalized = stripped.replace(/^#+\s*/, "");
    normalized = normalized.replace(/^[-*+]\s+/, "");
    normalized = normalized.replace(/^\d+[.)]\s+/, "");
    normalized = normalized.split(/\s+/).join(" ").trim().replace(/^[- ]+|[- ]+$/g, "");
    if (normalized.length < 8) {
      continue;
    }
    const key = normalized.toLocaleLowerCase();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    items.push(normalized.replace(/\.$/, ""));
    if (items.length === 4) {
      break;
    }
  }
  return items;
}

export type DashboardTemplateContext = {
  goal: string;
  activeDeliverySlice: string;
  activePhase: string;
  lastCompletedPhase: string;
  supervisorVerdict: string;
  escalationStatus: string;
  resumePoint: string;
  nextAction: readonly string[];
  notes: readonly string[];
  activeRoadmapFocus: readonly string[];
  risksAndWatchpoints: readonly string[];
};

export function renderDashboardValues(context: DashboardTemplateContext): Record<string, string> {
  return {
    goal: context.goal,
    active_delivery_slice: context.activeDeliverySlice,
    active_phase: context.activePhase,
    last_completed_phase: context.lastCompletedPhase,
    supervisor_verdict: context.supervisorVerdict,
    escalation_status: context.escalationStatus,
    resume_point: context.resumePoint,
    next_action: bulletLines(context.nextAction),
    notes: bulletLines(context.notes),
    active_roadmap_focus: bulletLines(context.activeRoadmapFocus),
    risks_and_watchpoints: bulletLines(context.risksAndWatchpoints)
  };
}

export type PlanTemplateContext = {
  taskItems: readonly string[];
  resumeCheckpoint: string;
};

export function renderPlanValues(context: PlanTemplateContext): Record<string, string> {
  return {
    task_items: taskLines(context.taskItems),
    resume_checkpoint: context.resumeCheckpoint
  };
}

export function defaultDashboardContext(options: {
  goal: string;
  roadmapPhaseIds: readonly string[];
  promptText?: string | null;
  repoGuidance?: RepoGuidance | null;
}): DashboardTemplateContext {
  const roadmapFocus = activeRoadmapFocus(options.roadmapPhaseIds);
  const guidanceNotes = guidanceNoteLines(options.repoGuidance);
  const promptSummary = summarizePromptGoal(options.promptText, options.goal);
  return {
    goal: options.goal,
    activeDeliverySlice: roadmapFocus.length
      ? `${roadmapFocus[0]} prompt-driven setup for ${promptSummary}`
      : `Prompt-driven setup for ${promptSummary}`,
    activePhase: "plan",
    lastCompletedPhase: "none",
    supervisorVerdict: "approved",
    escalationStatus: "approved",
    resumePoint: "Return to Plan and resume from the first unchecked PLAN item if setup is interrupted",
    nextAction: [
      `Review the prompt-derived goal and success criteria for ${options.goal}.`,
      guidanceReviewTask(options.repoGuidance),
      "Generate DASHBOARD.md and PLAN.md from the active prompt before implementation continues."
    ],
    notes: [
      "This file should show the actual progress of the active scope.",
      "workflow_state.json remains machine truth.",
      "PLAN.md should list prompt-derived development items in phase order.",
      ...guidanceNotes
    ],
    activeRoadmapFocus: roadmapFocus,
    risksAndWatchpoints: [
      "Do not overwrite existing operator-authored Markdown.",
      "Keep JSON merges additive so interrupted runs stay resumable.",
      "Keep session-scoped state isolated when multiple workflows run in parallel."
    ]
  };
}

export function defaultPlanContext(options: {
  goal: string;
  promptText?: string | null;
  repoGuidance?: RepoGuidance | null;
}): PlanTemplateContext {
  const promptRequirements = promptRequirementLines(options.promptText);
  let taskItems: string[];
  if (promptRequirements.length) {
    taskItems = promptRequirements.map((item, index) => `Phase ${index + 1}. ${item}`);
  } else {
    taskItems = [
      `Phase 1. Confirm the goal and success criteria for ${options.goal}`,
      `Phase 2. ${guidanceReviewTask(options.repoGuidance)}`,
      `Phase 3. Plan the smallest resumable slice for ${options.goal}`
    ];
  }

  const alreadyHasValidation = taskItems.some((item) => {
    const lower = item.toLocaleLowerCase();
    return ["validate", "test", "review", "sync"].some((keyword) => lower.includes(keyword));
  });
  if (!alreadyHasValidation) {
    taskItems = [
      ...taskItems,
      `Phase ${taskItems.length + 1}. Validate the slice and keep \`.dev\` state synchronized before completion`
    ];
  }

  return {
    taskItems,
    resumeCheckpoint:
      "Resume from the first unchecked PLAN item unless validation requires a return to earlier planning work."
  };
}
