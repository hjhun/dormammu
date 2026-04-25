# Dormammu Remediation Roadmap

작성일: 2026-04-25

## 목적

이 문서는 `docs/ANLAYSIS.md`의 분석 결과를 바탕으로 수정 작업을
실행 가능한 단계로 정리한다. 목표는 새 기능 추가가 아니라 런타임
계약을 더 작고 명확한 단위로 나누고, 완료 판정과 운영자 상태가 같은
사실을 가리키도록 정리하는 것이다.

## 원칙

- CLI-only 제품 범위를 유지한다.
- 이미 통과 중인 guidance bundle sync와 result/supervisor 회귀 테스트를
  기준선으로 삼는다.
- 큰 runner와 state/config 모듈은 한 번에 갈아엎지 않고, 먼저 읽기 전용
  resolver/service를 추출한 뒤 write path를 이동한다.
- `.dev` Markdown은 운영자 표시 계층으로 보고, runtime truth는
  `StageResult`, lifecycle event, JSON state 쪽으로 이동한다.
- 각 단계는 독립적으로 검증 가능해야 한다.

## Phase 0. Baseline And Guardrails

### 목표

현재 정상 신호를 고정하고, 이후 리팩터링이 guidance, result model,
supervisor 동작을 깨지 않도록 빠른 회귀 기준선을 만든다.

### 작업

- `scripts/verify-agents-sync.sh`를 필수 사전 검증으로 문서화한다.
- 현재 통과한 핵심 테스트 묶음을 baseline command로 고정한다.
- 전체 테스트 실행 비용과 실패 여부를 한 번 더 측정해 CI 후보를 정한다.
- graphify 분석 산출물 위치와 generic symbol noise 한계를 문서화한다.
- `docs/BASELINE.md`와 `scripts/verify-baseline.sh`를 이후 phase의 공통
  진입 기준으로 사용한다.

### 완료 조건

- baseline 검증 명령이 `docs/ROADMAP.md`와 개발 문서에 명시되어 있다.
- guidance bundle drift가 발생하면 실패하는 테스트/스크립트가 확인된다.
- 이후 phase가 참조할 "known-good" 테스트 묶음이 정해져 있다.

### 검증

```text
scripts/verify-baseline.sh quick
scripts/verify-baseline.sh full
```

## Phase 1. Result-Driven Completion

### 목표

완료 판정의 primary truth를 Markdown heuristic에서 `StageResult`와
lifecycle event로 이동한다.

### 작업

- `Supervisor`가 어떤 heuristic으로 verdict를 만들었는지 structured
  metadata에 기록한다.
- `StageResult`가 존재하는 경우 supervisor가 이를 우선 판정 자료로
  사용하도록 우선순위를 정리한다.
- `WORKFLOWS.md`, `PLAN.md`, task sync, unresolved-question regex는
  fallback evidence로 격하한다.
- daemon result publication이 stale PLAN sync를 보정하는 현재 특수 경로를
  result aggregation helper로 이동한다.

### 완료 조건

- terminal stage evidence가 있는 완료 run은 Markdown projection 지연만으로
  `failed`가 되지 않는다.
- Markdown이 완료로 보이더라도 stage result/artifact evidence가 없으면
  승인되지 않는다.
- supervisor report에 판정 근거가 structured field로 남는다.

### 검증

```text
pytest -q tests/test_results.py tests/test_supervisor.py
pytest -q tests/test_pipeline_runner.py tests/test_loop_runner.py tests/test_daemon.py
```

## Phase 2. Configuration Resolver Split

### 목표

`AppConfig`가 모든 런타임 해석을 연결하는 god object가 되지 않도록,
설정 모델과 resolver 책임을 분리한다.

### 작업

- `AppConfig`에 남길 값 모델과 분리할 resolver 책임을 표로 정리한다.
- agent profile resolution을 별도 service로 이동한다.
- MCP server/profile access resolution을 별도 service로 이동한다.
- guidance/path/package asset resolution을 작은 resolver로 분리한다.
- 기존 public API compatibility를 유지하기 위한 forwarding method를
  한시적으로 둔다.
- resolver별 소유 경계는 `docs/config-resolvers.md`에 기록한다.

### 완료 조건

