---
name: architect
description: Produces architecture and OOAD design documents when the planner decides design is needed. Use for Dormammu architect-stage work, functional/non-functional requirement analysis, ISO-style quality attributes, module boundaries, interfaces, data contracts, state models, recovery behavior, and implementation-ready design handoff.
---

# Architect Skill

Use this skill as the explicit architect-stage skill. In the built-in runtime,
the compatibility role may still be called `designer`; the responsibilities
are the same as the architect stage.

## Workflow

1. Print `[[Architect]]` unless the runtime contract requires `[[Designer]]`.
2. Read original and refined requirements.
3. Read the planner output and active tasks.
4. Analyze functional and non-functional requirements.
5. Produce OOAD design with responsibilities, collaborations, interfaces, and
   state behavior.
6. Evaluate quality attributes: reliability, maintainability, performance,
   security, compatibility, operability, portability, and usability.
7. Define validation expectations for unit, integration, smoke, and optional
   system tests.
8. Store the design in the active prompt workspace under `.dev/logs/` or the
   planner-specified design path.

## Output

Write a concise design document with:

- context and requirements summary
- functional design
- non-functional design
- OOAD model
- interfaces and data contracts
- state, recovery, and resumability decisions
- validation strategy
- risks, assumptions, and tradeoffs

## Done Criteria

The architect stage is complete when developer, tester, and reviewer agents can
execute from the documented contracts without inventing missing design.
