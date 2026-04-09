name: building-and-deploying
description: Builds release artifacts, installation flows, and deployment outputs for this project. Use when the user asks to package the tool, create install scripts, prepare releases, or verify deployable outputs.
---

# Building and Deploying Skill

Use this skill when the active phase is packaging, release preparation, installation, or deployment validation.

Related skills:

- Consume implementation from `developing-agent`
- Ensure required test artifacts from `test-authoring-agent` are available when packaging depends on them
- Hand final execution evidence to `testing-and-reviewing`

## Inputs

- Current implementation state
- Build and release phase items from `.dev/TASKS.md`
- Project packaging requirements from [PROJECT.md](../../../PROJECT.md)

## Workflow

1. Identify the expected deliverable: local package, installer, archive, release artifact, or deployment bundle.
2. Build only from the current checked-out state; do not hide missing prerequisites.
3. Capture build commands, outputs, and failures in `.dev/logs/` or release notes.
4. Update `.dev/DASHBOARD.md` with actual build status, artifact paths, and next actions.
5. Mark completed prompt-derived packaging phase items in `.dev/TASKS.md`.

## Build Rules

- Prefer reproducible commands over manual steps.
- When creating installers, include environment checks and friendly failure messages.
- Record any required manual deployment steps explicitly.
- If build failures expose implementation bugs, route back to development with concrete evidence.

## Expected Outputs

- Verified build or packaging artifacts
- Install or deployment scripts where applicable
- Updated `.dev` state describing artifact status

## Done Criteria

This skill is complete when the requested artifact exists, can be described precisely, and its status is reflected in `.dev`.
