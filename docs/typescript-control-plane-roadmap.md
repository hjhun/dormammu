# TypeScript Control Plane 전환 로드맵

## 목적

`dormammu`의 현재 기능은 Python 런타임, FastAPI 웹 서버, React TypeScript
프론트엔드, Python Telegram bot, 파일 기반 daemon queue가 나누어 갖고 있다.
목표는 프롬프트 또는 목표를 전달하면 개발, 테스트, 리뷰, 결과 확인까지 자동화하고,
그 과정을 웹앱과 Telegram에서 동일한 방식으로 제어할 수 있도록 기능을
TypeScript 중심으로 통합하는 것이다.

이 문서는 기존 코드를 분석한 문제점과 보완 방향을 함께 제시한다. 권장 전략은
대규모 일괄 재작성보다, 먼저 TypeScript control plane을 세우고 Python 실행
엔진을 점진적으로 축소하는 단계적 전환이다.

## 현재 구조 요약

### 기존 목표와 문서 상태

- 저장소 지침은 `.dev/PROJECT.md`와 `.dev/ROADMAP.md`를 주요 목표 문서로
  지정하지만, 현재 저장소의 `.dev/` 디렉터리에는 해당 파일이 없다.
- 실제로 확인 가능한 제품 목표는 README와 `docs/GUIDE.md`에 더 잘 정리되어
  있다. 핵심 목표는 supervised retry loop, resumable execution, role-based
  pipeline, goals automation, web terminal, Telegram 연동이다.
- 따라서 이 전환 계획은 부재한 `.dev` 목표 파일보다 README, Guide, 현재 코드,
  테스트 기준선을 우선 근거로 삼는다.
- Phase 0에서 `.dev` 목표 문서를 복구할지, shadow workspace export만 유지할지
  명확히 결정해야 한다.

### Python 런타임

- CLI 진입점은 `backend/dormammu/cli.py`에 있고 `run`, `run-once`,
  `daemonize`, `web`, `terminal`, `shell` 서브커맨드를 등록한다.
- 외부 agent CLI 실행은 `CliAdapter`가 담당한다.
- 반복 실행과 검증은 `LoopRunner`, 역할 기반 흐름은 `PipelineRunner`가 담당한다.
- 목표 자동화는 `GoalsScheduler`가 goals 디렉터리를 주기적으로 스캔하고,
  analyzer, planner, designer agent를 호출해 daemon prompt를 생성한다.
- 상태는 기본적으로 저장소 `.dev/`가 아니라
  `~/.dormammu/workspace/<repo-relative-path>/.dev` 아래 shadow workspace에
  생성된다.

### 웹 제어면

- `backend/dormammu/web/app.py`는 FastAPI 앱 하나에 인증, 설정, daemon,
  goals, terminal, Telegram session API를 모두 등록한다.
- 웹 터미널은 `tmux` 기반이며 WebSocket으로 pane snapshot을 전송한다.
- 프론트엔드는 `frontend/`의 Vite + React + TypeScript 앱이다.
- `frontend/src/main.tsx` 하나에 대부분의 화면 상태와 컴포넌트가 몰려 있다.
- API 타입은 `frontend/src/api.ts`에 수동으로 선언되어 있고 서버 계약과 자동
  동기화되지 않는다.

### Telegram 제어면

- `backend/dormammu/telegram/bot.py`는 Python `python-telegram-bot` 기반이다.
- `/run`, `/ask`, `/run_fast`, `/queue`, `/tail`, `/result`, `/sessions`,
  `/repo`, `/goals`, `/shutdown` 등을 처리한다.
- Telegram 명령은 daemon queue, goals 파일, conversation session store를 직접
  건드리거나 Python service를 호출한다.

### Agent guidance 번들

- 이전 구조에는 `agents/` 아래 runtime rules, skills, workflows가 있고,
  `.agents/skills/*-workflows` 아래에는 프로젝트 전용 workflow skill이 따로 있었다.
- 두 위치가 동시에 존재하면서 어떤 파일이 설치/실행 시 authoritative한지
  불명확했던 문제가 있었다.
