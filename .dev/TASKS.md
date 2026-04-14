# TASKS

## Prompt-Derived Implementation Plan

- [O] Phase 1. Confirm which installer path fails: local editable install,
  release install from source dir, or release install from downloaded archive
- [O] Phase 2. Replace the release install command with an interpreter-bound
  PEP 517 install path that does not depend on legacy `bdist_wheel` behavior
- [O] Phase 3. Add regression coverage in `tests/test_install_script.py`
- [O] Phase 4. Run targeted install-script tests

## Resume Checkpoint

Targeted install-script validation is complete.
