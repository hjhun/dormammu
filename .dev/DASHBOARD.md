# DASHBOARD

## Actual Progress

- Goal: Add user-facing max-iteration loop control, default it to 50 total
  attempts, and stop Dormammu as soon as development is approved.
- Prompt-driven scope: Add `--max-iterations` for run and resume, keep loop
  completion eager, and validate the behavior with both automated and local
  smoke tests.
- Active roadmap focus:
- Phase 3. Agent CLI Adapter and Single-Run Execution
- Phase 4. Supervisor Validation, Continuation Loop, and Resume
- Phase 6. Installer, Commands, and Environment Diagnostics
- Current workflow phase: test_and_review
- Last completed workflow phase: test_and_review
- Supervisor verdict: `approved`
- Escalation status: `approved`
- Resume point: The max-iteration loop-control slice is implemented and
  validated. Resume from commit preparation or from follow-up loop UX work if
  we want richer operator controls.

## In Progress

- `run` and `resume` now accept a user-facing `--max-iterations` budget.
- When users do not provide a loop budget, Dormammu now defaults to 50 total
  attempts instead of a single attempt.
- Resume now refuses to spend iterations beyond the total configured budget,
  while successful supervisor approval still exits immediately.

## Progress Notes

- Loop result payloads and progress logs now surface both retries and total
  iteration limits so operators can see the active budget directly.
- Focused validation passed for `tests.test_cli`, `tests.test_loop_runner`,
  `tests.test_config`, and `tests.test_install_script`.
- Local smoke validation passed in
  `~/samba/test/dormammu-max-iterations-smoke` for both default-50 eager exit
  and `run`/`resume` with explicit iteration budgets.

## Risks And Watchpoints

- `--max-iterations` and `--max-retries` overlap semantically, so the CLI now
  rejects using both at the same time.
- Older saved loop state still serializes retry budgets; resume logic must keep
  honoring those states while applying any new total-iteration overrides.