- 새 방향은 기존 `agents/`와 `.agents/skills/*-workflows`를 제거하고,
  `.agents` 아래에 Codex, Claude, agy(Antigravity), Cline이 공통으로 참조할 수
  있는 역할 기반 skill/workflow 번들을 두는 것이다.
- 이 번들은 `dormammu` 설치 시 함께 설치되어야 하며, 각 agent CLI가 읽을 수
  있는 adapter 파일도 같이 생성해야 한다.

## 심층 분석: 기존 코드의 주요 문제

### 1. 제품 범위가 문서와 코드에서 충돌한다

저장소 지침은 CLI-only를 현재 제품 범위로 설명하지만, README와 구현은 이미
웹 터미널, 설정 콘솔, Telegram session continuation, goals editor를 제품 표면으로
다룬다. 이 불일치는 설계 판단을 어렵게 만든다.

보완 방향:

- `AGENTS.md`, README, `docs/GUIDE.md`에서 제품 표면을 다시 정의한다.
- 새 기준은 "CLI는 실행 백엔드와 로컬 운영 경로, 웹앱과 Telegram은 control
  plane"으로 잡는다.
- CLI-only 문구는 과거 범위로 명시하거나 제거한다.

### 2. Python API 서버가 너무 많은 책임을 가진다

`web/app.py`는 인증, 설정 편집, daemon process 시작/종료, queue 파일 관리,
goals 파일 관리, terminal WebSocket, Telegram session continuation까지 한 파일에
묶고 있다. TypeScript 전환 시 이 구조를 그대로 옮기면 TS 코드도 같은 문제를
반복한다.

보완 방향:

- API를 `auth`, `settings`, `runs`, `goals`, `artifacts`, `terminal`,
  `telegram` 모듈로 나눈다.
- 모든 제어 동작은 service 계층을 통과하게 하고, HTTP handler는 검증과 응답
  매핑만 담당한다.
- OpenAPI 또는 shared schema에서 TypeScript client/server 타입을 생성한다.

### 3. 웹앱은 TypeScript지만 control model이 없다

현재 React 앱은 queue, goals, terminal, Telegram, settings 화면을 제공하지만,
중심 개념은 "파일 목록"과 "tmux 터미널"에 가깝다. 사용자가 원하는 자동화
흐름인 "목표 -> 계획 -> 개발 -> 테스트 -> 리뷰 -> 결과"가 하나의 작업 단위로
표현되지 않는다.

보완 방향:

- UI의 중심 모델을 `Goal`, `Run`, `Stage`, `Artifact`, `Event`로 재정의한다.
- queue 파일은 내부 구현으로 숨기고, 사용자는 Run timeline과 stage verdict를
  보게 한다.
- terminal은 보조 디버그 도구로 유지하고, 기본 제어는 typed API로 제공한다.

### 4. Telegram과 웹이 같은 기능을 다른 경로로 제어한다

웹은 FastAPI endpoint를 통해 queue/goals를 조작하고, Telegram bot은 Python
runner와 service를 직접 호출한다. 두 제어면이 같은 추상화 위에 있지 않아
기능 추가 시 중복과 불일치가 생긴다.

현재 관찰된 정합성 문제:

- CLI parser에는 `web`, `terminal` 서브커맨드가 있지만 operator command matrix에
  빠져 있어 전체 테스트가 실패한다.
- Telegram help와 handler에는 `/ask`, `/run_fast`가 있지만 command matrix의
  Telegram 표면에는 빠져 있다. 현재 테스트가 모든 명령을 다 검증하지 않아
  누락이 숨어 있다.

보완 방향:

- TypeScript control API를 유일한 제어 진입점으로 만들고 웹과 Telegram bot은
  같은 API client를 사용한다.
- operator command matrix를 API route, CLI command, Telegram command에서
  자동 생성하거나 계약 테스트로 검증한다.

### 5. 파일 시스템 queue는 단순하지만 상태 모델이 약하다

현재 daemon은 `prompt_path`와 `result_path`의 Markdown 파일을 통해 작업을
처리한다. 이 방식은 사람이 읽기 쉽지만 다음 문제가 있다.

