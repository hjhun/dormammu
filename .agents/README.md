# Dormammu Agent Guidance Bundle

This directory is the source guidance bundle installed with Dormammu.
It is designed for Codex, Claude, agy(Antigravity), and Cline.

The bundle defines a shared autonomous development loop:

```text
analyzer -> refiner -> planner -> architect -> developer -> reviewer
         -> coordinator -> supervisor
```

Simple tasks may use `.agents/workflows/simple-task.md` to skip stages that do
not add value. Every workflow must still make validation evidence visible.

## Layout

```text
.agents/
  AGENTS.md
  roles/<role>/SKILL.md
  workflows/*.md
  templates/*.md
  adapters/<agent>/AGENTS.md
```

## State Files

Runtime state is projected to `.dev/` or the configured Dormammu shadow
workspace. Use the templates in `.agents/templates/` when a state file does
not already exist.

