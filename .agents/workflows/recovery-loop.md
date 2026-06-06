# Recovery Loop

Use this workflow when a Dormammu run is interrupted, failed, or inconsistent.

## Steps

1. Read `DASHBOARD.md`, `TASKS.md`, `COORDINATION.md`,
   `SUPERVISOR_REPORT.md`, and `workflow_state.json`.
2. Identify the latest completed role with usable evidence.
3. Identify the earliest uncertain role.
4. Resume from that role instead of assuming later stages are valid.
5. Preserve unrelated user changes.
6. Record the recovery decision in `COORDINATION.md`.

## Recovery Outcomes

- `resume`: continue from the earliest uncertain stage.
- `restart`: restart the loop when state is not trustworthy.
- `blocked`: stop until external input or environment changes are available.