- 상태 전이가 파일명, Markdown 본문, heartbeat 파일에 흩어진다.
- 중복 실행, 취소, 재시도, stage-level progress를 typed query로 조회하기 어렵다.
- 웹과 Telegram이 같은 상태를 보려면 파일을 다시 해석해야 한다.
- `.dev` shadow workspace와 저장소 `.dev`의 차이가 운영자에게 혼란을 준다.

보완 방향:

- TypeScript control plane에서 SQLite 기반 event store를 도입한다.
- Markdown 파일은 호환성과 사람이 읽는 export로 유지한다.
- 작업 상태 전이는 `queued`, `running`, `waiting_for_review`, `blocked`,
  `completed`, `failed`, `cancelled` 같은 명시적 enum으로 관리한다.

### 6. 보안 모델을 정리해야 한다

현재 웹은 password/token을 받아 `Authorization: Bearer`로 보내지만, 프론트엔드는
비밀번호를 `localStorage`에 저장한다. raw config 편집 API도 있어 secret masking과
권한 분리가 중요하다.

보완 방향:

- 외부 bind 시 password-only 사용을 금지하고 session cookie 또는 short-lived
  token으로 전환한다.
- `localStorage`에 비밀번호 원문을 저장하지 않는다.
- raw config 편집은 관리자 권한으로 분리하고 감사 로그를 남긴다.
- Telegram bot token, web password hash, agent CLI credentials는 secret store
  추상화로 분리한다.

### 7. 테스트는 넓지만 현재 전체 기준선이 깨져 있다

최근 전체 테스트 기준선은 다음 두 실패를 보인다.

- `cli.py` 라인 수가 639줄로 `< 600` 제한을 초과한다.
- parser에는 `web`, `terminal` 명령이 있으나 operator command matrix에는 없다.

빠른 기준선 `scripts/verify-baseline.sh quick`은 통과하지만, 전체 suite가 깨진
상태에서 대규모 전환을 시작하면 회귀 분리가 어렵다.

보완 방향:

- 전환 전 Phase 0에서 전체 테스트를 녹색으로 만든다.
- `web`, `terminal`, Telegram `/ask`, `/run_fast`까지 command matrix 계약을
  강화한다.
- `cli.py` parser builder를 하위 모듈로 분리한다.

### 8. 생성 산출물이 분석과 검색을 오염시킨다

`backend/dormammu/web/static/assets/*.js`와 로컬 `graphify-out/` 같은 생성물이
repo-wide 검색에 섞이면 실제 소스 분석이 부정확해진다.

보완 방향:

- 분석/리뷰 스크립트에서 `web/static/assets`, `frontend/dist`, `graphify-out`,
  `.venv`, cache 디렉터리를 기본 제외한다.
- 패키징 산출물은 sync 검증 대상이지만 일반 코드 분석 대상에서는 제외한다.

### 9. 역할 skill과 workflow가 너무 세분화되어 루프 제어가 흐려진다

현재 bundle은 `refiner`, `planner`, `developer`, `tester`, `reviewer`,
`committer`, `evaluator`와 별도 workflow 문서로 나뉘어 있다. 여기에
`.agents/skills/*-workflows`까지 더해지면서 역할, workflow, runtime rule의
경계가 중복된다.

보완 방향:

- `.agents`를 단일 배포 번들로 삼고 역할 skill을 명확히 재작성한다.
- 루프 제어는 `coordinator`와 `supervisor`로 분리한다.
- `tester`를 독립 역할로 두기보다 `reviewer`의 실행 검증 책임에 포함하되,
  unit, smoke, e2e test gate는 workflow contract에서 강제한다.
- 단순 작업은 analyzer/refiner/planner 전체를 강제하지 않고 light path로 처리한다.

## 목표 아키텍처

### 핵심 원칙

1. TypeScript control plane이 모든 사용자 제어면의 중심이 된다.
2. 웹앱과 Telegram은 같은 API와 event stream을 사용한다.
3. Python 런타임은 초기에는 worker로 유지하고, 검증된 단위부터 TypeScript로
   포팅한다.
4. Markdown `.dev` 상태는 유지하되, 내부 진실은 typed state store와 event log로
   이동한다.
5. 사용자는 "파일을 큐에 넣었다"가 아니라 "목표 실행을 만들었다"는 모델을
   보게 한다.

### 제안 패키지 구조