- 새 config option 추가 시 수정해야 할 소유 모듈이 명확하다.
- `AppConfig`는 값 보관과 최소 조합 로직만 담당한다.
- 기존 CLI/config 테스트가 변경 없이 통과하거나, migration 테스트가
  명확히 추가된다.

### 검증

```text
pytest -q tests/test_config.py tests/test_role_config.py tests/test_agent_profiles.py
pytest -q tests/test_mcp_config.py tests/test_mcp_runtime.py
pytest -q tests/test_cli.py
```

## Phase 3. State Projection Simplification

### 목표

`StateRepository`를 facade로 축소하고, root `.dev` mirror와 session-local
state의 책임을 명확히 나눈다.

### 작업

- state write path를 bootstrap, run result, stage result, prompt, worktree,
  operator projection 단위로 분류한다.
- root mirror를 derived projection으로 정의하고 sync 방향과 충돌 조건을
  문서화한다.
- `StateRepository`에서 write-path별 service를 추출한다.
- session state와 workflow state 동시 쓰기 규칙을 helper로 집중시킨다.
- stale operator state 보정 로직의 허용 조건을 테스트로 고정한다.
- root mirror와 execution projection 경계는 `docs/state-projection.md`에
  기록한다.

### 완료 조건

- `StateRepository`가 orchestration facade에 가까워진다.
- root/session divergence를 설명하는 문서와 테스트가 있다.
- `.dev` 삭제/복구/세션 전환 경로가 기존보다 좁은 모듈에서 처리된다.

### 검증

```text
pytest -q tests/test_state_repository.py tests/test_state_modules.py
pytest -q tests/test_workspace_shadow.py tests/test_recovery.py
pytest -q tests/test_repo_and_sessions_commands.py
```

## Phase 4. Runner And Stage Execution Decomposition

### 목표

`PipelineRunner`, `LoopRunner`, `DaemonRunner`의 공통 실행 의미를 더 작은
stage execution service와 result aggregation helper로 모은다.

### 작업

- one-shot stage call, artifact persistence, lifecycle emit, retry metadata
  기록을 공통 service 후보로 추출한다.
- `PipelineRunner`는 stage ordering과 re-entry orchestration에 집중하도록
  역할을 줄인다.
- `LoopRunner`의 stagnation/retry/continuation 판단을 helper로 나눈다.
- `DaemonRunner`의 result publication과 prompt lifecycle 처리를 분리한다.
- runner별 manual_review_needed 처리 차이를 표준화한다.
- runner result 집계 경계는 `docs/runner-results.md`에 기록한다.

### 완료 조건

- runner별 완료/실패/manual review 의미가 `StageResult` helper를 통해
  설명된다.
- pipeline, loop, daemon 중 하나의 변경이 다른 경로의 result semantics를
  암묵적으로 바꾸지 않는다.
- artifact/lifecycle 기록이 stage 종류와 무관하게 같은 형식으로 남는다.

### 검증

```text
pytest -q tests/test_pipeline_runner.py tests/test_loop_runner.py tests/test_daemon.py
pytest -q tests/test_agent_cli_adapter.py tests/test_lifecycle.py tests/test_artifacts.py
```

## Phase 5. Role Taxonomy And Goals Unification

### 목표

main pipeline role과 goals/autonomous-only role을 명확히 구분하고, 문서,
config, runtime profile 이름을 같은 계약으로 맞춘다.

### 작업

- canonical role taxonomy 표를 작성한다.
- `analyzer`는 goals/autonomous-only role인지, main pipeline 전 단계인지
  명확히 고정한다.
- `architect` 등 이전 명칭을 compatibility alias로 남길지 제거할지 결정한다.
- README, GUIDE, config example, `agent/role_config.py`, `agent/profiles.py`를
  같은 taxonomy에 맞춘다.
- `GoalsScheduler`가 main refine/plan/pipeline 계약과 어떻게 연결되는지
  문서화한다.
- canonical taxonomy와 goals 연결 계약은 `docs/role-taxonomy.md`에 기록한다.

### 완료 조건

- 사용자는 planner/designer/analyzer의 차이를 문서만 보고 설명할 수 있다.
- role-specific CLI 설정과 skill guidance 이름이 충돌하지 않는다.
- goals prompt synthesis가 main workflow와 별도 제품처럼 보이지 않는다.

### 검증

