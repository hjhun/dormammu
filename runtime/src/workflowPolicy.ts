export type RequestClass =
  | "direct_response"
  | "planning_only"
  | "light_edit"
  | "full_workflow";

export type RequestClassDecisionSource = "workflow_state" | "classifier";

export type RequestClassDecisionInput = {
  promptText: string;
  workflowState?: Readonly<Record<string, unknown>> | null;
};

export type RequestClassDecision = {
  requestClass: RequestClass;
  confidence: number | null;
  source: RequestClassDecisionSource;
  reason: string;
};

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

const REQUEST_CLASS_DIRECTIVE_RE =
  /^\s*DORMAMMU_REQUEST_CLASS\s*:\s*(direct_response|planning_only|light_edit|full_workflow)\s*$/gim;

const DIRECT_RESPONSE_SIGNALS = [
  "analyze",
  "analyse",
  "explain",
  "summarize",
  "summarise",
  "describe",
  "review",
  "compare",
  "audit",
  "report",
  "list",
  "show",
  "what is",
  "what are",
  "how does",
  "how do",
  "why does",
  "why do",
  "tell me",
  "find out",
  "check",
  "inspect",
  "diagnose",
  "document",
  "분석",
  "설명",
  "요약",
  "검토",
  "확인",
  "파악",
  "원인",
  "왜",
  "어떻게",
  "알려",
  "찾아"
] as const;

const LIGHT_EDIT_SIGNALS = [
  "fix",
  "rename",
  "update",
  "correct",
  "tweak",
  "adjust",
  "bump",
  "patch",
  "comment",
  "uncomment",
  "format",
  "lint",
  "typo",
  "spelling",
  "docstring",
  "changelog",
  "readme",
  "config",
  "configuration",
  "setting",
  "version",
  "dependency",
  "dependencies",
  "upgrade",
  "downgrade",
  "수정",
  "고쳐",
  "개선",
  "변경",
  "설정"
] as const;

const FULL_WORKFLOW_SIGNALS = [
  "implement",
  "add",
  "build",
  "create",
  "introduce",
  "design",
  "architect",
  "refactor",
  "restructure",
  "migrate",
  "port",
  "rewrite",
  "overhaul",
  "replace",
  "integrate",
  "develop",
  "feature",
  "module",
  "service",
  "api",
  "interface",
  "schema",
  "pipeline",
  "system",
  "end-to-end",
  "end to end",
  "multi-file",
  "multi file",
  "구현",
  "추가",
  "개발",
  "설계",
  "통합",
  "리팩터",
  "리팩토링"
] as const;

const PLANNING_ONLY_SUBJECTS = [
  "architecture",
  "architectural",
  "structure",
  "structural",
  "system design",
  "module boundary",
  "module boundaries",
  "workflow design",
  "technical direction",
  "design approach",
  "runtime structure",
  "execution mode",
  "run mode",
  "daemon mode",
  "pipeline shape",
  "workflow shape",
  "structural concern"
] as const;

const PLANNING_ONLY_INTENT = [
  "consider",
  "think through",
  "discuss",
  "evaluate",
  "review",
  "analyze",
  "analyse",
  "reason about",
  "think deeply",
  "deep thinking",
  "deliberate",
  "weigh options",
  "propose direction"
] as const;

const IMPLEMENTATION_INTENT = [
  "implement",
  "add",
  "build",
  "create",
  "introduce",
  "develop",
  "fix",
  "update",
  "refactor",
  "migrate",
  "rewrite"
] as const;

const INTERFACE_RISK_MARKERS = [
  "api",
  "interface",
  "schema",
  "contract",
  "protocol",
  "breaking change",
  "backwards compatible",
  "backward compatible",
  "public api",
  "public interface"
] as const;

const TESTING_MARKERS = [
  "test",
  "tests",
  "unit test",
  "integration test",
  "regression",
  "coverage",
  "test suite"
] as const;

