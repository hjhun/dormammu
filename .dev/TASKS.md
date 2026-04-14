# TASKS

## Prompt-Derived Implementation Plan

- [O] Phase 1. Audit the current top-level parser and handler entrypoints to
  identify the smallest safe insertion point for default interactive mode
- [O] Phase 2. Produce an architecture decision for minimal shell versus richer
  TUI, including dependency and portability tradeoffs
- [O] Phase 3. Define the interactive command grammar for free-text prompts,
  `/help`, `/config`, `/run`, `/resume`, `/sessions`, `/exit`, and interrupts
- [O] Phase 4. Define config data ownership between existing `dormammu.json`
  keys and any new interactive-shell settings
- [O] Phase 5. Define how the interactive shell controls daemon queue input and
  daemon progress output without turning `daemonize` itself into a REPL
- [O] Phase 6. Implement runtime plumbing and tests once the design checkpoint
  is approved
- [O] Phase 7. Run validation and update operator-facing docs for the new
  default startup behavior

## Resume Checkpoint

Interactive shell implementation, targeted validation, and operator-facing docs
are complete. Resume only if final commit/push work or follow-up ergonomics are
requested.
