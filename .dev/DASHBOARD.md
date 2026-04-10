# DASHBOARD

## Actual Progress

- Goal: Make external agent CLI execution honor the resolved `HOME` directory
  so tools like `cline` can discover `~/`-anchored configuration and
  credentials when run through Dormammu.
- Prompt-driven scope: Align runtime config, child CLI launches, and operator
  diagnostics around one explicit `HOME` contract instead of relying on
  implicit subprocess inheritance alone.
- Active roadmap focus:
- Phase 3. Agent CLI Adapter and Single-Run Execution
- Phase 6. Installer, Commands, and Environment Diagnostics
- Current workflow phase: test_and_review
- Last completed workflow phase: test_and_review
- Supervisor verdict: `approved`
- Escalation status: `approved`
- Resume point: The `HOME`-anchored execution slice is implemented and
  validated. Resume only if we want richer environment diagnostics or
  supporting documentation for the new doctor output.

## In Progress

- The config model now resolves a canonical `home_dir` and shares it with
  runtime consumers.
- The CLI adapter now passes the resolved `HOME` explicitly to capability
  inspection and real child CLI runs.
- The doctor report now shows the effective home directory and validates that
  it exists as a usable directory before an agent run starts.

## Progress Notes

- The previous `cline` API-key report suggests that the current execution
  context is too implicit for troubleshooting, even though subprocesses inherit
  the parent environment by default.
- This slice keeps the existing Cline preset behavior intact and focuses only
  on making `HOME`-based execution deterministic and visible.
- Focused config, doctor, CLI, and adapter tests now cover the new execution
  contract instead of leaving it implicit.

## Risks And Watchpoints

- Passing an explicit `HOME` to all child CLIs affects every supported adapter,
  so validation needs to cover both normal runs and `doctor`.
- If a local `cline` command depends on a shell wrapper or login-shell setup
  that mutates credentials outside the home-directory contract, this fix may
  need a follow-up diagnostic path.
