---
name: evaluating-agent
description: Evaluates implementation against requirements at mid-pipeline checkpoints and at the end of a completed development cycle. Use for mid-pipeline checks (verify implementation matches refined requirements before committing) and for final evaluation (assess goal achievement and optionally generate the next goal).
---

# Evaluating Agent Skill

Use this skill in two contexts:

1. **Mid-pipeline check** — verifies that the current stage output matches the
   refined requirements before the pipeline advances. Triggered by the
   supervisor when the task complexity or risk warrants it (see
   `.dev/WORKFLOWS.md` for the planned checkpoints).
2. **Final evaluation** — assesses whether the completed implementation achieved
   the original goal and optionally generates the next development cycle. Runs
   after the committer stage, either automatically (goals-scheduler trigger) or
   when the `WORKFLOWS.md` final step is reached.

## Inputs

| Source | Content |
|--------|---------|
| Original goal text | Passed in the evaluator prompt |
| `.dev/REQUIREMENTS.md` | Refined requirements from refining-agent (if present) |
| `.dev/PLAN.md` | Completed task checklist |
| `.dev/WORKFLOWS.md` | Planned stage sequence and checkpoint context |
| `.dev/DASHBOARD.md` | Live progress and active phase |
| `.dev/supervisor_report.md` | Latest supervisor verdict and checks |
| `git log -3 --oneline --stat` | Recent commits and changed files |

## Modes

### Mid-Pipeline Check

Used when the supervisor or `WORKFLOWS.MD` triggers an evaluator checkpoint
before the commit stage. Focus narrowly on the current stage:

1. Read `.dev/REQUIREMENTS.md` acceptance criteria.
2. Inspect changed files and test results from the current stage.
3. Determine whether the stage output satisfies the criteria needed to advance.
4. Produce a short checkpoint report (see format below) and a `PROCEED` or
   `REWORK` decision.

Write checkpoint reports to `.dev/logs/check_<stage>_<date>.md` and final reports to `.dev/logs/<date>_evaluator_<stem>.md`.

#### Checkpoint Report Format

```markdown
# Evaluator Checkpoint — <stage name>

**Date**: <ISO-8601 timestamp>
**Stage**: <stage name>
**Decision**: PROCEED | REWORK

## Criteria Checked
- [x] <criterion> — <evidence>
- [ ] <criterion> — <gap or missing evidence>

## Findings
<Short summary of what was verified and what was not>

DECISION: PROCEED | REWORK
```

If the decision is `REWORK`, the supervisor must route back to the appropriate
earlier stage before the pipeline can advance.

### Final Evaluation

## Evaluation Criteria

Assess the implementation against these dimensions:

1. **Goal Achievement** — Do the completed tasks address the original goal?
2. **Acceptance Coverage** — Are all acceptance criteria from the goal met?
3. **Code and Test Quality** — Are tests present and passing? Are there regressions?
4. **Roadmap Alignment** — Is the active roadmap phase consistent with the work?
5. **Completeness** — Are there gaps that need a follow-up cycle?

## Verdict Values

Choose exactly one verdict based on the evidence:

| Verdict | Meaning |
|---------|---------|
| `goal_achieved` | All acceptance criteria met; implementation is complete |
| `partial` | Core work done but some items are missing or incomplete |
| `not_achieved` | Implementation did not meaningfully address the goal |

## Report Structure

Write the evaluation report to the path provided in the prompt.
Structure it as follows:

```markdown
# Evaluation Report — <stem>

**Date**: <ISO-8601 timestamp>
**Verdict**: <goal_achieved | partial | not_achieved>

## Goal Summary
<One-paragraph restatement of the original goal>

## What Was Achieved
<Bullet list of completed items confirmed by PLAN.md and git log>

## Gaps and Issues
<Bullet list of missing items or quality concerns; empty section if none>

## Roadmap Alignment
<Current phase vs. expected phase; note any drift>

## Assessment
<Two to four sentences summarising the overall outcome>

VERDICT: <goal_achieved | partial | not_achieved>
```

The `VERDICT:` line **must** be the last non-empty line of the report.

## Next Goal Generation

Behaviour depends on the `next_goal_strategy` setting passed in the prompt:

### strategy: `none`
Write only the evaluation report. Do not output a next-goal block.

### strategy: `suggest`
After the `VERDICT:` line, add a `## Suggestions for Next Cycle` section with
recommended next steps for human review. Do not output a next-goal block.

### strategy: `auto`
After the `VERDICT:` line, output the next goal wrapped in these **exact**
delimiters (no extra blank lines inside):

```
<!-- next_goal_start -->
<next goal content in Markdown>
<!-- next_goal_end -->
```

The next goal content must be self-contained Markdown that the goals scheduler
can process directly as a new goal file. It should:

- Build on what was achieved in this cycle.
- Address any gaps identified in the evaluation.
- Define the next logical feature or phase if the goal was fully achieved.
- Be written in the imperative form: "Implement X", "Add Y", "Fix Z".
- Include acceptance criteria so the next evaluator can assess it.

## Output Files

| File | Purpose |
|------|---------|
| `.dev/logs/check_<stage>_<date>.md` | Mid-pipeline checkpoint report |
| `.dev/logs/<date>_evaluator_<stem>.md` | Full final evaluation report |
| Original goal file (when strategy is `auto`) | Overwritten with the next goal |

## Rules

- Write all output in English regardless of the goal language.
- Do not invent passing evidence; base verdicts only on confirmed facts.
- In mid-pipeline mode, use `DECISION: PROCEED | REWORK` not `VERDICT:`.
- Keep the `VERDICT:` line as the last non-empty line before any next-goal block.
- When `next_goal_strategy` is `auto` and the goal was fully achieved with no
  obvious continuation, it is acceptable to output an empty next-goal block —
  the evaluator stage will detect this and leave the goal file unchanged.
- Never modify source code or test files; this skill is read-only except for
  writing the evaluation report and the goal file.

## Done Criteria

**Mid-pipeline check** — complete when:

1. The checkpoint report is written to `.dev/logs/check_<stage>_<date>.md`.
2. The `DECISION:` line is present as the last non-empty line.
3. The supervisor has received a clear `PROCEED` or `REWORK` signal.

**Final evaluation** — complete when:

1. The evaluation report is written to `.dev/logs/<date>_evaluator_<stem>.md`.
2. The `VERDICT:` line is present as the last non-empty line of the report.
3. When `next_goal_strategy` is `auto`, the next-goal block is present and
   properly delimited (or intentionally empty if no continuation is needed).
