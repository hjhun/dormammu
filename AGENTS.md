# AGENTS.md

## Purpose

This repository is building `dormammu`, a Python-based coding agent loop
orchestrator with:

- standalone Python execution for core workflows
- CLI entrypoints for terminal-first usage
- resumable execution
- Markdown-based state management under `.dev/`
- supervisor-driven validation
- packaging and deployment support

The product surface is CLI-only. Web UI and browser-served control paths are
not part of the current product scope.

All agent work in this repository must help advance the goals defined in:

- `.dev/PROJECT.md`
- `.dev/ROADMAP.md`

## Source Of Truth

Use the following precedence order when deciding what to do next:

1. Direct user request
2. `.dev/PROJECT.md`
3. `.dev/ROADMAP.md`
4. Current `.dev/WORKFLOWS.md` stage sequence
5. Current `.dev` execution state files
6. Current repository contents

## Required Workflow

All substantial work should follow this base sequence. The planning agent
records the exact adaptive stage sequence for the current task in
`.dev/WORKFLOWS.md`. Stages not listed in `WORKFLOWS.md` for a given task are
skipped.

```
0. Refine
1. Plan          ← generates .dev/WORKFLOWS.md
2. Design
3. Develop       ↓ parallel tracks
4. Test Author   ↑ parallel tracks
5. [Evaluator check — if WORKFLOWS.md includes a mid-pipeline checkpoint]
6. Build and Deploy   (only if packaging or deployability is required)
7. Test and Review
8. Final Verification
9. Commit
10. Evaluate
```

Use the supervisor skill as the controller for every multi-step implementation
effort.

After design, the supervisor should route two implementation tracks as needed:

- the development skill for product code
- the test authoring skill for automated test code

Execute validation only after the active development slice is complete. Default
validation coverage is unit test plus integration test. Add system tests only
when the prompt or acceptance criteria explicitly require system-test-level
coverage; when that happens, run them in a real device or equivalent executable
environment when available.

## Role-Based Agent Pipeline

When `agents` is configured in `dormammu.json`, `DaemonRunner` routes each
goal through `PipelineRunner` instead of `LoopRunner`. The pipeline executes
these roles in order:

```
refiner → planner → evaluator(plan checkpoint) → developer → tester → reviewer → committer → evaluator(final, goals only)
```

The mandatory prelude is `refine -> plan`. The post-plan evaluator checkpoint
runs only for goals-scheduler prompts, not for interactive `run` or `run-once`
execution. The post-commit final evaluator is also goals-scheduler only.

### Roles

| Role | Slot | Verdict format | Re-entry trigger |
|------|------|----------------|-----------------|
| developer | `01-developer` | n/a | tester FAIL or reviewer NEEDS_WORK |
| tester | `04-tester` | `OVERALL: PASS` / `OVERALL: FAIL` | — |
| reviewer | `05-reviewer` | `VERDICT: APPROVED` / `VERDICT: NEEDS_WORK` | — |
| committer | `06-committer` | n/a | — |

**Tester** is a black-box one-shot agent. It designs and executes test cases
against the observable behaviour described in the goal, then writes its last
output line as `OVERALL: PASS` or `OVERALL: FAIL`. A `FAIL` verdict causes the
developer to re-enter with the tester report appended to the original prompt.

**Reviewer** performs a one-shot code review against the goal and the architect
design document (`.dev/02-architect/<date>_<stem>.md` if present). Its last
output line must be `VERDICT: APPROVED` or `VERDICT: NEEDS_WORK`.

**Re-entry limit**: `MAX_STAGE_ITERATIONS` is derived from the active
iteration-max budget. After that many rounds in either the tester or reviewer
loop, the pipeline advances unconditionally.

Each role writes its output to `.dev/<slot>-<role>/<date>_<stem>.md`.

### CLI resolution per role

For each role, the CLI is resolved in this order:

1. `agents.<role>.cli` in `dormammu.json`
2. `active_agent_cli` (global fallback)

### Pipeline Stage Protocol

At the start of every pipeline stage (tester, reviewer, committer, evaluator),
the agent must:

1. Read `.dev/DASHBOARD.md` and output its full content.
2. Read `.dev/PLAN.md` and output its full content.
3. Read `.dev/WORKFLOWS.md` and output its full content.
4. Then proceed with the stage task.

This makes the current workflow state visible in each stage's output and
stored document, so operators can observe progress through the pipeline without
inspecting state files separately.

### Goals automation

When `goals` is configured in `daemonize.json`, `GoalsScheduler` runs as a
separate daemon thread. It polls the goals directory at `interval_minutes`
intervals and, for each `.md` file found, writes a prompt into `prompt_path/`
for the next pipeline run. Files already processed (same `<date>_<stem>`) are
skipped.

