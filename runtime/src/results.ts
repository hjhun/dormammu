export const RESULT_STATUSES = [
  "completed",
  "failed",
  "blocked",
  "skipped",
  "manual_review_needed"
] as const;

export const RESULT_VERDICTS = [
  "done",
  "proceed",
  "rework",
  "pass",
  "fail",
  "approved",
  "needs_work",
  "committed",
  "goal_achieved",
  "partial",
  "not_achieved",
  "unknown",
  "promise_complete",
  "rework_required",
  "blocked",
  "manual_review_needed"
] as const;

export type ResultStatus = (typeof RESULT_STATUSES)[number];
export type ResultVerdict = (typeof RESULT_VERDICTS)[number];

const STATUS_SET = new Set<string>(RESULT_STATUSES);
const VERDICT_SET = new Set<string>(RESULT_VERDICTS);

export type RetryMetadata = {
  attempt?: number | null;
  nextAttempt?: number | null;
  retriesUsed?: number | null;
  maxRetries?: number | null;
  maxIterations?: number | null;
};

export type TimingMetadata = {
  startedAt?: string | null;
  completedAt?: string | null;
  durationSeconds?: number | null;
};

export type StageResult = {
  role: string;
  verdict?: ResultVerdict | string | null;
  output?: string;
  status?: ResultStatus | string;
  stageName?: string | null;
  summary?: string | null;
  reportPath?: string | null;
  artifacts?: readonly unknown[];
  retry?: RetryMetadata | null;
  timing?: TimingMetadata | null;
  metadata?: Readonly<Record<string, unknown>>;
};

export type RunResult = {
  status: ResultStatus | string;
  attemptsCompleted?: number;
  attempts_completed?: number;
  retriesUsed?: number;
  retries_used?: number;
  maxRetries?: number;
  max_retries?: number;
  maxIterations?: number;
  max_iterations?: number;
  latestRunId?: string | null;
  latest_run_id?: string | null;
  supervisorVerdict?: ResultVerdict | string | null;
  supervisor_verdict?: ResultVerdict | string | null;
  reportPath?: string | null;
  report_path?: string | null;
  continuationPromptPath?: string | null;
  continuation_prompt_path?: string | null;
  summary?: string | null;
  output?: string | null;
  stageResults?: readonly StageResult[];
  stage_results?: readonly StageResult[];
  artifacts?: readonly unknown[];
  retry?: RetryMetadata | null;
  timing?: TimingMetadata | null;
  metadata?: Readonly<Record<string, unknown>>;
};

export function normalizeResultStatus(value: ResultStatus | string | null | undefined): ResultStatus | null {
  if (value == null) {
    return null;
  }
  const normalized = String(value).trim().toLowerCase();
  if (!STATUS_SET.has(normalized)) {
    throw new Error(`Invalid result status: ${value}`);
  }
  return normalized as ResultStatus;
}

export function normalizeResultVerdict(value: ResultVerdict | string | null | undefined): ResultVerdict | null {
  if (value == null) {
    return null;
  }
  const normalized = String(value).trim().toLowerCase().replaceAll(" ", "_");
  if (!VERDICT_SET.has(normalized)) {
    throw new Error(`Invalid result verdict: ${value}`);
  }
  return normalized as ResultVerdict;
}

const TESTER_VERDICT_RE = /OVERALL\s*:\s*(PASS|FAIL|MANUAL[_\s]REVIEW[_\s]NEEDED)/gi;
const REVIEWER_VERDICT_RE = /VERDICT\s*:\s*(APPROVED|NEEDS[_\s]WORK)/gi;
const CHECKPOINT_PROCEED_RE = /DECISION\s*:\s*PROCEED/i;
const EVALUATOR_VERDICT_RE = /VERDICT\s*:\s*(goal_achieved|partial|not_achieved)/gi;

const FAILURE_STATUSES = new Set<ResultStatus>(["failed", "blocked", "manual_review_needed"]);
const FAILURE_VERDICTS = new Set<ResultVerdict>([
  "fail",
  "needs_work",
  "rework",
  "blocked",
  "manual_review_needed"
]);
const RETRY_VERDICTS = new Set<ResultVerdict>([
  "fail",
  "needs_work",
  "rework",
  "rework_required"
]);

function parseLastNormalizedVerdict(output: string, pattern: RegExp): ResultVerdict | null {
  const matches = [...output.matchAll(pattern)];
  if (!matches.length) {
    return null;
  }
  const rawVerdict = matches[matches.length - 1][1] ?? "";
  return normalizeResultVerdict(rawVerdict);
}

