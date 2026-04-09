# DASHBOARD

## Actual Progress

- Goal: Create a distributable `agents/` workflow bundle, remove the
  `-workflows` postfix in the shipped skills, and align packaging and docs with
  the new layout.
- Prompt-driven scope: Copy repository guidance into `agents/`, split it into
  grouped workflow documents, and include the bundle in dormammu distribution
  assets.
- Active roadmap focus:
- Phase 7. Hardening, Multi-Session, and Productization
- Current workflow phase: commit
- Last completed workflow phase: test_and_review
- Supervisor verdict: `approved`
- Escalation status: `approved`
- Resume point: Continue from optional cleanup or commit preparation for the
  validated `agents/` bundle migration

## In Progress

- The new `agents/` directory is in place as the portable workflow bundle that
  should ship with dormammu.
- The copied skills now use postfix-free names and the grouped workflow
  documents are in `agents/workflows/`.
- Packaging metadata, packaged assets, and operator-facing docs are aligned
  with the new bundle layout.

## Progress Notes

- `agents/AGENTS.md` should become the distributable entry point for the new
  workflow bundle.
- `agents/workflows/` should group the lifecycle into four operator-facing
  documents.
- `agents/skills/` should keep the existing guidance shape but use postfix-free
  skill names and updated references.
- The packaged asset copy under `backend/dormammu/assets/agents/` should stay
  synchronized with the source `agents/` tree.
- Validation passed with `python3 -m unittest tests.test_config
  tests.test_state_repository tests.test_install_script`.
- A wheel built with `python3 -m pip wheel . --no-deps` contains the expected
  `dormammu/assets/agents/` files.

## Risks And Watchpoints

- The repository may temporarily contain both `.agents/` and `agents/`, so the
  official distributable path needs to stay explicit in the docs.
- Packaged asset metadata must include the new `agents/` bundle or the deploy
  goal is only partially met.
- The machine workflow state and operator-facing Markdown must stay aligned
  while the migration is in progress.
