# Dormammu Project Analysis

작성일: 2026-04-25

## 분석 범위

현재 저장소 전체를 graphify로 분석하고, 핵심 런타임 파일과 검증 신호를
직접 확인했다.

- 분석 대상: `/home/hjhun/samba/github/dormammu`
- graphify 감지 결과: 229 files, 약 217,136 words
- graphify 그래프: 3,691 nodes, 14,835 edges, 41 communities
- graphify 산출물:
  `/home/hjhun/.graphify/samba/github/dormammu/graphify-out/`
- Phase 7 code-only graphify update:
  `graphify-out/` (`3,514 nodes`, `15,136 edges`, `29 communities`)
- 추가 확인:
  `scripts/verify-agents-sync.sh`
  `pytest -q tests/test_packaging_sync.py tests/test_results.py tests/test_supervisor.py`

## 요약

프로젝트의 방향은 명확하다. `dormammu`는 CLI 기반 agent loop
orchestrator이고, `.dev` 상태, role-based pipeline, supervised loop,
daemon/goals/Telegram 제어면을 모두 갖춘다. 문제는 기능 부족보다
런타임 계약이 여러 계층에 넓게 퍼져 있다는 점이다.

graphify가 찾은 핵심 god node는 `AppConfig`, `LoopRunner`,
`StateRepository`, `AgentsConfig`, `AgentProfile`, `DaemonRunner`,
`PipelineRunner`다. 이는 실제 코드 구조와도 맞다. 현재 위험은 이
객체들이 너무 많은 커뮤니티를 연결하면서 변경 영향 범위가 커진다는
점이다.

## 확인된 정상 신호

- `agents/`와 `backend/dormammu/assets/agents/`는 현재 동기화되어 있다.
  `scripts/verify-agents-sync.sh`가 통과했다.
- result model과 supervisor 관련 핵심 회귀 테스트 34개가 통과했다.
- `PipelineRunner`의 one-shot stage는 현재 `CliAdapter.run_once()`를 통해
  실행된다. 과거 분석의 "pipeline이 adapter를 우회한다"는 결론은 현재
  코드에는 맞지 않는다.

## 문제점

### 1. `AppConfig`가 지나치게 많은 런타임 책임을 연결한다

graphify에서 `AppConfig`는 465개 edge를 가진 최상위 bridge node다.
실제 코드에서도 `backend/dormammu/config.py`는 1,308줄이며 경로,
설정 precedence, fallback CLI, agent profile, MCP, Telegram, asset
resolution을 모두 연결한다.

위험:

- 설정 변경이 CLI, daemon, pipeline, MCP, Telegram까지 넓게 번질 수 있다.
- 테스트는 많지만, 새 옵션 추가 시 어느 계층의 계약을 깨는지 파악하기
  어렵다.
- `AppConfig`가 "설정 값"과 "런타임 해석 서비스" 역할을 동시에 가진다.

권장 조치:

- `AppConfig`는 불변 설정 모델에 가깝게 유지한다.
- profile/MCP/guidance/path resolution은 별도 resolver로 분리한다.
- 새 config option은 소유 resolver와 테스트 파일을 같이 정하도록 한다.

### 2. `.dev` 상태 모델은 강하지만 동기화 계층이 여전히 복잡하다

`StateRepository`는 graphify에서 235개 edge를 가진 핵심 node이고,
`backend/dormammu/state/repository.py`는 1,613줄이다. 이미
`OperatorSync`, `SessionManager`, `persistence`로 일부 분리되어 있지만,
repository가 아직 bootstrap, session routing, root mirror, prompt
persistence, run/stage result 기록을 모두 조정한다.

위험:

- root `.dev` mirror와 session-local state가 어긋날 때 supervisor와
  daemon이 별도 보정 로직을 가져야 한다.
- stale PLAN/TASKS sync를 허용하는 특수 경로가 늘어나면 실제 실패를
  완료로 오판할 수 있다.
- 상태 복구 기능을 고치려면 여러 Markdown/JSON projection 규칙을 동시에
  이해해야 한다.

권장 조치:

- `StateRepository`를 facade로 축소하고 write-path별 service를 분리한다.
- root mirror는 "derived projection"으로 명확히 선언하고 단방향/양방향
  sync 조건을 문서화한다.
- supervisor가 Markdown mirror보다 structured `StageResult`와 lifecycle
  event를 우선하도록 단계적으로 이동한다.

### 3. 실행 runner들이 너무 크고 서로 강하게 연결되어 있다

파일 크기 기준 주요 실행 모듈은 다음과 같다.

- `backend/dormammu/daemon/pipeline_runner.py`: 1,838 lines
- `backend/dormammu/loop_runner.py`: 1,641 lines
- `backend/dormammu/daemon/runner.py`: 976 lines
- `backend/dormammu/supervisor.py`: 1,024 lines

이 모듈들은 모두 agent 실행, stage 결과, retry, artifact, lifecycle,
operator state를 공유한다. graphify에서도 `LoopRunner`,
`PipelineRunner`, `DaemonRunner`가 별도 커뮤니티를 잇는 bridge로 나타난다.

위험:

- pipeline, loop, daemon 중 하나의 완료 semantics를 바꾸면 다른 경로의
  결과 발행이 흔들릴 수 있다.
- retry/re-entry/manual_review_needed 처리가 runner별로 조금씩 달라질 수
  있다.
- 테스트 실패가 발생하면 원인이 adapter, supervisor, state sync,
  daemon publication 중 어디인지 빠르게 좁히기 어렵다.

권장 조치:

- 공통 stage execution service를 더 작게 추출한다.
- retry/re-entry/manual review 판단을 runner 내부가 아니라 result model
  helper로 모은다.
