Use this workflow after the mandatory `refine -> plan` prelude has already
completed and downstream execution is continuing with a single coding agent.

## Purpose

This workflow keeps downstream execution under the supervising-agent contract
instead of dropping straight back to the raw user prompt.

## Entry Conditions

- `.dev/REQUIREMENTS.md` exists when refinement was required
- `.dev/WORKFLOWS.md`, `.dev/PLAN.md`, and `.dev/DASHBOARD.md` were produced by
  planning
- downstream work still needs to continue through one coding-agent runtime path

## Required Behaviour

1. Read the current `.dev` state before acting:
   - `.dev/DASHBOARD.md`
   - `.dev/PLAN.md`
   - `.dev/WORKFLOWS.md`
   - `.dev/TASKS.md` when present
   - `.dev/workflow_state.json`
2. Use `skills/supervising-agent/SKILL.md` as the top-level controller for the
   remaining work.
3. Resume from the earliest unfinished downstream phase after planning.
4. Route into the next workflow skill implied by `.dev/WORKFLOWS.md` instead of
   restarting from the raw goal.
5. Keep `.dev/workflow_state.json` as machine truth and keep the Markdown state
   synchronized with actual progress.
6. Re-enter `workflows/refine-plan.md` only when state inconsistency or missing
   requirements make the saved plan unsafe to continue.

## Expected Outcome

The first downstream execution after planning behaves like a supervisor-led
handoff: the agent inspects state, chooses the next phase, performs the needed
repository work, and leaves resumable `.dev` evidence behind.
