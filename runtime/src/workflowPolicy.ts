export type RequestClass =
  | "direct_response"
  | "planning_only"
  | "light_edit"
  | "full_workflow";

export const ALL_PHASES = [
  "refine",
  "plan",
  "evaluator_check",
  "design",
  "develop",
  "test_author",
  "test_and_review",
  "final_verify",
  "commit",
  "evaluate"
] as const;

export type WorkflowPhase = (typeof ALL_PHASES)[number];

export const PHASE_LABELS: Record<WorkflowPhase, string> = {
  refine: "Refine - refiner",
  plan: "Plan - planner",
  evaluator_check: "Evaluator check - evaluator (post-plan)",
  design: "Design - architect",
  develop: "Develop - developer",
  test_author: "Test Author - developer/reviewer validation support",
  test_and_review: "Test and Review - reviewer",
  final_verify: "Final Verify - supervisor gate",
  commit: "Commit - committer",
  evaluate: "Evaluate - supervisor final assessment"
};

const DIRECT_SKIP: Record<WorkflowPhase, string> = {
  refine:
    "direct_response tasks are read-only or analysis work; REQUIREMENTS.md is not needed when no code changes are planned.",
  plan:
    "direct_response tasks do not require a multi-phase implementation plan; a single inline execution is sufficient.",
  evaluator_check:
    "evaluator checkpoint is only meaningful after planning; not applicable for direct_response.",
  design: "no interface or implementation decisions are needed for read-only tasks.",
  develop: "no code changes are expected for direct_response tasks.",
  test_author: "no new code means no new tests are needed.",
  test_and_review: "nothing to validate when no code was changed.",
  final_verify:
    "supervisor verification targets code-change correctness; not applicable for read-only work.",
  commit: "no repository changes to commit for direct_response tasks.",
  evaluate: "goals-scheduler post-commit evaluation; not applicable for direct_response tasks."
};

const PLANNING_ONLY_SKIP: Record<WorkflowPhase, string> = {
  refine: "",
  plan: "",
  evaluator_check:
    "planning_only tasks need a planner decision, but not the goals-style post-plan evaluator checkpoint unless explicitly scheduled.",
  design:
    "deep_thinking structure deliberation is captured by the planner output for this request class; no separate implementation design stage is required.",
  develop: "planning_only tasks are about structure or workflow direction; no product-code implementation is expected.",
  test_author: "no product-code implementation means no new automated test code is required.",
  test_and_review:
    "developer and tester loops are skipped because there is no executable implementation to validate.",
  final_verify:
    "planner output is the terminal artifact for planning_only tasks; there is no downstream implementation slice to verify.",
  commit:
    "planning_only runs normally produce planning artifacts only and do not require a source commit unless the user explicitly asks.",
  evaluate: "goals-scheduler post-commit evaluation; not applicable for planning_only tasks."
};

const LIGHT_SKIP: Record<WorkflowPhase, string> = {
  refine:
    "light_edit tasks use normalize mode; a full REQUIREMENTS.md is optional when scope is trivially bounded.",
  plan: "",
  evaluator_check:
    "post-plan evaluator checkpoint is reserved for high-risk or ambiguous plans; light edits do not warrant this overhead.",
  design:
    "light edits are single-file or config changes that do not require interface or contract decisions before implementation.",
  develop: "",
  test_author:
    "test authoring is optional when the change carries no behavior risk; include when the change touches executable logic.",
  test_and_review: "",
  final_verify: "",
  commit: "",
  evaluate: "goals-scheduler post-commit evaluation; not applicable for manually-invoked light_edit runs."
};

const FULL_SKIP: Record<WorkflowPhase, string> = {
  refine: "",
  plan: "",
  evaluator_check: "",
  design: "",
  develop: "",
  test_author: "",
  test_and_review: "",
  final_verify: "",
  commit: "",
  evaluate:
    "final evaluating-agent is added only for goals-scheduler runs, not for manually-invoked full_workflow runs."
};

export const SKIP_POLICY: Record<RequestClass, Record<WorkflowPhase, string>> = {
  direct_response: DIRECT_SKIP,
  planning_only: PLANNING_ONLY_SKIP,
  light_edit: LIGHT_SKIP,
  full_workflow: FULL_SKIP
};

export const MINIMAL_WORKFLOWS: Record<RequestClass, WorkflowPhase[]> = {
  direct_response: [],
  planning_only: ["refine", "plan"],
  light_edit: ["plan", "develop", "test_and_review", "final_verify", "commit"],
  full_workflow: [
    "refine",
    "plan",
    "evaluator_check",
    "design",
    "develop",
    "test_author",
    "test_and_review",
    "final_verify",
    "commit"
  ]
};

export class WorkflowPolicy {
  constructor(
    public readonly requestClass: RequestClass,
    public readonly requiredPhases: readonly WorkflowPhase[],
    public readonly skippedPhases: readonly WorkflowPhase[],
    public readonly skipRationale: Readonly<Record<string, string>>,
    public readonly phaseLabels: Readonly<Record<WorkflowPhase, string>> = PHASE_LABELS
  ) {}

  toDict(): Record<string, unknown> {
    return {
      request_class: this.requestClass,
      required_phases: [...this.requiredPhases],
      skipped_phases: [...this.skippedPhases],
      skip_rationale: { ...this.skipRationale }
    };
  }

  isPhaseRequired(phase: string): boolean {
    return this.requiredPhases.includes(phase as WorkflowPhase);
  }

  isPhaseSkipped(phase: string): boolean {
    return this.skippedPhases.includes(phase as WorkflowPhase);
  }

  skipReason(phase: string): string | null {
    return this.skipRationale[phase] ?? null;
  }

  dashboardSummary(): string {
    return [
      `Request class: ${this.requestClass}`,
      `Required phases (${this.requiredPhases.length}): ${
        this.requiredPhases.length ? this.requiredPhases.join(", ") : "none"
      }`,
      `Skipped phases (${this.skippedPhases.length}): ${
        this.skippedPhases.length ? this.skippedPhases.join(", ") : "none"
      }`
    ].join("\n");
  }
}

export function resolveWorkflowPolicy(requestClass: RequestClass): WorkflowPolicy {
  const skipMap = SKIP_POLICY[requestClass];
  if (!skipMap) {
    throw new Error(`Unknown request_class ${requestClass}.`);
  }

  const required: WorkflowPhase[] = [];
  const skipped: WorkflowPhase[] = [];
  const skipRationale: Record<string, string> = {};

  for (const phase of ALL_PHASES) {
    const reason = skipMap[phase] ?? "";
    if (reason) {
      skipped.push(phase);
      skipRationale[phase] = reason;
    } else {
      required.push(phase);
    }
  }

  return new WorkflowPolicy(requestClass, required, skipped, skipRationale);
}

export function defaultWorkflowPolicyState(requestClass: RequestClass): Record<string, unknown> {
  return resolveWorkflowPolicy(requestClass).toDict();
}
