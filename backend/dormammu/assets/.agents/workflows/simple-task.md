# Simple Task Workflow

Use this workflow for small, low-risk tasks where the full loop would add
more overhead than value.

## Examples

- typo fixes
- small documentation updates
- single-file configuration edits
- narrow test expectation updates

## Stage Order

Use one of these paths:

```text
developer -> reviewer -> supervisor
```

or, for documentation-only work:

```text
developer -> supervisor
```

## Rules

- Record why the task is simple in `DASHBOARD.md` or `SUPERVISOR_REPORT.md`.
- Do not skip tests blindly. State which gates apply and which do not.
- If scope expands, switch to `autonomous-development-loop.md`.