- `PipelineRunner`는 orchestration만 남기고 prompt building, stage call,
  artifact persistence를 더 작은 객체로 옮긴다.

### 4. 완료 판정이 아직 structured result와 Markdown heuristic 사이에 걸쳐 있다

`docs/result-model.md`와 `backend/dormammu/results.py`는 좋은 방향이다.
`StageResult`가 operational status와 domain verdict를 분리한다. 하지만
`Supervisor`는 여전히 `WORKFLOWS.md`, `PLAN.md`, 질문 문장 regex, git
diff, task sync를 조합해 승인 여부를 판단한다.

위험:

- 실제 agent가 완료했지만 Markdown projection이 늦으면 false failure가
  발생한다.
- 반대로 Markdown이 먼저 체크되면 실제 산출물이 부족해도 승인될 수 있다.
- 한국어/영어 질문 탐지 같은 텍스트 heuristic이 runtime correctness에
  영향을 준다.

권장 조치:

- `StageResult`와 lifecycle event를 primary truth로 승격한다.
- Markdown은 operator display/projection으로 취급한다.
- supervisor heuristic은 fallback evidence로만 남기고, 어느 heuristic이
  verdict에 영향을 줬는지 structured metadata에 기록한다.

### 5. role taxonomy가 아직 두 층으로 보인다

현재 문서와 코드에는 `refiner`, `planner`, `designer`, `developer`,
`tester`, `reviewer`, `committer`, `evaluator`가 중심이다. 동시에 goals와
autonomous 경로에는 `analyzer`가 남아 있고, 일부 가이드에는 goals
prelude와 main pipeline이 별도 개념처럼 설명된다.

위험:

- 운영자는 "planner"가 pipeline planner인지 goals prelude planner인지
  헷갈릴 수 있다.
- role-specific CLI 설정과 skill guidance가 서로 다른 이름 체계를
  가질 수 있다.
- goals automation이 main workflow와 다른 제품 계약처럼 보인다.

권장 조치:

- role taxonomy 표를 하나로 만들고 `analyzer`는 goals/autonomous-only
  role임을 명확히 고정한다.
- docs, config examples, runtime profiles에서 같은 표를 참조하게 한다.
- `architect` 같은 이전 명칭은 compatibility alias인지 제거 대상인지
  분명히 정한다.

### 6. CLI와 operator control surface가 넓다

`cli.py`, `_cli_handlers.py`, `interactive_shell.py`, daemon, Telegram,
goals scheduler가 모두 operator entrypoint다. graphify는 CLI handlers,
Telegram control plane, goals scheduler, daemon runner를 별도 커뮤니티로
분리했지만, 이들은 `AppConfig`, `StateRepository`, `LoopRunner`를 통해
강하게 연결된다.

위험:

- 동일 기능이 shell, CLI, daemon, Telegram에서 다르게 보일 수 있다.
- command handler 변경이 state/session/runtime 변경을 동반하기 쉽다.
- 사용자-facing 문서와 실제 command behavior가 drift될 가능성이 높다.

권장 조치:

- command handler를 domain별로 나눈다: run/session/config/daemon/telegram.
- 각 entrypoint는 같은 application service를 호출하게 한다.
- 사용자 문서의 command matrix를 테스트 가능한 fixture로 전환한다.

### 7. graphify 결과 자체에도 noise가 있다

graphify god node 1위는 `path()`이고, suggested questions에도 `str` 같은
primitive inferred edge 검증 질문이 나타났다. 이는 Python AST 추출에서
일반 함수/타입 이름이 지나치게 강한 bridge로 잡힌 결과다.

위험:

- graph report만 보면 실제 아키텍처 문제가 아닌 primitive utility가
  핵심 설계축처럼 보일 수 있다.
- inferred edge가 많은 primitive node는 분석 우선순위를 흐린다.

권장 조치:

- graphify 후처리에서 `str`, `path()`, `.to_dict()`, `from_dict()` 같은
  generic symbol을 낮은 우선순위로 필터링한다.
- 프로젝트 분석에는 graph 중심성만 쓰지 말고 LOC, 테스트, runtime
  ownership을 같이 보정한다.

Phase 7 이후에는 [Analysis Tooling Runbook](analysis-tooling.md)을 따라
`scripts/graphify_review.py`로 graphify 결과를 후처리한다. 후처리 결과는
generic AST symbol을 별도 demoted 섹션으로 분리하고, architecture review
후보에는 degree, LOC, test mentions, runtime area를 함께 표시한다.

## 우선순위

1. Result-driven completion으로 이동한다.
   `StageResult`/lifecycle event를 primary truth로 만들고 supervisor의
   Markdown heuristic 의존을 낮춘다.

2. `AppConfig`와 state repository의 책임을 더 분리한다.
   설정 resolution과 state projection이 현재 가장 큰 변경 증폭 지점이다.

3. Runner 계층을 작게 만든다.
   `PipelineRunner`, `LoopRunner`, `DaemonRunner`가 같은 stage execution,
   retry, artifact, verdict helper를 쓰도록 수렴시킨다.

4. Role taxonomy와 goals 경로를 정리한다.
   goals/autonomous-only role과 main pipeline role을 명확히 구분한다.

5. 분석 tooling noise를 줄인다.
   graphify의 generic AST symbol을 필터링해 다음 분석의 신호대잡음비를
   높인다.

## 검증 결과

실행한 명령:

```text
scripts/verify-agents-sync.sh
pytest -q tests/test_packaging_sync.py tests/test_results.py tests/test_supervisor.py
```

결과:

```text
OK: agents/ and backend/dormammu/assets/agents/ are in sync.
34 passed in 2.50s
```

전체 테스트는 이번 분석 중 실행하지 않았다. 현재 문서는 구조 분석과
선별 검증 결과를 기준으로 한다.