```text
apps/
  control-api/          # TypeScript HTTP/WebSocket API
  web/                  # React web app
  telegram-bot/         # TypeScript Telegram bot
packages/
  contracts/            # Zod/JSON Schema/OpenAPI contracts
  state/                # SQLite repositories and migrations
  runner-client/        # Python worker 또는 TS runner 호출 client
  agent-runtime/        # 장기적으로 TS CliAdapter/Pipeline/Supervisor
  agent-guidance/       # .agents 역할 skill, workflow, adapter generator
  ui/                   # 공용 UI 컴포넌트
python/
  dormammu-legacy/      # 전환 기간 Python runtime compatibility layer
.agents/
  README.md
  workflows/
    autonomous-development-loop.md
    simple-task.md
    recovery-loop.md
  roles/
    analyzer/SKILL.md
    refiner/SKILL.md
    planner/SKILL.md
    architect/SKILL.md
    developer/SKILL.md
    reviewer/SKILL.md
    committer/SKILL.md
    coordinator/SKILL.md
    supervisor/SKILL.md
  adapters/
    codex/AGENTS.md
    claude/CLAUDE.md
    agy/AGENTS.md
    cline/AGENTS.md
  templates/
    GOAL.md
    REQUIREMENTS.md
    ROADMAP.md
    DASHBOARD.md
    TASKS.md
    DECISIONS.md
    TEST_PLAN.md
    TEST_REPORT.md
    REVIEW.md
```

초기에는 기존 `backend/dormammu`를 유지하고, TS 앱은 기존 Python CLI/API를
호출하는 facade로 시작한다. 이후 `agent-runtime`으로 기능을 단계별 이관한다.

### 주요 도메인 모델

```text
Goal
  id, title, body, source(web|telegram|cli|scheduler), schedule, status

Run
  id, goal_id, prompt, request_class, status, created_by, created_at, updated_at

Stage
  id, run_id, role, status, verdict, attempt, started_at, completed_at

Artifact
  id, run_id, stage_id, kind(prompt|stdout|stderr|report|diff|commit), uri, content_type

Event
  id, run_id, type, payload, created_at

AgentProfile
  id, role, cli, model, permission_policy, enabled_tools

AgentGuidanceBundle
  id, version, roles, workflows, adapters, install_targets
```

### 새 `.agents` 역할 정의

새 역할은 사용자가 제안한 이름을 기준으로 하되, 자동 개발 루프에서 책임이
겹치지 않도록 다음 계약으로 정의한다.

| Role | 책임 | 주요 산출물 |
|------|------|-------------|
| `analyzer` | 원문 목표, 기존 코드, 운영 제약을 분석하고 문제 영역과 불확실성을 정리한다. | `ANALYSIS.md` |
| `refiner` | 분석 내용을 바탕으로 기능 요구사항, 비기능 요구사항, 테스트 케이스, 수용 기준을 재작성한다. | `REQUIREMENTS.md` |
| `planner` | 재작성된 요구사항을 개발 가능한 단계로 분해하고 반복 실행 계획을 작성한다. | `ROADMAP.md`, `DASHBOARD.md`, `TASKS.md` |
| `architect` | SW/HW 스펙과 요구사항을 분석해 구조, 인터페이스, 데이터 흐름, 배포 제약을 설계한다. | `ARCHITECTURE.md`, `DECISIONS.md` |
| `developer` | 20년 이상 경력의 senior engineer 기준으로 품질, 메모리, 성능, 유지보수성을 고려해 구현한다. | 코드 변경, `DEV_NOTES.md` |
| `reviewer` | 요구사항 충족 여부, 숨은 side effect, regression, unit/smoke/e2e 결과를 검토한다. | `REVIEW.md`, `TEST_REPORT.md` |
| `committer` | 불필요한 산출물을 제거하고 필요한 변경만 stage/commit한다. commit message는 제목 80자 이하, 제목과 본문 사이 빈 줄을 둔다. | git commit |
| `coordinator` | 각 단계를 모니터링하고 필요한 경우 이전 단계로 되돌려 재수행을 요청한다. | `COORDINATION.md` |
| `supervisor` | coordinator 보고와 산출물을 보고 목표 달성 여부를 판단해 루프 중단/재개를 결정한다. | `SUPERVISOR_REPORT.md` |

