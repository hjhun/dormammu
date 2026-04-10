# DASHBOARD

## Actual Progress

- Goal: Migrate `install.sh` from direct `~/.dormammu/bin` PATH injection to
  a `~/.local/bin/dormammu` launcher flow with explicit shell reload guidance.
- Prompt-driven scope: Create a `~/.local/bin` launcher, remove installer-managed
  legacy `~/.dormammu/bin` PATH exports from `.bashrc`, add a `~/.local/bin`
  PATH export only when the current shell `PATH` does not already include it,
  and update installer regression coverage.
- Active roadmap focus:
- Phase 5. CLI Operator Experience and Progress Visibility
- Phase 6. Installer, Commands, and Environment Diagnostics
- Current workflow phase: test_and_review
- Last completed workflow phase: test_and_review
- Supervisor verdict: `approved`
- Escalation status: `approved`
- Resume point: The installer launcher migration is implemented and validated.
  Resume from commit preparation or from follow-up installer docs.

## In Progress

- `install.sh` now installs a `~/.local/bin/dormammu` launcher that execs the
  venv-managed binary instead of expecting `~/.dormammu/bin` to stay on
  `PATH`.
- The installer now removes the installer-managed legacy
  `export PATH="~/.dormammu/bin:$PATH"` equivalent from `.bashrc`, and only
  appends the `~/.local/bin` export when the current shell `PATH` is missing it.
- Final install guidance now tells operators to run `source ~/.bashrc` before
  using `dormammu` from a newly bootstrapped shell PATH.

## Progress Notes

- Focused automated validation passed for `tests.test_install_script`.
- Added regression coverage for launcher creation, legacy PATH cleanup,
  conditional `~/.local/bin` PATH bootstrapping, and the explicit shell reload
  guidance.

## Risks And Watchpoints

- The installer still targets `.bashrc`; shells that rely on `.zshrc`,
  `.profile`, or other startup files remain outside this automation path.
- Legacy cleanup removes the installer-managed export line shape, not arbitrary
  custom shell snippets that happen to reference `~/.dormammu/bin`.
