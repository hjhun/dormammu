# PLAN

## Prompt-Derived Implementation Plan

- [O] Phase 1. Inspect the release installer, packaging metadata, and existing
  tests to identify why raw `install.sh` fails on Python 3.10
- [O] Phase 2. Update the release install path to avoid the legacy
  `bdist_wheel` fallback and keep the local editable installer behavior intact
- [O] Phase 3. Add regression coverage for the fixed release-install command
  path
- [O] Phase 4. Execute targeted validation and confirm the installer fix is
  ready for final verification

## Resume Checkpoint

Targeted validation completed. Resume only if follow-up packaging validation is
requested.