```text
pytest -q tests/test_role_config.py tests/test_prompt_identity.py
pytest -q tests/test_goals_config.py tests/test_goals_scheduler.py tests/test_goals_telegram.py
pytest -q tests/test_mermaid_docs.py
```

## Phase 6. Operator Entry Point Consolidation

### 목표

CLI, interactive shell, daemon, Telegram control surface가 같은 application
service를 호출하도록 정리해 사용자-facing drift를 줄인다.

### 작업

- command handler를 run/session/config/daemon/telegram 진입점으로 분리한다.
- shell과 Telegram이 CLI 내부 구현을 우회하지 않고 같은 service를 쓰도록
  경계를 정한다.
- command matrix를 문서와 테스트 fixture로 관리한다.
- daemon/goals queue lifecycle의 status 문구를 result model과 맞춘다.

### 완료 조건

- 동일 기능이 CLI, shell, Telegram에서 같은 상태 전이를 만든다.
- `_cli_handlers.py` 변경 없이 새 domain command를 추가할 수 있는 구조가
  생긴다.
- 사용자 문서의 command behavior가 테스트 가능한 형태로 고정된다.

### 검증

```text
pytest -q tests/test_cli.py tests/test_repo_and_sessions_commands.py
pytest -q tests/test_daemon.py tests/test_telegram_bot_resilience.py
pytest -q tests/test_goals_telegram.py tests/test_help_parser.py
```

## Phase 7. Analysis Tooling Cleanup

### 목표

graphify 분석 결과에서 generic AST symbol noise를 줄여 이후 구조 분석의
신호대잡음비를 높인다.

### 작업

- `path()`, `str`, `.to_dict()`, `from_dict()` 같은 generic symbol을
  분석 보고서에서 낮은 우선순위로 분류한다.
- architecture review에서는 graph centrality, LOC, test ownership,
  runtime ownership을 함께 보는 기준을 문서화한다.
- graphify 재실행 절차와 결과 해석 기준을 `docs/ANLAYSIS.md` 또는 별도
  runbook에 연결한다.

### 완료 조건

- 다음 graphify 보고서에서 generic symbol이 핵심 설계축으로 오해되지
  않는다.
- 분석 결과가 바로 수정 우선순위로 이어지는 기준이 문서화된다.

### 검증

```text
graphify --update
```

## 권장 실행 순서

1. Phase 0으로 baseline을 고정한다.
2. Phase 1로 완료 판정의 primary truth를 먼저 정리한다.
3. Phase 2와 Phase 3을 작은 PR 단위로 병렬 진행한다.
4. Phase 4에서 runner decomposition을 진행한다.
5. Phase 5와 Phase 6으로 문서/entrypoint drift를 줄인다.
6. Phase 7은 각 phase 후 재분석 시 반복적으로 적용한다.

## 단계별 리스크

| Phase | 주요 리스크 | 완화책 |
| --- | --- | --- |
| 0 | 전체 테스트가 오래 걸리거나 실패할 수 있음 | 빠른 baseline과 전체 suite를 분리 |
| 1 | Markdown-only 완료 경로가 깨질 수 있음 | 기존 supervisor 회귀 테스트 유지 |
| 2 | config compatibility가 깨질 수 있음 | forwarding API와 migration 테스트 추가 |
| 3 | root/session sync가 어긋날 수 있음 | projection source와 write direction 명시 |
| 4 | runner behavior가 미묘하게 변할 수 있음 | stage result golden tests 추가 |
| 5 | 문서와 runtime role 이름이 다시 drift될 수 있음 | taxonomy fixture를 테스트에 사용 |
| 6 | CLI surface 변경이 사용자 workflow를 깨뜨릴 수 있음 | command matrix snapshot 테스트 |
| 7 | tooling 개선이 제품 코드 우선순위를 밀어낼 수 있음 | 분석 필터는 문서/runbook 중심으로 제한 |

## 완료 정의

로드맵 전체는 다음 조건을 만족하면 완료로 본다.

- 완료 판정은 structured runtime result를 우선한다.
- `AppConfig`, `StateRepository`, runner 계층의 변경 영향 범위가 줄어든다.
- role taxonomy와 goals 경로가 문서와 코드에서 같은 의미를 갖는다.
- CLI, daemon, Telegram 결과가 같은 status/verdict 계약을 따른다.
- guidance bundle sync와 주요 regression suite가 CI에서 안정적으로 통과한다.