The goals directory is also manageable through the Telegram bot via `/goals`
(list, add, delete).

## Skill Routing

Use the distributable workflow bundle under `agents/` to execute each phase:

- Refine and Plan workflow: `agents/workflows/refine-plan.md`
- Development and Test Authoring workflow: `agents/workflows/develop-test-authoring.md`
- Build Deploy and Test Review workflow: `agents/workflows/build-deploy-test-review.md`
- Cleanup and Commit workflow: `agents/workflows/cleanup-commit.md`

There is no separate planning-and-design workflow document. When requirements
are already clear, use `agents/workflows/refine-plan.md`, skip refining as
needed, and route into `agents/skills/designing-agent/SKILL.md` after planning.

Use the skills under `agents/skills/` when a workflow document routes to a
specific skill:

- Refine: `agents/skills/refining-agent/SKILL.md`
- Planning: `agents/skills/planning-agent/SKILL.md`
- Design: `agents/skills/designing-agent/SKILL.md`
- Development: `agents/skills/developing-agent/SKILL.md`
- Test Authoring: `agents/skills/test-authoring-agent/SKILL.md`
- Build and Deploy: `agents/skills/building-and-deploying/SKILL.md`
- Test and Review: `agents/skills/testing-and-reviewing/SKILL.md`
- Commit: `agents/skills/committing-agent/SKILL.md`
- Supervision: `agents/skills/supervising-agent/SKILL.md`
- Evaluation: `agents/skills/evaluating-agent/SKILL.md`

Stable runtime role contracts for one-shot pipeline stages live under
`agents/rules/` and are mirrored into the packaged asset bundle at install
time.

## Phase Expectations

### 0. Refine

Use `agents/skills/refining-agent/SKILL.md` when a new request arrives and
the scope or acceptance criteria need to be clarified before planning begins.

- Ask 3–6 targeted clarifying questions about scope, acceptance criteria,
  constraints, dependencies, and risks.
- Produce `.dev/REQUIREMENTS.md` with refined, unambiguous requirements.
- Hand off to the planning agent once requirements are confirmed.
- Skip this phase for simple, well-scoped changes where no clarification is
  needed.

### 1. Plan

- Read `.dev/REQUIREMENTS.md` as primary input; fall back to the raw goal.
- Generate `.dev/WORKFLOWS.md` — an adaptive, task-specific stage sequence
  with checkboxes that reflects exactly which stages this task needs and where
  evaluator checkpoints are placed.
- Update `.dev/DASHBOARD.md` with the actual in-progress status for the active scope.
- Update `.dev/PLAN.md` with prompt-derived phase checklist items in
  `[ ] Phase N. <title>` form.
- Update `.dev/TASKS.md` with development work items for the active scope.
- Record the active phase and next action.

### 2. Design

Focus on:

- module boundaries
- interfaces and contracts
- state files and schemas
- recovery and resumability
- validation strategy

### 3. Develop

Implement only the active scoped slice.

Rules:

- keep changes incremental and verifiable
- preserve unrelated user changes
- keep the repo resumable after each meaningful update
- coordinate with the test authoring skill so product code and test code stay aligned
- route back to design when implementation exposes a gap

### 4. Test Authoring

Use this phase after design to author test code for the active scope.

Rules:

- assign test code ownership to the dedicated test authoring skill
- write unit tests and integration tests by default
- add system tests only when the prompt or acceptance criteria explicitly call
  for system-test-level validation
- if system tests require a real device or equivalent environment and that
  environment is unavailable, record the gap explicitly instead of pretending
  coverage exists

### 5. Evaluator Check (mid-pipeline, optional)

Triggered when `.dev/WORKFLOWS.md` includes a mid-pipeline evaluator
checkpoint. The supervisor invokes `agents/skills/evaluating-agent/SKILL.md`
in mid-pipeline check mode.

- The evaluator reads `.dev/REQUIREMENTS.md` acceptance criteria and inspects
  stage outputs.
- It produces a checkpoint report in `.dev/07-evaluator/check_<stage>_<date>.md`
  with a `DECISION: PROCEED` or `DECISION: REWORK` verdict.
- `PROCEED` — the supervisor advances to the next stage.
- `REWORK` — the supervisor routes back to the stage indicated in the report.

Insert a mid-pipeline checkpoint when the task modifies a public interface,
spans more than two development phases, or has ambiguous acceptance criteria
that should be verified before committing.

### 6. Build And Deploy

Use this phase when the roadmap requires packaging, install flows, release
artifacts, or deployability checks.

### 7. Test And Review

Validation must include, when relevant:

- unit tests
- integration tests
- system tests when explicitly requested
- linters
- build checks
- smoke checks
- review of changed files for bugs, regressions, and missing edge cases

Run this phase after the developer agent has finished the active implementation
slice. Do not treat authored test code as executed validation.

