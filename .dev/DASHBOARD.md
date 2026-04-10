# DASHBOARD

## Actual Progress

- Goal: Install `dormammu` locally, validate it from `~/samba/test`, and run
  Rust Tetris completion loops with `codex`, `claude`, and `gemini` for at
  least three attempts each.
- Prompt-driven scope: Repair supervised loop continuation behavior so retries
  do not over-constrain valid external-path tasks or recursively bloat retry
  prompts.
- Active roadmap focus:
- Phase 3. Agent CLI Adapter and Single-Run Execution
- Phase 4. Supervisor Validation, Continuation Loop, and Resume
- Phase 6. Installer, Commands, and Environment Diagnostics
- Phase 7. Hardening, Multi-Session, and Productization
- Current workflow phase: test_and_review
- Last completed workflow phase: test_authoring
- Supervisor verdict: `approved`
- Escalation status: `approved`
- Resume point: The supervised loop continuation repair is implemented and
  validated. Resume from review if additional external-loop reruns are needed.

## In Progress

- Continuation prompts now keep the original user task as the retry baseline
  instead of recursively embedding the previous retry prompt.
- Retry guidance now defaults to repository-local work while still allowing
  explicitly required external system paths such as `/proc`.
- Focused regression coverage for continuation generation and loop retries is in
  place alongside the existing loop, CLI, and install-script tests.
- External rerun evidence from
  `~/samba/test/proc-mem-gemini-loop-v3` shows the repaired continuation prompt
  is emitted during retry attempts and preserves the original task prompt while
  allowing `/proc`-style external-path work.

## Progress Notes

- Focused validation passed with
  `python3 -m unittest tests.test_continuation tests.test_loop_runner`.
- Guardrail regression validation also passed with
  `python3 -m unittest tests.test_supervisor tests.test_agent_cli_adapter`.
- Repository-external verification on
  `~/samba/test/proc-mem-gemini-loop-v3` reached three supervised attempts and
  produced working Rust code. Manual checks passed with `cargo test` and
  `cargo run -- $$`, and `DORMAMMU.log` captured all three attempts plus the
  retry continuation prompt text.
- The repair intentionally leaves existing `DORMAMMU.log`, installer, and CLI
  preset changes intact while narrowing the continuation-specific fix.

## Risks And Watchpoints

- Prompt wording changes can improve retry behavior, but external CLI variance
  may still limit convergence on long real-world tasks.
- The latest Gemini rerun still failed supervisor approval because the agent did
  not finish `README.md`, `NOTES.md`, or `.attempt3-complete` before shell/tool
  instability and manual interruption ended the run.
- The repository currently tracks this repair slice in `.dev/PLAN.md`, not in a
  separate `.dev/TASKS.md`; state files should continue to reflect that source
  of truth.
