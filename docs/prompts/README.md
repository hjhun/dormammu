# Development Prompt Index

## Purpose

This directory contains implementation prompts derived from [`docs/PLAN.md`](../PLAN.md).

The prompts are ordered by the recommended build sequence from the plan. File names use a global numeric prefix so the execution order remains unambiguous across phases.

## Naming Convention

Prompt files follow this pattern:

`NN_phaseMM_<topic>.md`

Where:

- `NN` is the global execution order across all prompts
- `phaseMM` matches the implementation phase in `docs/PLAN.md`
- `<topic>` is the concrete development slice for that prompt

## Current Coverage

### Prompt 00. Workspace Project Shadow and Temporary File Policy

Goal:

- move runtime-authored `.dev` and temporary files out of the repository and into a deterministic workspace shadow under `~/.dormammu/workspace/`

Prompt:

- `00_workspace_project_shadow_and_tmp_policy.md`

### Phase 1. Agent Contract and Permission Model

Goal:

- define the stable agent contract and permission model that later extension systems depend on

Prompts:

- `01_phase01_agent_profile_schema.md`
- `02_phase01_permission_ruleset.md`
- `03_phase01_config_loader_precedence.md`
- `04_phase01_backward_compat_migration.md`
- `05_phase01_validation_and_tests.md`

### Phase 2. User and Project Agent Manifests

Goal:

- add repo-local and user-local agent definitions with discovery, validation, and runtime integration

Prompts:

- `06_phase02_agent_manifest_schema.md`
- `07_phase02_manifest_paths_and_discovery.md`
- `08_phase02_manifest_loader_and_validation.md`
- `09_phase02_runtime_integration.md`
- `10_phase02_manifest_tests_and_docs.md`

### Phase 3. Hook Runtime

Goal:

- introduce structured lifecycle hooks with explicit outcomes and safe runtime integration

Prompts:

- `11_phase03_hook_schema.md`
- `12_phase03_hook_config_and_discovery.md`
- `13_phase03_hook_execution_runner.md`
- `14_phase03_runtime_hook_integration.md`
- `15_phase03_hook_tests_and_docs.md`

### Phase 4. Worktree Isolation

Goal:

- add managed worktree execution for isolated or risky stages with deterministic lifecycle behavior

Prompts:

- `16_phase04_worktree_service_foundation.md`
- `17_phase04_git_worktree_lifecycle.md`
- `18_phase04_state_and_resume_integration.md`
- `19_phase04_runtime_stage_isolation.md`
- `20_phase04_worktree_tests_and_docs.md`

### Phase 5. Skill Discovery and Role-Aware Loading

Goal:

- formalize skill discovery, filtering, and runtime visibility as a first-class subsystem

Prompts:

- `21_phase05_skill_model_and_schema.md`
- `22_phase05_skill_discovery_paths.md`
- `23_phase05_permission_aware_skill_filtering.md`
- `24_phase05_runtime_skill_integration.md`
- `25_phase05_skill_tests_and_docs.md`

### Phase 6. MCP Integration Surface

Goal:

- define MCP as a first-class configuration and runtime boundary governed by permissions and hooks

Prompts:

- `26_phase06_mcp_config_schema.md`
- `27_phase06_mcp_registration_and_resolution.md`
- `28_phase06_mcp_permission_and_hook_boundary.md`
- `29_phase06_mcp_runtime_adapter.md`
- `30_phase06_mcp_tests_and_docs.md`

### Phase 7. Event and Artifact Unification

Goal:

- unify lifecycle events, stage results, artifact persistence, and runtime observability

Prompts:

- `31_phase07_lifecycle_event_schema.md`
- `32_phase07_stage_result_unification.md`
- `33_phase07_artifact_writer_and_references.md`
- `34_phase07_runtime_event_integration.md`
- `35_phase07_event_tests_and_docs.md`

### Phase 8. Operator UX and Bootstrap Commands

Goal:

- add inspect and bootstrap commands so operators can understand and initialize the system without source diving

Status:

- not written yet

Suggested next prompt range:

- `36_phase08_inspect_command_surface.md`
- `37_phase08_state_introspection_views.md`
- `38_phase08_bootstrap_init_command.md`
- `39_phase08_cli_examples_and_help_output.md`
- `40_phase08_tests_and_docs.md`

## Recommended Execution Order

1. Complete Prompt `00` first.
2. Continue with the numbered phase prompts in numeric order.
3. Finish all prompts within a phase before moving to the next phase.
4. Treat each phase's final `tests_and_docs` prompt as the closure gate for that phase.

## Why The Numbering Matters

- It keeps the implementation sequence stable even if prompts are viewed outside phase folders.
- It makes handoff easier between agents or sessions.
- It provides a direct bridge from `docs/PLAN.md` to executable development slices.
- It allows prerequisite platform changes such as workspace path policy to land before phase-specific feature work.

## Maintenance Notes

- When adding new prompts, continue the global numeric sequence.
- Keep prerequisite prompts before Phase 1 in the `00_` range when they apply across all later phases.
- Do not renumber existing prompts unless the plan itself changes materially.
- If a phase is split further, preserve the phase number and insert the next available global prefix.