export function resolveRequestClassDecision(
  input: RequestClassDecisionInput
): RequestClassDecision {
  const intake = asRecord(input.workflowState?.intake);
  if (intake !== null) {
    const requestClass = parseRequestClassValue(intake.request_class);
    const confidence = finiteNumberOrNull(intake.confidence);
    if (requestClass !== null) {
      if (requestClass === "direct_response" && confidence !== null && confidence < 0.5) {
        return {
          requestClass: "full_workflow",
          confidence,
          source: "workflow_state",
          reason: "workflow_state_direct_response_low_confidence_promoted"
        };
      }
      return {
        requestClass,
        confidence,
        source: "workflow_state",
        reason: "workflow_state_intake_request_class"
      };
    }
  }

  const classification = classifyRequest(input.promptText);
  if (
    classification.requestClass === "direct_response" &&
    classification.confidence < 0.5
  ) {
    return {
      requestClass: "full_workflow",
      confidence: classification.confidence,
      source: "classifier",
      reason: "classifier_direct_response_low_confidence_promoted"
    };
  }
  return {
    requestClass: classification.requestClass,
    confidence: classification.confidence,
    source: "classifier",
    reason: "classifier_request_class"
  };
}

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

function classifyRequest(promptText: string): {
  requestClass: RequestClass;
  confidence: number;
} {
  REQUEST_CLASS_DIRECTIVE_RE.lastIndex = 0;
  const directive = REQUEST_CLASS_DIRECTIVE_RE.exec(promptText ?? "");
  if (directive !== null) {
    return {
      requestClass: directive[1].toLowerCase() as RequestClass,
      confidence: 1.0
    };
  }

  if (!promptText || promptText.trim().length === 0) {
    return {
      requestClass: "direct_response",
      confidence: 0.5
    };
  }

  const normalized = tokens(promptText);
  const directScore = countMatches(normalized, DIRECT_RESPONSE_SIGNALS);
  let planningScore =
    countMatches(normalized, PLANNING_ONLY_SUBJECTS) +
    countMatches(normalized, PLANNING_ONLY_INTENT);
  const lightScore = countMatches(normalized, LIGHT_EDIT_SIGNALS);
  let fullScore = countMatches(normalized, FULL_WORKFLOW_SIGNALS);
  const implementationIntent =
    countMatches(normalized, IMPLEMENTATION_INTENT) > 0;
  const hasInterfaceRisk =
    countMatches(normalized, INTERFACE_RISK_MARKERS) > 0;
  const requiresTestStrategy = countMatches(normalized, TESTING_MARKERS) > 0;
  const estimatedFileCount = estimateFileCount(promptText, normalized);

  const planningOnly =
    planningScore >= 2 &&
    !implementationIntent &&
    estimatedFileCount < 3 &&
    !requiresTestStrategy;

  if (hasInterfaceRisk || estimatedFileCount >= 3) {
    if (planningOnly) {
      planningScore += 2;
    } else {
      fullScore += 2;
    }
  }

  if (requiresTestStrategy) {
    fullScore += 1;
  }

  const total = directScore + planningScore + lightScore + fullScore || 1;

  if (planningOnly && planningScore >= fullScore) {
    return {
      requestClass: "planning_only",
      confidence: roundConfidence(planningScore / total)
    };
  }
  if (fullScore > lightScore && fullScore > directScore) {
    return {
      requestClass: "full_workflow",
      confidence: roundConfidence(fullScore / total)
    };
  }
  if (lightScore > directScore) {
    return {
      requestClass: "light_edit",
      confidence: roundConfidence(lightScore / total)
    };
  }
  if (directScore > 0) {
    return {
      requestClass: "direct_response",
      confidence: roundConfidence(directScore / total)
    };
  }
  return {
    requestClass: "direct_response",
    confidence: 0.4
  };
}

function tokens(text: string): string {
  return text.toLowerCase().split(/\s+/u).filter(Boolean).join(" ");
}

function countMatches(normalized: string, signals: readonly string[]): number {
  return signals.reduce(
    (count, signal) => count + (normalized.includes(signal) ? 1 : 0),
    0
  );
}

function estimateFileCount(text: string, normalized: string): number {
  const explicitFiles = text.match(/\b\w+\.\w{1,5}\b/gu)?.length ?? 0;
  const broadTerms = [
    "across",
    "multiple",
    "several",
    "all files",
    "each file",
    "everywhere"
  ];
  return explicitFiles + countMatches(normalized, broadTerms);
}

function roundConfidence(value: number): number {
  return Math.round(value * 1000) / 1000;
}

function asRecord(value: unknown): Readonly<Record<string, unknown>> | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }
  return value as Readonly<Record<string, unknown>>;
}

function finiteNumberOrNull(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function parseRequestClassValue(value: unknown): RequestClass | null {
  if (
    value === "direct_response" ||
    value === "planning_only" ||
    value === "light_edit" ||
    value === "full_workflow"
  ) {
    return value;
  }
  return null;
}