`comitter` 오타는 사용자 입력 호환 alias로 지원하되, 표준 역할명은
`committer`로 고정한다.

### 권장 Markdown 상태 구조

사용자가 제안한 `ROADMAP.md`, `DASHBOARD.md`, `TASK.md`는 유지하되, 더 명확한
상태 관리를 위해 다음 파일명을 권장한다.

```text
.dev/
  GOAL.md              # 원문 목표와 작업 범위
  ANALYSIS.md          # analyzer 산출물
  REQUIREMENTS.md      # refiner 산출물
  ROADMAP.md           # planner의 phase roadmap
  DASHBOARD.md         # 현재 루프 상태, active phase, next action
  TASKS.md             # 실행 가능한 작업 체크리스트
  ARCHITECTURE.md      # architect 산출물
  DECISIONS.md         # 주요 결정과 trade-off
  DEV_NOTES.md         # developer 작업 메모
  TEST_PLAN.md         # unit/smoke/e2e 전략
  TEST_REPORT.md       # 실행된 테스트 결과
  REVIEW.md            # reviewer 검토 결과
  COORDINATION.md      # coordinator 라우팅/재시도 기록
  SUPERVISOR_REPORT.md # supervisor 최종 판단
  workflow_state.json  # machine-readable truth
```

기본 파일명은 복수형 `TASKS.md`를 사용한다. `TASK.md`는 migration alias로
읽을 수 있게 한다.

### 루프 정책

- 기본 경로는 개발 자동화 루프다:
  `analyzer -> refiner -> planner -> architect -> developer -> reviewer ->
  coordinator -> supervisor`.
- supervisor가 목표 달성을 승인하면 루프를 중단한다.
- reviewer가 테스트 실패, 요구사항 불충족, side effect를 찾으면 coordinator가
  `developer`, `architect`, `planner`, `refiner` 중 필요한 단계로 되돌린다.
- 단순 작업은 simple-task workflow로 축약한다. 예를 들어 오탈자, 한 파일 설정,
  작은 문서 변경은 `analyzer/refiner/planner/architect`를 생략하고
  `developer -> reviewer -> supervisor` 또는 즉시 처리 경로를 사용할 수 있다.
- 어떤 경로를 선택하든 unit, smoke, e2e 중 해당 변경에 필요한 테스트 gate를
  명시해야 한다. e2e가 불필요한 단순 작업은 생략 사유를 기록한다.

### Control API 초안

```text
POST   /api/runs
GET    /api/runs
GET    /api/runs/:id
POST   /api/runs/:id/cancel
POST   /api/runs/:id/retry
GET    /api/runs/:id/events
WS     /api/runs/:id/stream

POST   /api/goals
GET    /api/goals
GET    /api/goals/:id
PATCH  /api/goals/:id
DELETE /api/goals/:id

GET    /api/artifacts/:id
GET    /api/settings
PATCH  /api/settings

POST   /api/terminal/sessions
WS     /api/terminal/sessions/:id

GET    /api/telegram/sessions
POST   /api/telegram/sessions/:id/messages
```

기존 `/api/daemon/*`는 호환 API로 남기되, 새 웹앱과 Telegram은 `/api/runs`,
`/api/goals`, `/api/events`를 우선 사용한다.

## 수정 로드맵

### Phase 0. 기준선 복구와 범위 정렬

목표: TypeScript 전환 전 현재 저장소를 신뢰 가능한 상태로 만든다.

작업:

- `operator_commands.py`에 `web`, `terminal`, Telegram `/ask`, `/run_fast`를
  등록한다.
- CLI parser builder를 분리해 `cli.py` 라인 수 정책 테스트를 통과시킨다.
- `AGENTS.md`, README, `docs/GUIDE.md`의 제품 표면 설명을 일치시킨다.
- `state/models.py`의 phase label을 현재 로드맵 명칭과 동기화한다.
- 분석 스크립트와 문서에 생성 산출물 제외 규칙을 명시한다.
- 기존 `agents/`와 `.agents/skills/*-workflows`의 역할, 사용처, 패키징 경로를
  inventory로 정리한다.

완료 신호:

