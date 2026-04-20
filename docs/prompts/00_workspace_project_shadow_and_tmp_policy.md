# Prompt 00: Workspace Project Shadow and Temporary File Policy

## Objective

Introduce a workspace-level project shadow under `~/.dormammu/workspace/` so `dormammu` writes operational `.dev` documents and temporary files outside the source repository while still targeting the real project directory for development work.

## Background

The current workflow writes planning and execution documents directly under the project's `.dev/` directory during development.

This works, but it mixes operator state and temporary runtime artifacts into the repository working tree. That makes the project noisier, increases accidental file churn, and creates avoidable coupling between runtime state and source-controlled files.

The desired behavior is:

- create a workspace project directory under `~/.dormammu/workspace/<home-relative-project-path>`
- create and maintain `.dev/` inside that workspace project directory
- create and use `.tmp/` inside that same workspace project directory for temporary files
- remove unnecessary temporary files when they are no longer needed

For example, if the real project path is `~/samba/github/dormammu`, the workspace shadow path should be:

`~/.dormammu/workspace/samba/github/dormammu`

## Problem

`dormammu` currently treats the repository itself as the place where operational state is written. That creates several issues:

- `.dev` state lives inside the source tree instead of a managed runtime workspace
- temporary files do not have one clear lifecycle-managed home
- cleanup behavior is inconsistent
- resumability and operator state are coupled to repository-local filesystem layout

The product should distinguish clearly between:

- the real source repository being edited
- the workspace shadow used for operational state, reports, and temp artifacts

## Task

Design and implement a workspace shadow model for project-scoped runtime state.

The implementation should:

- derive a deterministic workspace project root from the real project path
- create the workspace project directory when needed
- write `.dev/` state documents under the workspace project root instead of the repository root
- write temporary runtime files under a sibling `.tmp/` directory inside the workspace project root
- write result reports under `~/.dormammu/results/` by invoking the configured CLI to author the report content
- ensure each result report body includes the date and time when the report was generated
- clean up temporary files that are no longer needed

## Path Mapping Rules

Use the user's home directory as the mapping anchor.

Rules:

- if the project path is inside the user's home directory, strip the home prefix and append the remaining relative path to `~/.dormammu/workspace/`
- if the project path is outside the user's home directory, define and document a deterministic fallback mapping strategy instead of using an unsafe raw absolute path
- normalize path handling so repeated runs always resolve to the same workspace project root

Example mapping:

- real project: `~/samba/github/dormammu`
- workspace root: `~/.dormammu/workspace/samba/github/dormammu`
- state directory: `~/.dormammu/workspace/samba/github/dormammu/.dev`
- temp directory: `~/.dormammu/workspace/samba/github/dormammu/.tmp`

## Design Requirements

- Add a dedicated resolver or service for workspace project path calculation
- Centralize `.dev` and `.tmp` directory resolution instead of scattering path joins across the codebase
- Ensure runtime components that currently write repository-local `.dev` files are migrated to the workspace shadow
- Keep source-editing operations pointed at the actual repository path
- Make the workspace root easy to inspect and reason about for operators

## `.dev` Behavior

The `.dev` directory under the workspace shadow becomes the operational state root for:

- planning documents
- dashboard and workflow documents
- run reports
- machine-readable state files
- stage outputs that are not source files

The source repository should no longer be the default destination for runtime-authored `.dev` documents once this feature is implemented.

## Result Report Behavior

Result reports written for daemon or queued prompt execution should be treated as
operator-facing documents under `~/.dormammu/results/`.

Requirements:

- create result documents under `~/.dormammu/results/` rather than mixing them into the repository
- use the configured CLI to generate or author the report body instead of only assembling a static internal template
- include explicit date and time information in the written report content so operators can see when the report was generated
- keep the report format deterministic enough for resume, troubleshooting, and operator inspection

## `.tmp` Behavior

The `.tmp` directory under the workspace shadow is the managed location for temporary runtime artifacts such as:

- transient prompt files
- intermediate exports
- temporary transcripts
- short-lived command outputs
- staging files used during execution

Temporary file policy:

- create files only when needed
- remove them after successful use when they are not needed for resume, debugging, or operator inspection
- retain only the minimum set required for active execution or explicit troubleshooting
- avoid leaving unbounded temp growth across runs

## Integration Guidance

Review and update runtime paths used by:

- state repository handling
- loop and pipeline execution
- supervisor outputs
- evaluator outputs
- daemon result report generation
- workflow bootstrap and resume flows
- any helper modules that currently assume `.dev` is repository-local

The design should make it obvious which paths refer to:

- the real project root
- the workspace project shadow root
- the workspace `.dev` directory
- the workspace `.tmp` directory
- the result report directory under `~/.dormammu/results/`

## Constraints

- Do not break source editing against the actual repository
- Do not silently mix repository-local `.dev` state with workspace `.dev` state
- Do not bypass the configured CLI when producing result reports under `~/.dormammu/results/`
- Preserve deterministic resume behavior
- Keep the path policy cross-platform enough to evolve later, even if the first implementation targets Unix-like environments
- Avoid ad hoc temp file creation outside the managed workspace `.tmp` directory

## Acceptance Criteria

- `dormammu` derives a deterministic workspace project root from the source project path
- runtime-authored `.dev` documents are written under the workspace shadow
- temporary runtime files are written under `.tmp` in the workspace shadow
- result reports under `~/.dormammu/results/` are authored through the configured CLI
- result report content includes explicit date and time information
- unneeded temporary files are cleaned up according to a defined policy
- the implementation clearly separates source repository operations from workspace state operations

## Validation

- Add unit tests for workspace path resolution
- Add integration tests that verify `.dev` and `.tmp` are created under the workspace shadow
- Verify resume-oriented state reads and writes use the workspace `.dev` location
- Verify result reports are written under `~/.dormammu/results/` through the CLI path and contain date and time metadata
- Verify temporary file cleanup behavior for at least one successful execution path

## Deliverable

Produce the workspace shadow path resolver, migrate `.dev`, temp file usage, and result report generation to the new workspace model, add validation, and document the final path policy clearly for future contributors.
