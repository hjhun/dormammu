# Role Taxonomy

`dormammu` has one role namespace for configuration and profiles, but not every
role is part of the interactive runtime pipeline. This table is the canonical
operator-facing contract for `agents.<role>` in `dormammu.json`.

| Role | Scope | Purpose |
|------|-------|---------|
| `refiner` | runtime pipeline | Turns the raw prompt into `.dev/REQUIREMENTS.md` before planning. |
| `planner` | runtime pipeline and goals prelude | Writes runtime `.dev/WORKFLOWS.md`, `.dev/PLAN.md`, and `.dev/TASKS.md`; goals automation may also use it to strengthen a queued prompt. |
| `developer` | runtime pipeline | Implements the active product-code slice. |
| `tester` | runtime pipeline | Performs black-box validation and emits `OVERALL: PASS` or `OVERALL: FAIL`. |
| `reviewer` | runtime pipeline | Reviews the implementation and emits `VERDICT: APPROVED` or `VERDICT: NEEDS_WORK`. |
| `committer` | runtime pipeline | Prepares validated changes for version-control handoff. |
| `analyzer` | goals and autonomous only | Reads scheduled goals or autonomous repository context before a runtime prompt is queued. |
| `designer` | goals prelude only | Adds optional technical design context to a scheduled goal prompt. Runtime review reads `.dev/logs/<date>_designer_<stem>.md` when present, but the designer is not an interactive pipeline stage. |
| `evaluator` | goals checkpoint only | Runs goals-scheduler plan checkpoints and final goal evaluation. Interactive `run` and `run-once` skip it. |

`architect` is not a compatibility alias. The current role name is `designer`,
and legacy `architect` configuration is rejected as an unknown role.

## Goals Connection

`GoalsScheduler` is a prompt producer, not a separate product workflow. It
promotes files from `goals.path` into the daemon prompt queue. Before queueing,
it may run the goals prelude:

```text
analyzer -> planner -> designer
```

The resulting prompt then enters the normal runtime contract:

```text
refiner -> planner -> developer -> tester -> reviewer -> committer
```

For scheduled goals only, `evaluator` may run after runtime planning and after
commit to decide whether the generated plan or completed goal needs rework.