- `python3 -m pytest -q` 전체 통과.
- `scripts/verify-baseline.sh quick` 통과.
- 문서상 제품 표면이 CLI, web, Telegram control plane으로 일관된다.

### Phase 1. `.agents` 역할 번들 재설계

목표: Codex, Claude, agy(Antigravity), Cline이 공통으로 참조할 역할 skill과
workflow를 `.agents` 아래 단일 구조로 재작성한다.

작업:

- 기존 `agents/`와 `.agents/skills/*-workflows`를 제거 대상으로 확정한다.
- `.agents/roles/<role>/SKILL.md`에 analyzer, refiner, planner, architect,
  developer, reviewer, committer, coordinator, supervisor를 작성한다.
- `.agents/workflows/autonomous-development-loop.md`에 기본 자동 개발 루프를
  정의한다.
- `.agents/workflows/simple-task.md`에 단순 작업 축약 경로를 정의한다.
- `.agents/workflows/recovery-loop.md`에 실패, 중단, 재개, 재시도 정책을 정의한다.
- `.agents/templates/`에 `.dev` Markdown 상태 파일 템플릿을 둔다.
- `.agents/adapters/`에 Codex, Claude, agy, Cline이 읽을 adapter 문서를 둔다.
- install script와 package data가 `.agents` 번들을 설치하도록 바꾼다.
- 기존 `agents/` 기반 테스트를 `.agents` 기준으로 전환한다.

완료 신호:

- 새 설치에서 `.agents` 번들이 함께 설치된다.
- Codex, Claude, agy, Cline 각각이 같은 역할 계약을 참조할 수 있다.
- 기존 `agents/`와 `.agents/skills/*-workflows` 의존이 제거된다.
- 단순 작업과 기본 개발 루프가 모두 문서와 테스트로 검증된다.

### Phase 2. 계약과 상태 모델 정의

목표: Python과 TypeScript가 공유할 실행 계약을 먼저 고정한다.

작업:

- `packages/contracts`에 `Goal`, `Run`, `Stage`, `Artifact`, `Event`,
  `AgentProfile`, `AgentGuidanceBundle`, `Settings` schema를 정의한다.
- 기존 Python result, `.dev/session.json`, `workflow_state.json`, result report를
  새 schema로 projection하는 compatibility mapper를 작성한다.
- OpenAPI를 생성하고 프론트엔드 API client를 수동 타입에서 generated client로
  전환한다.
- event type taxonomy를 정의한다.
- `.agents` role/workflow bundle의 manifest schema를 정의한다.

완료 신호:

- 기존 daemon result를 새 `Run` view로 조회할 수 있다.
- 웹앱 타입이 서버 schema에서 생성된다.
- Python과 TS 간 계약 테스트가 생긴다.
- `.agents` manifest를 검증하는 contract test가 생긴다.

### Phase 3. TypeScript control API 도입

목표: 웹과 Telegram이 호출할 TypeScript 제어 서버를 만든다.

작업:

- `apps/control-api`를 만든다.
- 초기에는 기존 Python CLI 또는 FastAPI endpoint를 호출하는 adapter 방식으로
  구현한다.
- SQLite event store와 migration을 도입한다.
- `/api/runs`, `/api/goals`, `/api/events`를 구현한다.
- daemon 파일 queue와 새 Run API를 양방향으로 동기화하는 bridge를 만든다.

완료 신호:

- 웹에서 새 Run API로 prompt를 생성하면 기존 Python daemon이 실행할 수 있다.
- 기존 queue 파일이 생겨도 Run 목록에서 보인다.
- Run event stream이 웹에서 실시간으로 표시된다.

### Phase 4. 웹앱을 작업 중심 UI로 재구성

목표: 사용자가 목표 실행과 검증 흐름을 웹에서 직접 제어한다.

작업:

- `frontend/src/main.tsx`를 view별 모듈로 분리한다.
- Queue 화면을 Run dashboard로 바꾼다.
- Goals 화면에 목표 작성, 예약, 즉시 실행, 실행 이력 연결을 추가한다.
- Run detail 화면에 stage timeline, verdict, artifacts, retry/cancel controls를
  표시한다.
