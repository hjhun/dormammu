# DASHBOARD

## Actual Progress

- Goal: Apply Ralph-inspired improvements to dormammu — Codebase Patterns
  accumulation, `<promise>COMPLETE</promise>` self-completion signal, PRD agent
  skill, and Mermaid workflow visualization in the dashboard template.
- Prompt-driven scope: Internal implementation changes only; no existing CLI
  commands were added or removed.
- Active roadmap focus:
- Phase 5. CLI Operator Experience and Progress Visibility
- Current workflow phase: commit
- Last completed workflow phase: final_verification
- Supervisor verdict: `approved`
- Escalation status: `approved`
- Resume point: All four improvements are implemented and 220 tests pass.
  Proceed to commit.

## Workflow Phases

```mermaid
flowchart LR
    plan([Plan]) --> design([Design])
    design --> develop([Develop])
    design --> test_author([Test Author])
    develop --> test_review([Test & Review])
    test_author --> test_review
    test_review --> final_verify([Final Verify])
    final_verify -->|approved| commit([Commit])
    final_verify -->|rework| develop
```

## In Progress

All implementation complete. Awaiting commit.

## Progress Notes

- `templates/dev/patterns.md.tmpl` — new template for `.dev/PATTERNS.md`
- `StateRepository.read_patterns_text()` / `_ensure_patterns_file()` — bootstrap and read PATTERNS.md
- `guidance.build_guidance_prompt(patterns_text=...)` — injects patterns into initial prompts
- `continuation.build_continuation_prompt(patterns_text=...)` — includes patterns + update instruction in retries
- `loop_runner.LoopRunner._stdout_has_promise_complete()` — detects `<promise>COMPLETE</promise>` in agent stdout
- `agents/skills/prd-agent/SKILL.md` — new PRD generation skill
- `templates/dev/dashboard.md.tmpl` — Mermaid workflow diagram added
- All 220 tests pass.

## Risks And Watchpoints

- PATTERNS.md is repo-wide (`.dev/PATTERNS.md`), not session-specific. Multiple
  concurrent sessions share the same patterns file.
- `<promise>COMPLETE</promise>` bypasses supervisor validation. Agents should
  only emit it when all work is genuinely done.
- Mermaid rendering requires a Markdown viewer that supports Mermaid (GitHub,
  VS Code with extension, etc.).