export function parseTesterVerdict(output: string): ResultVerdict | null {
  return parseLastNormalizedVerdict(output, TESTER_VERDICT_RE);
}

export function parseReviewerVerdict(output: string): ResultVerdict | null {
  return parseLastNormalizedVerdict(output, REVIEWER_VERDICT_RE);
}

export function parsePlanEvaluatorVerdict(output: string): ResultVerdict {
  return CHECKPOINT_PROCEED_RE.test(output) ? "proceed" : "rework";
}

export function parseFinalEvaluatorVerdict(output: string): ResultVerdict {
  return parseLastNormalizedVerdict(output, EVALUATOR_VERDICT_RE) ?? "unknown";
}

export function stageResultKey(stage: StageResult): string {
  return stage.stageName ? stage.stageName : stage.role;
}

function normalizedStageStatus(stage: StageResult): ResultStatus {
  return normalizeResultStatus(stage.status ?? "completed") ?? "completed";
}

function normalizedStageVerdict(stage: StageResult): ResultVerdict | null {
  return normalizeResultVerdict(stage.verdict ?? null);
}

export function effectiveStageVerdict(
  stage: StageResult,
  defaultVerdict: ResultVerdict | string | null = null
): ResultVerdict | null {
  const verdict = normalizedStageVerdict(stage);
  if (verdict !== null) {
    return verdict;
  }
  const status = normalizedStageStatus(stage);
  if (status === "blocked") {
    return "blocked";
  }
  if (status === "manual_review_needed") {
    return "manual_review_needed";
  }
  if (status === "failed") {
    return "unknown";
  }
  return normalizeResultVerdict(defaultVerdict);
}

export function stageResultIsFailure(stage: StageResult): boolean {
  const status = normalizedStageStatus(stage);
  if (FAILURE_STATUSES.has(status)) {
    return true;
  }
  const verdict = normalizedStageVerdict(stage);
  return verdict !== null && FAILURE_VERDICTS.has(verdict);
}

export function stageResultRequestsRetry(stage: StageResult): boolean {
  const verdict = normalizedStageVerdict(stage);
  return verdict !== null && RETRY_VERDICTS.has(verdict);
}

export function latestStageResults(stageResults: readonly StageResult[]): StageResult[] {
  const latestReversed: StageResult[] = [];
  const seen = new Set<string>();
  for (const stage of [...stageResults].reverse()) {
    const key = stageResultKey(stage);
    if (seen.has(key)) {
      continue;
    }
    latestReversed.push(stage);
    seen.add(key);
  }
  return latestReversed.reverse();
}

function artifactToPayload(artifact: unknown): unknown {
  if (
    typeof artifact === "object" &&
    artifact !== null &&
    "toDict" in artifact &&
    typeof (artifact as { toDict: unknown }).toDict === "function"
  ) {
    return (artifact as { toDict: () => unknown }).toDict();
  }
  return artifact;
}

function retryToDict(retry: RetryMetadata | null | undefined): Record<string, number | null> | null {
  if (retry == null) {
    return null;
  }
  return {
    attempt: retry.attempt ?? null,
    next_attempt: retry.nextAttempt ?? null,
    retries_used: retry.retriesUsed ?? null,
    max_retries: retry.maxRetries ?? null,
    max_iterations: retry.maxIterations ?? null
  };
}

function timingToDict(timing: TimingMetadata | null | undefined): Record<string, string | number | null> | null {
  if (timing == null) {
    return null;
  }
  return {
    started_at: timing.startedAt ?? null,
    completed_at: timing.completedAt ?? null,
    duration_seconds: timing.durationSeconds ?? null
  };
}

export function stageResultToDict(
  stage: StageResult,
  options: { includeOutput?: boolean } = {}
): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    role: stage.role,
    stage_name: stage.stageName ?? null,
    status: normalizeResultStatus(stage.status ?? "completed"),
    verdict: normalizeResultVerdict(stage.verdict ?? null),
    summary: stage.summary ?? null,
    report_path: stage.reportPath ?? null,
    artifacts: [...(stage.artifacts ?? [])].map(artifactToPayload),
    retry: retryToDict(stage.retry),
    timing: timingToDict(stage.timing),
    metadata: { ...(stage.metadata ?? {}) }
  };
  if (options.includeOutput === true) {
    payload.output = stage.output ?? "";
  }
  return payload;
}

function coalesceNumber(...values: readonly (number | undefined)[]): number {
  for (const value of values) {
    if (typeof value === "number") {
      return value;
    }
  }
  return 0;
}