- Settings 화면은 raw JSON 중심에서 typed form 중심으로 재구성한다.
- Terminal 화면은 유지하되 기본 진입점에서 보조 도구로 낮춘다.

완료 신호:

- 웹 첫 화면에서 목표를 입력하고 실행, 테스트, 리뷰 결과까지 추적할 수 있다.
- 파일명/경로를 몰라도 Run 상태를 이해할 수 있다.
- Playwright 또는 equivalent e2e smoke test가 생긴다.

### Phase 5. Telegram bot을 TypeScript control API client로 전환

목표: Telegram이 Python 내부 객체가 아니라 동일한 control API를 사용하게 한다.

작업:

- `apps/telegram-bot`을 만든다.
- `/run`, `/ask`, `/status`, `/queue`, `/goals`, `/tail`, `/result`,
  `/sessions`, `/repo`, `/shutdown`을 control API 호출로 구현한다.
- Telegram conversation state를 SQLite 또는 shared state repository로 옮긴다.
- inline keyboard callback도 command matrix에서 생성하거나 검증한다.
- 기존 Python Telegram bot은 호환 모드로 유지하고 새 bot과 기능 parity를 검증한다.

완료 신호:

- Telegram과 웹에서 같은 Run id를 보고 제어할 수 있다.
- Telegram `/run`으로 만든 작업이 웹 Run dashboard에 즉시 나타난다.
- Python Telegram bot을 끄고 TS bot만으로 기본 운영이 가능하다.

### Phase 6. Goals scheduler와 자동화 정책을 TypeScript로 이전

목표: 목표 파일 감시와 목표 promotion을 typed scheduler로 바꾼다.

작업:

- goals source를 파일 디렉터리와 DB row 둘 다 지원한다.
- analyzer, refiner, planner, architect prelude를 Run stage로 모델링한다.
- interval 기반 scheduler와 수동 "run now" 액션을 control API에 추가한다.
- goal source tag 주석 의존을 `goal_id` foreign key로 대체한다.
- 기존 Markdown goal 파일 import/export를 제공한다.
- scheduler가 `.agents/workflows/autonomous-development-loop.md`를 기본 루프로
  사용하게 한다.

완료 신호:

- 웹/Telegram에서 goal을 추가하면 scheduler가 Run을 생성한다.
- prelude 산출물이 Run artifacts로 보인다.
- 기존 `daemonize.json` goals 설정을 migration할 수 있다.

### Phase 7. Agent runtime을 TypeScript로 단계적 포팅

목표: Python 의존을 줄이고 핵심 실행 루프를 TypeScript로 옮긴다.

우선순위:

1. command builder와 CLI capability detection
2. `CliAdapter`의 subprocess 실행, stdout/stderr artifact capture, fallback CLI
3. request intake classifier
4. supervisor verdict resolver
5. LoopRunner retry/continuation
6. PipelineRunner role orchestration과 `.agents` role resolver
7. committer/evaluator integration

작업 원칙:

- Python과 TypeScript runner를 같은 contract test suite로 검증한다.
- 각 기능은 dual-run 또는 golden fixture로 parity를 확인한 뒤 TS를 기본값으로
  바꾼다.
- Python runner는 `legacy-python-runner` adapter로 남겨 rollback 가능하게 한다.

완료 신호:

- 새 Run은 기본적으로 TS runner에서 실행된다.
- Python runner 없이 `run`, `run-once`, goals automation 핵심 흐름이 동작한다.
- 기존 Python tests에 대응하는 TS unit/integration tests가 있다.

### Phase 8. 배포, 패키징, 마이그레이션 정리

목표: 사용자가 TS 통합 버전을 설치하고 운영할 수 있게 한다.

작업:

- Node.js runtime 요구사항과 install script를 갱신한다.
- Python legacy mode 설치 옵션을 분리한다.
- 기존 `~/.dormammu` 상태를 SQLite/event store로 migration하는 도구를 제공한다.
- 릴리스 산출물에 web build와 control API server를 포함한다.
- 릴리스 산출물에 `.agents` role/workflow bundle과 agent별 adapter 문서를 포함한다.
- systemd 또는 pm2 등 장기 실행 운영 예시를 제공한다.

완료 신호:

