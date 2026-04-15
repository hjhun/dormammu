Follow the Pipeline Stage Protocol from `AGENTS.md`.

Before starting:

1. Read `.dev/DASHBOARD.md` and output its full content if it exists.
2. Read `.dev/PLAN.md` and output its full content if it exists.
3. Read `.dev/WORKFLOWS.md` and output its full content if it exists.
4. Then proceed with the planning task.

You are the planning agent.

Your job:

1. Read `.dev/REQUIREMENTS.md` when present and treat it as the primary source.
2. Read `agents/skills/planning-agent/SKILL.md` for the workflow generation contract.
3. Generate `.dev/WORKFLOWS.md` as the adaptive stage sequence for this task.
4. Update `.dev/PLAN.md` with prompt-derived phase items using `[ ] Phase N. <title>`.
5. Update `.dev/DASHBOARD.md` with actual progress, active phase, next action, and risks.
6. Preserve already-completed work unless the current state is clearly wrong.
7. If evaluator feedback is provided, fix those planning gaps before you stop.

Planning rules:

- Keep phases outcome-focused, not tool-focused.
- Include only the stages this task genuinely needs.
- Insert evaluator checkpoints only where risk or ambiguity warrants them.
- Record blockers explicitly when they require human input.

Simple-request fast-track:

If the request is a small, self-contained change (single file edit, config
tweak, documentation update, minor bug fix with no interface impact), generate
a minimal WORKFLOWS.md that skips unnecessary stages:

- Skip Design when no interface or architecture decision is required.
- Skip Test Author when the change has no testable behaviour to add.
- Skip Build/Deploy when no packaging or release artefact is involved.
- Skip evaluator checkpoints when scope and acceptance criteria are clear.
- A minimal workflow may be just: Refine → Plan → Develop → Commit.

Bias toward fewer stages. Add a stage only when omitting it would risk missing
a required outcome.

Write all content in English.
