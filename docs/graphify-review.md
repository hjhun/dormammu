# Graphify Review

Generic AST symbols are demoted before architecture prioritization. Use the candidate table with LOC, test mentions, and runtime area instead of graph degree alone.

## Demoted Generic Symbols

| Rank | Label | Degree | LOC | Test mentions | Runtime area |
| --- | --- | --- | --- | --- | --- |
| 1 | `path()` | 569 | 732 | 58 | agent |
| 2 | `str` | 461 | 0 | 52 | unknown |
| 3 | `load()` | 241 | 1200 | 43 | runtime |
| 4 | `.get()` | 164 | 229 | 29 | runtime |
| 5 | `.run()` | 137 | 412 | 44 | daemon |
| 6 | `.to_dict()` | 58 | 204 | 19 | agent |
| 7 | `.run()` | 55 | 1641 | 44 | runtime |
| 8 | `.run()` | 30 | 1780 | 44 | daemon |
| 9 | `.start()` | 23 | 413 | 27 | daemon |
| 10 | `from_path()` | 18 | 301 | 4 | runtime |

## Architecture Review Candidates

| Rank | Label | Degree | LOC | Test mentions | Runtime area | Source |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `AppConfig` | 478 | 1200 | 31 | runtime | /home/hjhun/samba/github/dormammu/backend/dormammu/config.py |
| 2 | `LoopRunner` | 260 | 1641 | 10 | runtime | /home/hjhun/samba/github/dormammu/backend/dormammu/loop_runner.py |
| 3 | `StateRepository` | 237 | 1477 | 15 | state | /home/hjhun/samba/github/dormammu/backend/dormammu/state/repository.py |
| 4 | `AgentsConfig` | 217 | 204 | 8 | agent | /home/hjhun/samba/github/dormammu/backend/dormammu/agent/role_config.py |
| 5 | `LoopRunRequest` | 200 | 1641 | 6 | runtime | /home/hjhun/samba/github/dormammu/backend/dormammu/loop_runner.py |
| 6 | `AgentProfile` | 176 | 295 | 5 | agent | /home/hjhun/samba/github/dormammu/backend/dormammu/agent/profiles.py |
| 7 | `StageResult` | 166 | 535 | 8 | runtime | /home/hjhun/samba/github/dormammu/backend/dormammu/results.py |
| 8 | `DaemonRunner` | 163 | 959 | 5 | daemon | /home/hjhun/samba/github/dormammu/backend/dormammu/daemon/runner.py |
| 9 | `PipelineRunner` | 159 | 1780 | 5 | daemon | /home/hjhun/samba/github/dormammu/backend/dormammu/daemon/pipeline_runner.py |
| 10 | `SupervisorReport` | 156 | 1276 | 4 | runtime | /home/hjhun/samba/github/dormammu/backend/dormammu/supervisor.py |