- 신규 설치자는 TypeScript control plane으로 시작한다.
- 기존 사용자는 상태와 goals를 보존하고 migration할 수 있다.
- release workflow가 TS build, Python legacy package, web static sync,
  `.agents` bundle sync를 모두 검증한다.

## 테스트 전략

### 계약 테스트

- OpenAPI/Zod schema와 Python compatibility mapper round-trip 테스트.
- command matrix와 실제 CLI/Web/Telegram route parity 테스트.
- Markdown result report와 typed Run projection fixture 테스트.
- `.agents` manifest, role skill, workflow 문서 schema 테스트.
- Codex, Claude, agy, Cline adapter 문서가 같은 역할 목록을 참조하는지 검증.

### TypeScript unit 테스트

- command builder
- scheduler
- event store repository
- run state reducer
- Telegram command parser
- settings secret masking
- `.agents` role resolver와 simple-task classifier

### 통합 테스트

- Run 생성 -> Python legacy daemon bridge -> result projection.
- Run 생성 -> TS runner -> stage events -> artifacts.
- Telegram `/run` -> Run dashboard 표시.
- Web goal 생성 -> scheduler promotion -> Run 생성.
- `.agents` autonomous-development-loop -> analyzer/refiner/planner/architect/
  developer/reviewer/coordinator/supervisor 순서 검증.

### 시스템 테스트

- 로컬 web server + Playwright smoke.
- Telegram bot은 Telegram API mock 또는 test adapter로 검증.
- tmux 또는 node-pty terminal smoke는 환경 의존 테스트로 분리.
- 개발 루프 완료 전 unit, smoke, e2e gate가 실행되거나 명시적으로 제외 사유가
  기록되는지 검증.

## 의사결정이 필요한 항목

1. TypeScript 서버 프레임워크: Fastify, Hono, NestJS 중 선택.
   - 권장: Fastify. OpenAPI, WebSocket, plugin 생태계가 충분하고 과하지 않다.
2. 상태 저장소: SQLite, 파일-only, Postgres 중 선택.
   - 권장: SQLite 우선. 로컬-first 제품에 맞고 migration이 단순하다.
3. 터미널 런타임: tmux 유지, node-pty 전환, 둘 다 지원 중 선택.
   - 권장: 둘 다 지원. tmux는 persistence, node-pty는 TS 통합과 배포 단순성이 장점이다.
4. Python 제거 범위: 완전 제거 또는 legacy runner 유지 기간 결정.
   - 권장: 최소 한 릴리스는 legacy runner를 유지한다.
5. Markdown `.dev`의 역할: source of truth 또는 export view 중 선택.
   - 권장: 내부 source of truth는 event store, `.dev`는 operator-facing export.
6. 기존 `agents/` 제거 시점: Phase 1에서 새 `.agents`가 검증되면 제거한다.
   - 적용: runtime rules와 supervised downstream workflow를 `.agents`로 이관한
     뒤 `agents/`와 packaged `assets/agents`를 제거한다.
7. `tester` 독립 역할 유지 여부.
   - 권장: 별도 역할로 노출하지 않고 reviewer의 검증 책임에 포함한다.
     다만 대규모 프로젝트에서는 reviewer가 test executor subtask를 호출할 수
     있게 한다.

## 가장 먼저 해야 할 보완 작업

1. 전체 테스트 실패 2건을 고친다.
2. 제품 범위 문서 충돌을 정리한다.
3. 기존 `agents/`와 `.agents/skills/*-workflows`를 새 `.agents` 역할 번들로
   대체하는 설계를 확정한다.
4. analyzer, refiner, planner, architect, developer, reviewer, committer,
   coordinator, supervisor skill 초안을 작성한다.
5. `web/app.py`와 `frontend/src/main.tsx`의 책임 분리 계획을 별도 설계로 확정한다.
6. `Run` 중심 계약 schema를 작성한다.
7. 기존 daemon queue를 새 Run API로 감싸는 compatibility bridge를 만든다.

이 작업들이 끝나야 TypeScript 전환이 단순한 UI 재작성으로 흐르지 않고,
웹앱, Telegram, Codex, Claude, agy, Cline이 동일한 자동화 control plane과
동일한 `.agents` 역할 계약을 공유하는 방향으로 진행된다.
