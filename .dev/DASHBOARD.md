# DASHBOARD

## Actual Progress

- Goal: Clarify the Dormammu CLI so operators can discover `daemonize` and
  understand how JSON config is injected without reading the source.
- Prompt-driven scope: Make `--help`, `README.md`, and `docs/GUIDE.md` explain
  the command groups, the `daemonize --config` entry point, and the runtime
  config resolution path for `dormammu.json`.
- Active roadmap focus:
- Phase 5. CLI Operator Experience and Progress Visibility
- Phase 6. Installer, Commands, and Environment Diagnostics
- Current workflow phase: commit
- Last completed workflow phase: test_and_review
- Supervisor verdict: `approved`
- Escalation status: `approved`
- Resume point: The CLI help and docs clarification slice is implemented and
  validated. Resume from commit preparation or optional follow-up UX polish
  around typo recovery and command aliasing.

## In Progress

- The top-level CLI help now groups commands by use case and explicitly calls
  out the two config entry points: runtime config versus daemon queue config.
- `show-config` and `daemonize --help` now explain where JSON config is loaded
  from and include concrete invocation examples.
- `README.md` and `docs/GUIDE.md` now surface `show-config` earlier and
  document how `dormammu.json`, `DORMAMMU_CONFIG_PATH`, and `daemonize.json`
  fit together.

## Progress Notes

- Validation passed for `python3 -m unittest tests.test_cli`.
- Focused coverage now asserts that top-level help mentions runtime and daemon
  config entry points, and that `daemonize --help` retains the split-config
  guidance.

## Risks And Watchpoints

- Operators can still type `demonize` by habit, so help text clarity reduces
  confusion but does not yet provide typo-tolerant aliases.
- The guide and README are aligned for English documentation, but localized
  docs may still need a follow-up pass if parity is required.
- Config behavior is now documented more clearly, so future changes to
  resolution order should update help text and docs together.
