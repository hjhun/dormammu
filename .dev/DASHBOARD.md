# DASHBOARD

## Actual Progress

- Goal: Repair `scripts/install.sh` so a local Ubuntu install is usable
  immediately after installation.
- Prompt-driven scope: Make the local installer create a runnable
  `~/.local/bin/dormammu` launcher, add shell PATH bootstrap guidance, and add
  regression coverage for the local install path.
- Active roadmap focus:
- Phase 5. CLI Operator Experience and Progress Visibility
- Phase 6. Installer, Commands, and Environment Diagnostics
- Current workflow phase: test_and_review
- Last completed workflow phase: test_and_review
- Supervisor verdict: `approved`
- Escalation status: `approved`
- Resume point: The local installer fix is implemented and validated. Resume
  from commit preparation or from follow-up installer documentation.

## In Progress

- `scripts/install.sh` now installs the editable package into the repository
  `.venv`, creates `~/.local/bin/dormammu`, and points that launcher at the
  venv-managed CLI.
- The local installer now appends the `~/.local/bin` PATH export to `.bashrc`
  only when the current shell PATH is missing that directory.
- Final local install guidance now tells operators to run `source ~/.bashrc`
  before using the plain `dormammu` command in a new shell.

## Progress Notes

- Focused automated validation passed for `python3 -m unittest
  tests.test_install_script`.
- Added regression coverage for the local installer launcher creation,
  idempotent `.bashrc` PATH bootstrapping, and launcher execution via
  `--help`.
- Manual Ubuntu-style smoke verification passed by installing with a temporary
  `HOME`, then executing `~/.local/bin/dormammu --help`.

## Risks And Watchpoints

- The local installer still targets `.bashrc`; shells that rely on `.zshrc`,
  `.profile`, or other startup files remain outside this automation path.
- The local installer intentionally manages only the launcher PATH bootstrap; it
  does not attempt the root installer's broader global config bootstrap.