### 8. Final Verification

After development and executed validation complete, the supervisor must run one
final operational verification pass before commit preparation.

Rules:

- verify the completed slice behaves as expected from the supervisor's point of
  view
- if this pass fails, identify the cause clearly
- when the cause requires code changes, route back to Develop and repeat the
  downstream validation flow

### 9. Commit

Use the committing skill only after the active scope has passed validation or
the user explicitly asks for commit preparation.

### 10. Evaluate

Use `agents/skills/evaluating-agent/SKILL.md` in final evaluation mode after
the commit stage completes.

- Assesses whether the completed implementation achieved the original goal.
- Reads `.dev/REQUIREMENTS.md`, `.dev/PLAN.md`, `.dev/DASHBOARD.md`, and the
  recent git log.
- Produces a full evaluation report in `.dev/07-evaluator/<date>_<stem>.md`
  with a `VERDICT: goal_achieved | partial | not_achieved` line.
- Optionally generates the next development goal when `next_goal_strategy` is
  configured.

## `.dev` State Management

When a workflow is active, keep these files aligned when they exist:

- `.dev/REQUIREMENTS.md`
- `.dev/WORKFLOWS.md`
- `.dev/DASHBOARD.md`
- `.dev/PLAN.md`
- `.dev/ROADMAP.md`
- `.dev/TASKS.md`
- `.dev/workflow_state.json`
- `.dev/session.json`
- `.dev/logs/`

Treat `.dev/workflow_state.json` as machine truth and Markdown files as
operator-facing state.

Use the Markdown files with these roles:

- `.dev/REQUIREMENTS.md`: refined, unambiguous requirements produced by the
  refining agent before planning begins
- `.dev/WORKFLOWS.md`: the adaptive stage sequence for the current task,
  generated by the planning agent; use `[ ]` for pending and `[O]` for
  completed steps
- `.dev/DASHBOARD.md`: show the real current progress, active phase, next action,
  risks, and notable in-progress context for the active scope
- `.dev/PLAN.md`: list the prompt-derived phase checklist for the active scope
  using `[ ] Phase N. <title>` for pending items and `[O] Phase N. <title>` for
  completed items
- `.dev/TASKS.md`: list the development work items derived from the current user
  prompt or scope

## Evaluator Checkpoint Protocol

When `.dev/WORKFLOWS.md` contains a mid-pipeline evaluator checkpoint, the
supervisor must:

1. Confirm the preceding stage is complete (evidence present in `.dev/`).
2. Invoke `agents/skills/evaluating-agent/SKILL.md` in mid-pipeline check mode.
3. Read the checkpoint report from `.dev/07-evaluator/check_<stage>_<date>.md`.
4. If `DECISION: PROCEED` — advance to the next stage.
5. If `DECISION: REWORK` — route back to the stage indicated in the report.

## Phase Gate Rules

Each phase transition requires evidence:

- `refine → plan`: `.dev/REQUIREMENTS.md` exists and is confirmed
- `plan → design`: `WORKFLOWS.md` and `PLAN.md` exist; next action is clear
- `design → develop`: interface or decision exists for the active scope
- `develop → test_author`: product code changes exist in intended files
- `test_author → test_review`: unit/integration test code exists and has been
  executed (authored tests alone do not satisfy this gate)
- `test_review → final_verify`: executed validation has clear results
- `final_verify → commit`: completed slice passed final operational verification
- `commit`: diff scope and validation both support version control

## Roadmap Alignment

Prefer roadmap execution in this order unless the user redirects the priority.
See `.dev/ROADMAP.md` for full phase descriptions.

1. Phase 1. Workflow Source Of Truth Recovery
2. Phase 2. `.dev` State Model And Session Simplification
3. Phase 3. Agent Runtime Unification And CLI Adapter Hardening
4. Phase 4. Supervisor, Pipeline, And Continuation Semantics
5. Phase 5. Operator Experience, Daemon, And Goals Consolidation
6. Phase 6. Documentation, Packaging, And Release Alignment
7. Phase 7. Hardening, CI, And Productization

## Resume Behavior

When resuming work after interruption:

1. Read current `.dev` state including `WORKFLOWS.md`.
2. Verify whether dashboard, tasks, WORKFLOWS.md, and machine state agree.
3. Identify the earliest uncertain stage in `WORKFLOWS.md`.
4. Resume from that stage rather than assuming later stages are valid.

## Default Agent Posture

When working in this repository, agents should:

- be explicit about the active stage
- use the mapped workflow skill for that stage
- refer to adjacent workflow skills when handoff or collaboration is required
- let the supervisor govern transitions
- keep progress visible in `.dev/`, especially in `WORKFLOWS.md`
- prefer deterministic checks before semantic judgment
- preserve resumability at every step
