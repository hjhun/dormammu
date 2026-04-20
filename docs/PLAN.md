# Dormammu Reference Plan

## Purpose

This document turns a reference analysis of Claude Code and OpenCode into a practical development plan for `dormammu`.

Analysis date: April 19, 2026.

Primary sources used:

- Claude Code official docs:
  - `https://docs.anthropic.com/en/docs/claude-code/overview`
  - `https://docs.anthropic.com/en/docs/claude-code/settings`
  - `https://docs.anthropic.com/en/docs/claude-code/hooks`
  - `https://docs.anthropic.com/en/docs/claude-code/sub-agents`
  - `https://docs.anthropic.com/en/docs/claude-code/mcp`
  - `https://docs.anthropic.com/en/docs/claude-code/ide-integrations`
- Claude Code npm package `@anthropic-ai/claude-code` version `2.1.114`
- OpenCode repository `sst/opencode` at commit `33b2795cc84c79e91e15549609713567eb08348a`
- Local `graphify` analysis of:
  - the Claude Code docs/package corpus
  - a curated OpenCode core corpus
  - the current `dormammu` repository

Note: Claude Code does not expose its full runtime source, so its section focuses on public architecture surfaces rather than internals.

## Structural Summary

### Claude Code

Claude Code exposes a strong product model through configuration, agent definitions, hooks, and MCP instead of through a public runtime source tree.

Key patterns:

- Hierarchical settings:
  - `~/.claude/settings.json`
  - `.claude/settings.json`
  - `.claude/settings.local.json`
- Repo-local and user-local subagents defined as Markdown files with frontmatter.
- Per-agent control over prompts, models, tools, permissions, hooks, and optional isolated worktree behavior.
- Hooks as a first-class lifecycle surface:
  - prompt submission
  - tool execution
  - config changes
  - session events
  - worktree create/remove
  - MCP elicitation
- MCP treated as a core extension boundary, including `claude mcp serve`.
- IDE integrations exist, but they are downstream integrations, not the core operating model.

What matters for `dormammu`:

- Claude Code treats extensibility as part of the product contract.
- The product surface is repo-aware and configuration-first.
- Behavioral customization is declarative and scoped.

### OpenCode

OpenCode is structurally broader than `dormammu`, but its useful lessons come from the open terminal-agent core, not from its desktop/web breadth.

Observed core structure:

- The terminal agent core is concentrated under `packages/opencode/src`.
- Repo-local extensions live under `.opencode/`:
  - `agent/`
  - `command/`
  - `tool/`
  - `opencode.jsonc`
- Built-in agent modes are explicit:
  - `build`
  - `plan`
  - `general`
  - `explore`
- Permissions are typed and evaluated as `allow`, `deny`, or `ask`.
- Skills are discovered from:
  - project config
  - user directories
  - external `.claude` and `.agents` trees
- Worktrees are implemented as a dedicated service with create, reset, and remove flows.
- MCP, plugins, session storage, sharing, and provider adapters are separated into explicit modules.

What matters for `dormammu`:

- OpenCode treats agent profiles, skills, permissions, and worktrees as runtime primitives.
- It has a clean boundary between the core execution engine and optional extension surfaces.
- The repo-local extension model is concrete and reproducible.

### dormammu Today

The local `graphify` report identifies the current hub nodes as:

- `AppConfig`
- `LoopRunner`
- `AgentsConfig`
- `SupervisorReport`
- `LoopRunRequest`
- `DaemonRunner`
- `StateRepository`
- `SupervisorCheck`
- `PipelineRunner`

This indicates that `dormammu` already has the right orchestration center:

- configuration
- loop execution
- pipeline execution
- supervision
- daemonized scheduling
- resumable state

The main gap is not orchestration. The main gap is productized extension structure.

## What dormammu Should Adopt

### 1. Typed Agent Profiles

`dormammu` should move from role-specific configuration fragments toward a typed agent-profile contract.

Required capabilities:

- named profiles such as `plan`, `develop`, `test`, `review`, and `commit`
- explicit permissions for:
  - tools
  - filesystem scope
  - network access
  - worktree usage
- per-profile model and CLI overrides
- deterministic precedence between built-in defaults and project overrides

Why it matters:

- This gives the runtime a stable contract for all future extension work.
- It reduces ad hoc role handling inside `LoopRunner`, `PipelineRunner`, and `CliAdapter`.

### 2. User and Project Agent Manifests

`dormammu` should support repo-local and user-local agent definitions on disk.

Recommended shape:

- Markdown or YAML-backed manifests
- project-local path for shared agents
- user-local path for personal agents
- manifest-defined:
  - description
  - prompt
  - permissions
  - CLI override
  - model selection
  - optional skills

Why it matters:

- Projects should be able to extend agent behavior without editing Python source.
- This aligns well with the existing `agents/` guidance bundle.

### 3. Lifecycle Hooks

`dormammu` should add a safe hook system around its execution lifecycle.

Recommended initial hook points:

- prompt intake
- plan start
- stage start
- stage completion
- tool execution
- config changes
- final verification
- session end

Recommended response model:

- `allow`
- `deny`
- `warn`
- `annotate`
- `background_started`

Why it matters:

- Hooks allow policy, verification, auditing, and automation without hard-coding repository-specific logic into the runtime.
- Claude Code demonstrates that hooks become a major product surface once the runtime is stable.

### 4. Managed Worktree Isolation

`dormammu` should support optional git worktree execution for risky or high-churn stages.

Best initial uses:

- developer stage
- reviewer reproduction
- experimental feature implementation
- multi-agent parallel slices that should not collide in one checkout

Why it matters:

- Isolation reduces accidental overlap with user changes.
- Worktree state can be made resumable and explicit instead of implicit shell convention.

### 5. Permission-Aware Skill Discovery

`dormammu` already uses skills, but the loading and exposure model should become a first-class runtime subsystem.

Recommended features:

- consistent discovery of repo-local and user-local skills
- role-aware filtering
- duplicate-name conflict policy
- visibility in logs and operator state
- support for preloaded or denied skills per agent profile

Why it matters:

- Skills are already central to how work is organized in this repository.
- OpenCode shows that skill loading becomes much more useful once it is permission-aware.

### 6. MCP as a First-Class Boundary

`dormammu` should formalize MCP at the configuration and runtime boundary.

Recommended direction:

- allow project-level MCP server definitions
- allow per-agent MCP allowlists
- route MCP access through the same permission and hook layers as native tools
- consider `dormammu mcp serve` only after the internal stage contract stabilizes

Why it matters:

- Claude Code treats MCP as part of the product core, not an afterthought.
- `dormammu` is already orchestration-heavy, so a clean tool boundary has high leverage.

### 7. Typed Event and Artifact Model

`dormammu` should replace more heuristic stage inference with explicit, typed stage events and results.

Recommended scope:

- stage requested
- stage started
- stage finished
- hook blocked
- permission requested
- permission granted
- worktree created
- evaluator decided
- final verification passed or failed

Why it matters:

- This reduces regex-based interpretation.
- It aligns `LoopRunner`, `PipelineRunner`, `Supervisor`, and daemon behavior under one observable contract.

### 8. Operator Inspection and Bootstrap Commands

`dormammu` should expose more of its internal structure through CLI commands.

Recommended commands:

- `inspect-agent`
- `inspect-skill`
- `inspect-hooks`
- `inspect-worktree`
- `inspect-state`
- `init-agent-files` or equivalent

Why it matters:

- Operators should not need to read raw `.dev/*.json` or source files to understand the system state.
- OpenCode’s repo bootstrap and management commands show the value of this surface.

## Explicit Non-Goals

The following ideas are not recommended for the current product scope:

- desktop or web control surfaces
- hosted control plane or cloud collaboration layer
- marketplace-style plugin distribution before hooks and agent manifests stabilize

These would increase surface area faster than they increase product clarity.

## Development Plan

### Phase 1. Agent Contract and Permission Model

Goals:

- define a stable `AgentProfile` schema
- model tool, filesystem, network, and worktree permissions
- map current runtime roles into the new schema without breaking existing config

Deliverables:

- typed schema and loader
- config precedence rules
- migration support from current role-based config
- unit tests for permission evaluation

### Phase 2. User and Project Agent Manifests

Goals:

- load agent manifests from project and user locations
- merge manifest agents with built-in role defaults
- provide exact validation errors for bad manifests

Deliverables:

- discovery rules
- precedence policy
- manifest parser and validator
- tests for conflicts and overrides

### Phase 3. Hook Runtime

Goals:

- add synchronous lifecycle hooks first
- keep the hook input and output contract structured
- support blocking and non-blocking outcomes

Deliverables:

- hook schema
- hook execution runner
- typed hook result model
- tests for allow, deny, warn, and annotation flows

### Phase 4. Worktree Isolation

Goals:

- add managed git worktrees for selected stages
- store worktree state explicitly in machine-readable state
- make resume and cleanup behavior deterministic

Deliverables:

- worktree service module
- CLI commands for create/list/reset/remove
- integration tests for worktree lifecycle

### Phase 5. Skill Discovery and Role-Aware Loading

Goals:

- unify how repo-local and user-local skills are found
- allow role-specific skill filtering
- expose loaded skills in logs and operator-facing status

Deliverables:

- discovery service
- conflict handling
- permission-aware filtering
- tests for duplicate names and missing skill files

### Phase 6. MCP Integration Surface

Goals:

- define MCP server configuration as part of the project and agent contract
- route MCP access through permissions and hooks
- fail clearly when a configured server is unavailable

Deliverables:

- MCP config schema
- runtime adapter boundary
- failure reporting and validation tests

### Phase 7. Event and Artifact Unification

Goals:

- emit typed events for the full pipeline lifecycle
- persist explicit stage results instead of inferred status where possible
- align `.dev` files with the underlying machine-truth event model

Deliverables:

- stage result schema
- unified artifact writer
- integration tests across loop, pipeline, supervisor, and daemon flows

### Phase 8. Operator UX and Bootstrap Commands

Goals:

- add inspect and bootstrap commands
- make state introspection cheaper than source diving
- keep the product CLI-only and documentation-first

Deliverables:

- `inspect-*` commands
- bootstrap/init command for project guidance files
- updated docs and examples

## Recommended Build Order

1. Phase 1. Agent Contract and Permission Model
2. Phase 2. User and Project Agent Manifests
3. Phase 3. Hook Runtime
4. Phase 4. Worktree Isolation
5. Phase 5. Skill Discovery and Role-Aware Loading
6. Phase 6. MCP Integration Surface
7. Phase 7. Event and Artifact Unification
8. Phase 8. Operator UX and Bootstrap Commands

## Why This Order

- Permissions and manifests must stabilize before hooks, skills, and MCP can be governed correctly.
- Worktrees are valuable, but they are safer after agent contracts exist.
- Event unification should follow the extension work, otherwise the event schema will need a second redesign.

## Success Criteria

- custom project agents can be added without editing Python source
- high-risk stages can run in isolated worktrees and recover cleanly
- hooks can block or annotate runtime behavior in a typed and testable way
- skills and MCP servers can be exposed per role without widening permissions globally
- `.dev` state becomes more explicit as extensibility increases