function coalesceNullableString(...values: readonly (string | null | undefined)[]): string | null {
  for (const value of values) {
    if (value !== undefined) {
      return value;
    }
  }
  return null;
}

function runRetryToDict(result: RunResult): Record<string, number | null> | null {
  const explicitRetry = retryToDict(result.retry);
  if (explicitRetry !== null) {
    return explicitRetry;
  }
  return {
    attempt: coalesceNumber(result.attemptsCompleted, result.attempts_completed),
    next_attempt: null,
    retries_used: coalesceNumber(result.retriesUsed, result.retries_used),
    max_retries: coalesceNumber(result.maxRetries, result.max_retries),
    max_iterations: coalesceNumber(result.maxIterations, result.max_iterations)
  };
}

export function runResultToDict(
  result: RunResult,
  options: { includeOutput?: boolean } = {}
): Record<string, unknown> {
  const stageResults = result.stageResults ?? result.stage_results ?? [];
  const payload: Record<string, unknown> = {
    status: normalizeResultStatus(result.status),
    attempts_completed: coalesceNumber(result.attemptsCompleted, result.attempts_completed),
    retries_used: coalesceNumber(result.retriesUsed, result.retries_used),
    max_retries: coalesceNumber(result.maxRetries, result.max_retries),
    max_iterations: coalesceNumber(result.maxIterations, result.max_iterations),
    latest_run_id: coalesceNullableString(result.latestRunId, result.latest_run_id),
    supervisor_verdict: normalizeResultVerdict(
      result.supervisorVerdict ?? result.supervisor_verdict ?? null
    ),
    report_path: coalesceNullableString(result.reportPath, result.report_path),
    continuation_prompt_path: coalesceNullableString(
      result.continuationPromptPath,
      result.continuation_prompt_path
    ),
    summary: result.summary ?? null,
    stage_results: stageResults.map((stage) => stageResultToDict(stage, options)),
    artifacts: [...(result.artifacts ?? [])].map(artifactToPayload),
    retry: runRetryToDict(result),
    timing: timingToDict(result.timing),
    metadata: { ...(result.metadata ?? {}) }
  };
  if (options.includeOutput === true) {
    payload.output = result.output ?? null;
  }
  return payload;
}

export function stageResultsHaveCleanTerminalEvidence(stageResults: readonly StageResult[]): boolean {
  const latest = latestStageResults(stageResults);
  if (!latest.length) {
    return false;
  }
  return latest.every(
    (stage) => normalizedStageStatus(stage) === "completed" && !stageResultIsFailure(stage)
  );
}

export function aggregateRunVerdict(
  stageResults: readonly StageResult[],
  defaultVerdict: ResultVerdict | string | null = null
): ResultVerdict | null {
  const latest = latestStageResults(stageResults);
  const normalizedDefault = normalizeResultVerdict(defaultVerdict);
  if (!latest.length) {
    return normalizedDefault;
  }

  if (latest.some((stage) => normalizedStageStatus(stage) === "blocked")) {
    return "blocked";
  }
  if (latest.some((stage) => normalizedStageStatus(stage) === "manual_review_needed")) {
    return "manual_review_needed";
  }

  const failedStages = latest.filter((stage) => normalizedStageStatus(stage) === "failed");
  if (failedStages.length) {
    return effectiveStageVerdict(failedStages[failedStages.length - 1], "unknown");
  }

  const failingVerdicts = latest.filter((stage) => {
    const verdict = normalizedStageVerdict(stage);
    return verdict !== null && FAILURE_VERDICTS.has(verdict);
  });
  if (failingVerdicts.length) {
    return effectiveStageVerdict(failingVerdicts[failingVerdicts.length - 1], normalizedDefault);
  }

  for (const stage of [...latest].reverse()) {
    const verdict = effectiveStageVerdict(stage);
    if (verdict !== null) {
      return verdict;
    }
  }
  return normalizedDefault;
}

export function aggregateRunStatus(
  stageResults: readonly StageResult[],
  defaultStatus: ResultStatus | string = "completed"
): ResultStatus {
  const normalizedDefault = normalizeResultStatus(defaultStatus) ?? "completed";
  const latest = latestStageResults(stageResults);
  if (latest.some((stage) => normalizedStageStatus(stage) === "blocked")) {
    return "blocked";
  }
  if (latest.some((stage) => normalizedStageStatus(stage) === "manual_review_needed")) {
    return "manual_review_needed";
  }
  if (latest.some((stage) => normalizedStageStatus(stage) === "failed")) {
    return "failed";
  }
  return normalizedDefault;
}
