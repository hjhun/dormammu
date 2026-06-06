Follow the Pipeline Stage Protocol from `AGENTS.md`.

Print `[[Evaluator]]` to standard output before any other action.

Before starting:

1. Read `.dev/DASHBOARD.md` and output its full content.
2. Read `.dev/PLAN.md` and output its full content.
3. Read `.dev/WORKFLOWS.md` and output its full content.
4. Then proceed with the evaluator checkpoint task.

You are running the mandatory post-plan evaluator checkpoint.

Evaluate only whether the plan is ready to advance. Do not review implementation code.

Questions to answer:

1. Do the requirements map cleanly into the planned stages?
2. Does `.dev/WORKFLOWS.md` include the right downstream phases?
3. Are blockers, risks, and validation expectations explicit enough?
4. Is the task ready to advance into design and development without inventing missing structure?

Output rules:

- Write a short checkpoint report in English.
- End the last non-empty line with exactly one of:
  - `DECISION: PROCEED`
  - `DECISION: REWORK`
- If rework is needed, describe what planning must fix before the pipeline can continue.
