# DASHBOARD

## Actual Progress

- Goal: Refresh the public documentation so `README.md`, `docs/GUIDE.md`, and
  `docs/ko/GUIDE.md` better present Dormammu's supported features and fast
  execution paths.
- Prompt-driven scope: Rework the docs to look more like a polished open source
  project landing surface with highlights, quick start, supported CLIs,
  operator flows, and practical command examples.
- Active roadmap focus:
- Phase 3. Agent CLI Adapter and Single-Run Execution
- Phase 5. CLI Operator Experience and Progress Visibility
- Phase 6. Installer, Commands, and Environment Diagnostics
- Current workflow phase: test_and_review
- Last completed workflow phase: test_authoring
- Supervisor verdict: `approved`
- Escalation status: `approved`
- Resume point: The documentation refresh is implemented and command references
  have been checked against the current CLI surface. Resume from review only if
  another pass on wording, screenshots, or release-readiness polish is needed.

## In Progress

- The top-level README now emphasizes product value, supported workflows, quick
  start, CLI compatibility notes, configuration, and common operator patterns.
- The English and Korean guides now explain the main commands, `.dev` state,
  guidance-file behavior, fallback CLIs, workdir handling, and typical usage
  flows in more practical detail.
- The docs now surface recent Cline support details such as default
  `--verbose` behavior and `--cwd <path>` forwarding when `--workdir` is used.

## Progress Notes

- README, English guide, and Korean guide were rewritten to better match an
  open-source project entry experience instead of a minimal internal note set.
- Command names and feature references were checked against the current parser
  and implementation, including `run-once`, `run`, `resume`, `inspect-cli`,
  session commands, fallback CLI config, and guidance resolution behavior.
- A parser-level sanity check confirmed the documented core subcommands exist in
  the current CLI surface.

## Risks And Watchpoints

- The docs were checked against the current code surface, but not against a
  packaged release install on a fresh machine during this pass.
- The CLI help text did not render usefully through the current module
  invocation path, so command accuracy was confirmed from parser definitions and
  code inspection instead of relying on captured help output alone.
