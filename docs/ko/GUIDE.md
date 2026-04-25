# DORMAMMU 가이드

`dormammu`는 코딩 에이전트를 위한 CLI 중심 루프 오케스트레이터입니다.
외부 에이전트 CLI를 Supervisor와 재개 가능한 상태 관리, 운영자 가시성 아티팩트로
감싸서 — 에이전트 실행이 반복 가능하고, 검사 가능하며, 어떤 중단 이후에도
안전하게 계속할 수 있도록 만듭니다.

짧은 소개는 [README.md](../../README.md)를 먼저 보세요. 영문 전체 가이드는
[docs/GUIDE.md](../GUIDE.md)에 있습니다.

---

## 목차

- [DORMAMMU가 하는 일](#dormammu가-하는-일)
- [핵심 개념](#핵심-개념)
- [설치](#설치)
- [빠른 시작](#빠른-시작)
- [명령어 레퍼런스](#명령어-레퍼런스)
- [설정 레퍼런스](#설정-레퍼런스)
- [데몬 모드](#데몬-모드)
- [역할 기반 에이전트 파이프라인](#역할-기반-에이전트-파이프라인)
- [Goals 자동화](#goals-자동화)
- [Guidance 파일](#guidance-파일)
- [`.dev` 디렉터리](#dev-디렉터리)
- [세션 관리](#세션-관리)
- [Fallback Agent CLI](#fallback-agent-cli)
- [Working Directory와 CLI Override](#working-directory와-cli-override)
- [대표 운영 흐름](#대표-운영-흐름)
- [저장소 구조](#저장소-구조)

---

---

## DORMAMMU가 하는 일

DORMAMMU 없이 코딩 에이전트를 실행하면:

```
you ──▶ agent CLI ──▶ (잘 됐으면 좋겠다)
```

DORMAMMU와 함께하면:

```
you ──▶ dormammu run ──▶ agent CLI ──▶ supervisor가 검증 ──▶ 완료
                              ▲               │
                              │    실패        ▼
                              └── continuation 맥락 생성 ──┘
```

Supervisor가 확인하는 항목:

- 필요한 파일이 변경되었는가?
- worktree에 변화가 있는가?
- 에이전트가 의미 있는 결과를 만들었는가?

검증 실패 시 DORMAMMU는 continuation 맥락을 생성하고 재시도합니다.
설정된 한도 내에서 Supervisor가 작업을 승인하면 루프가 즉시 종료됩니다.

에이전트가 보고 만들어낸 모든 것은 나중에 검사하거나 재개할 수 있도록
`.dev/`에 기록됩니다.

---

## 핵심 개념

### Supervised 루프

`dormammu run`은 에이전트 호출을 재시도 루프로 감쌉니다. 각 시도 이후
Supervisor가 결과를 평가합니다. 실패 시 이전 출력이 담긴 continuation
프롬프트를 구성해서 다음 시도를 제출합니다.

### 재개 가능한 상태

모든 워크플로우 상태 — 프롬프트, 로그, 세션 메타데이터, 기계 상태 — 는
`.dev/`에 저장됩니다. 프로세스가 중단되더라도 `dormammu resume`으로 처음부터
다시 시작하는 대신 마지막 저장 상태에서 이어갑니다.

### CLI 어댑터

DORMAMMU는 내부 실행 요청 표현을 대상 CLI에 맞는 실제 호출로 변환합니다.
각 알려진 CLI에 대해 프롬프트 방식, 명령 prefix, workdir 플래그, 자동 승인
인수를 처리하는 preset 어댑터가 있습니다.

### 역할 기반 파이프라인

`dormammu.json`에 `agents`가 설정되면 모든 실행 모드(`run`, `run-once`,
`daemonize`)는 각 goal을 다음 파이프라인을 통해 처리합니다:

```
refiner (mandatory) → planner (mandatory) → developer → tester → reviewer → committer
```

**refiner**는 raw goal을 구조화된 `.dev/REQUIREMENTS.md`로 변환하고,
**planner**는 이를 읽어 적응형 `.dev/WORKFLOWS.md` 체크리스트를 생성합니다.
두 단계 모두 필수 런타임 진입 단계이며, 역할별 CLI가 없으면
`active_agent_cli`로 fallback 됩니다.

---

## 인터랙티브 셸

아무 서브커맨드 없이 `dormammu`를 실행하면 기본 인터랙티브 셸이 시작됩니다.
명시적으로 들어가고 싶다면 다음처럼 실행할 수도 있습니다:

```bash
dormammu shell
```

셸은 의도적으로 가볍게 구성됩니다:

- 상단 출력 영역: 로그, 요약, 데몬 상태
- 하단 프롬프트: 자유 텍스트 입력과 슬래시 명령
- 자유 텍스트 입력: 기본적으로 supervised `run` 요청으로 매핑

핵심 셸 명령:

| 명령 | 설명 |
|------|------|
| 자유 텍스트 | supervised `/run` 요청 제출 |
| `/run <prompt>` | supervised 루프를 명시적으로 실행 |
| `/run-once <prompt>` | 단일 bounded 실행 |
| `/resume` | 최근 중단된 실행 재개 |
| `/show-config` | 해석된 설정 출력 |
| `/config get|set|add|remove|unset ...` | 지원되는 설정 키 읽기/변경 |
| `/sessions` | 알려진 세션 목록 출력 |
| `/daemon start|stop|status|logs|enqueue|queue` | 데몬 워커 제어 또는 상태 확인 |
| `/exit` | 셸 종료 |

`daemonize` 자체는 계속 워커 지향 큐 처리기로 남습니다. 인터랙티브 셸은
`/daemon enqueue`, `/daemon logs`, `/daemon status` 같은 명령으로 이 워커를
조작하는 운영자 제어면입니다.
공유 명령 matrix와 서비스 소유 경계는
[Operator Entry Points](../operator-entrypoints.md)에 정리되어 있습니다.

---

## 실행 모드

DORMAMMU에는 네 가지 운영자 진입 방식이 있습니다.

| 모드 | 명령 | 설명 |
|------|------|------|
| 인터랙티브 셸 | `dormammu` 또는 `dormammu shell` | 상단 로그 출력, 하단 입력 프롬프트, 슬래시 명령을 제공하는 기본 터미널 셸 |
| run-once | `dormammu run-once` | 아티팩트를 남기는 단일 bounded 실행 |
| run | `dormammu run` | 검증과 continuation을 포함한 supervised 재시도 루프 |
| daemonize | `dormammu daemonize` | 프롬프트 큐를 감시하는 장기 실행 데몬 |

모든 실행 모드는 먼저 필수 `refine -> plan` 전주를 수행합니다. 그 이후:

- `agents`가 설정되면 전체 `PipelineRunner`로 계속 진행합니다.
- `agents`가 없으면 `run`과 `daemonize`는 단일 에이전트 `LoopRunner`로 진행합니다.
- `agents`가 없으면 `run-once`는 단일 bounded `CliAdapter` 호출로 진행합니다.

---

## 설치

### 빠른 설치 (권장)

```bash
curl -fsSL https://raw.githubusercontent.com/hjhun/dormammu/main/install.sh | bash
```

### 로컬 클론에서 설치

```bash
./scripts/install.sh
```

### 개발용 설치

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

Python `3.10+`이 필요합니다. Ubuntu 설정은 [docs/ko/UBUNTU_PYTHON_310_PLUS.md](UBUNTU_PYTHON_310_PLUS.md)를 참고하세요.

---

## 빠른 시작

### 1. 환경 확인

```bash
dormammu doctor --repo-root . --agent-cli codex
```

Python 버전, 에이전트 CLI 경로, 저장소 쓰기 가능 여부, 워크스페이스 디렉터리
존재 여부를 확인합니다.

### 2. `.dev` 상태 초기화

```bash
dormammu init-state \
  --repo-root . \
  --goal "요청된 저장소 작업을 안전하게 구현한다."
```

다음 파일을 생성하거나 갱신합니다:

- `.dev/DASHBOARD.md`
- `.dev/PLAN.md`
- `.dev/session.json`
- `.dev/workflow_state.json`

또한 설치된 coding-agent CLI를 확인하고 `active_agent_cli`를 우선순위
`codex` › `claude` › `gemini` › `cline` 순으로 사용 가능한 값으로 갱신합니다.

### 3. 어떤 설정 파일이 로드되는지 확인

```bash
dormammu show-config --repo-root .
```

로드된 파일 경로를 포함해 해석된 설정을 JSON으로 출력합니다.

### 4. CLI 어댑터 확인

```bash
dormammu inspect-cli --repo-root . --agent-cli cline
```

프롬프트 방식, preset 매칭 결과, workdir 지원 여부, 승인 관련 힌트를 실제
실행 전에 확인합니다.

### 5. 단일 에이전트 실행

```bash
dormammu run-once \
  --repo-root . \
  --agent-cli codex \
  --prompt "저장소 가이드를 읽고 다음 구현 단계를 요약하세요."
```

`run-once`는 재시도 루프 없이 한 번 실행하고 아티팩트를 남깁니다.

### 6. Supervised 루프 실행

```bash
dormammu run \
  --repo-root . \
  --agent-cli codex \
  --prompt-file PROMPT.md \
  --required-path README.md \
  --require-worktree-changes \
  --max-iterations 50
```

Supervisor가 승인하거나 반복 한도에 도달할 때까지 루프가 실행됩니다.
`--max-iterations`와 `--max-retries`를 모두 지정하지 않으면 기본값은 `50`입니다.

### 7. 나중에 이어서 실행

```bash
dormammu resume --repo-root .
```

저장된 루프 상태와 continuation 맥락을 다시 읽어 복구 흐름을 재시작합니다.

---

## 명령어 레퍼런스

### `dormammu doctor`

환경 진단. 다음을 확인합니다:

- Python 버전 (≥ 3.10)
- 에이전트 CLI 경로 및 사용 가능 여부
- `.agent` 또는 `.agents` 워크스페이스 디렉터리
- 저장소 루트 쓰기 가능 여부

### `dormammu init-state`

`.dev/` 상태를 생성하거나 갱신합니다. 저장소에서 처음 실행하기 전이나
goal 변경 후 상태를 초기화할 때 사용합니다.

### `dormammu show-config`

해석된 런타임 설정과 소스 파일을 출력합니다.

### `dormammu inspect-cli`

해석된 CLI 어댑터 세부 정보를 JSON으로 출력합니다:

- `prompt_mode`: 프롬프트 전달 방식 (positional, flag, stdin)
- `preset_name`: 매칭된 알려진 preset
- `command_prefix`: 프롬프트 앞에 붙는 prefix
- `workdir_flag`: working directory 설정에 사용되는 플래그
- `approval_hints`: 자동 주입되는 승인 관련 플래그

### `dormammu run-once`

에이전트를 한 번 실행합니다. 프롬프트 아티팩트, stdout, stderr, 실행 메타데이터를
저장합니다. 재시도하지 않습니다.

`agents`가 설정되어 있고 `--agent-cli`를 명시적으로 주지 않으면, `run-once`도
필수 `refine -> plan` 전주 뒤에 전체 파이프라인 한 번을 실행합니다.

### `dormammu run`

단일 에이전트 supervised 재시도 루프 또는 전체 파이프라인 한 번을 실행합니다.

주요 옵션:

| 옵션 | 설명 |
|------|------|
| `--prompt` / `--prompt-file` | 인라인 프롬프트 텍스트 또는 프롬프트 파일 경로 |
| `--agent-cli` | 사용할 CLI (설정의 `active_agent_cli`를 덮어씀) |
| `--required-path` | 에이전트 실행 후 존재하거나 변경되어야 하는 파일 |
| `--require-worktree-changes` | worktree 변화가 없으면 검증 실패 |
| `--max-iterations` | 총 시도 한도 (기본값 `50`) |
| `--max-retries` | 재시도 한도 (`--max-iterations` 대체) |
| `--workdir` | 에이전트 프로세스의 작업 디렉터리 |
| `--guidance-file` | 프롬프트에 삽입할 추가 guidance 파일 (반복 가능) |
| `--extra-arg` | 에이전트 CLI에 전달할 추가 플래그 (반복 가능) |
| `--debug` | 저장소 루트에 `DORMAMMU.log` 기록 |

> **참고:** `--agent-cli`를 명시적으로 제공하면 `agents` 설정이 있어도
> 필수 `refine -> plan` 전주는 계속 수행하지만, 그 이후에는 단일 에이전트
> 경로(LoopRunner / CliAdapter)를 사용합니다. 일회성 실행에서 파이프라인을
> 우회할 때 활용합니다.

### `dormammu shell`

기본 인터랙티브 셸을 명시적으로 시작합니다. 아무 인자 없이 `dormammu`를
실행했을 때와 같은 셸입니다.

```bash
dormammu shell --repo-root .
```

### `dormammu resume`

저장된 상태를 불러와 이전 실행을 계속합니다.

### `dormammu daemonize`

프롬프트 디렉터리를 감시하고 파일을 하나씩 Supervised 루프로 처리하는
장기 실행 데몬입니다.

```bash
dormammu daemonize --repo-root .
```

기본값은 `~/.dormammu/daemonize.json`이며, 다른 파일을 쓰려면
`--config daemonize.json`을 지정하면 됩니다. 자세한 설정은
[데몬 모드](#데몬-모드)를 참고하세요.

---

## 설정 레퍼런스

### 런타임 설정 (`dormammu.json`)

다음 순서로 해석됩니다:

1. `DORMAMMU_CONFIG_PATH` 환경 변수
2. `<repo-root>/dormammu.json`
3. `~/.dormammu/config`

전체 예시:

```json
{
  "active_agent_cli": "/home/you/.local/bin/codex",
  "fallback_agent_clis": [
    "claude",
    "gemini"
  ],
  "cli_overrides": {
    "cline": { "extra_args": ["-y", "--timeout", "1200"] }
  },
  "token_exhaustion_patterns": [
    "usage limit", "quota exceeded", "rate limit exceeded"
  ],
  "agents": {
    "refiner":   { "cli": "claude", "model": "claude-sonnet-4-6" },
    "planner":   { "cli": "claude", "model": "claude-sonnet-4-6" },
    "developer": { "cli": "claude", "model": "claude-opus-4-6" },
    "tester":    { "cli": "claude", "model": "claude-sonnet-4-6" },
    "reviewer":  { "cli": "claude", "model": "claude-sonnet-4-6" },
    "committer": { "cli": "claude" }
  }
}
```

`agents`가 설정되면 모든 실행 모드(`run`, `run-once`, `daemonize`)는 역할
기반 파이프라인을 사용합니다. `analyzer`는 goals/autonomous 전용이고,
goals 자동화는 `analyzer -> planner -> designer`를 사용해 큐에 넣을
프롬프트를 강화할 수 있습니다. `refiner`와 `planner`는 필수 런타임
단계로 항상 실행되며 역할별 CLI가 없으면 `active_agent_cli`를 사용합니다.
`designer`는 interactive runtime 단계가 아니며, 생성된 designer 문서가
있을 때 reviewer prompt가 이를 읽을 수 있습니다. `architect`는 지원되는
role alias가 아닙니다.
[역할 기반 에이전트 파이프라인](#역할-기반-에이전트-파이프라인)을 참고하세요.

### 데몬 큐 설정 (`daemonize.json`)

`dormammu.json`과 별개입니다. 데몬이 감시하는 내용과 큐 방식을 제어합니다.

```json
{
  "schema_version": 1,
  "prompt_path": "./queue/prompts",
  "result_path": "./queue/results",
  "watch": {
    "backend": "auto",
    "poll_interval_seconds": 60,
    "settle_seconds": 0
  },
  "queue": {
    "allowed_extensions": [".md", ".txt"],
    "ignore_hidden_files": true
  },
  "goals": {
    "path": "./goals",
    "interval_minutes": 60
  }
}
```

상대 경로는 현재 쉘 작업 디렉터리가 아닌 데몬 설정 파일 위치를 기준으로
해석됩니다.

---

## 데몬 모드

`daemonize`는 DORMAMMU를 장기 실행 큐 워커로 만듭니다. `prompt_path`에 프롬프트
파일을 넣으면 데몬이 이를 감지해 Supervised 루프로 실행하고 결과 리포트를
`result_path`에 씁니다.

```bash
dormammu daemonize --repo-root . --config daemonize.json
```

### 큐 정렬 순서

프롬프트 파일은 처리 전에 결정론적으로 정렬됩니다:

1. 숫자 prefix 파일 — 정수값 기준 (`001_`, `02_`, `10_`)
2. 알파벳 prefix 파일 — 알파벳순 (`A_`, `b-`, `C_`)
3. prefix 없는 파일 — 전체 파일명 기준

### 결과 리포트

`001_feature.md` 프롬프트 파일 처리 후 `001_feature_RESULT.md`를 `result_path`에
씁니다. 리포트에는 다음이 포함됩니다:

- 원본 프롬프트 파일명과 경로
- 시작 및 완료 타임스탬프
- 실행 결과와 단계별 요약
- 관련 `.dev/` 및 로그 아티팩트 경로

### 런타임 설정과 데몬 설정 동시 사용

```bash
DORMAMMU_CONFIG_PATH=./ops/dormammu.prod.json \
  dormammu daemonize --repo-root . --config ./ops/daemonize.prod.json
```

### 예시 설정 파일 선택 기준

| 예시 파일 | 언제 사용하는가 |
|-----------|----------------|
| `daemonize.json.example` | 기본 — `.md`와 `.txt` 혼합 큐 |
| `daemonize.named-skill.example.json` | Markdown 프롬프트만 받는 큐 |
| `daemonize.mixed-skill-resolution.example.json` | 편집기가 파일을 여러 번 나눠 쓸 때 settle delay 필요 |
| `daemonize.phase-specific-clis.example.json` | 더 짧은 polling 간격이 필요한 경우 |

---

## 역할 기반 에이전트 파이프라인

`dormammu.json`에 `agents`가 설정되면 모든 실행 모드는 단일 에이전트 루프
대신 다음 파이프라인을 통해 각 goal을 처리합니다:

```text
analyzer (goals prelude) -> planner (goals prelude) -> designer (optional)
    -> refiner (mandatory) -> planner (mandatory) -> developer -> tester
    -> reviewer -> committer
```

역할 namespace는 runtime, goals prelude, goals checkpoint 설정이 공유합니다.
`analyzer`는 goals/autonomous 전용이고, `designer`는 goals prelude 전용이며,
`planner`는 goals prompt synthesis와 필수 runtime planning 단계가 함께 쓰는
공유 역할입니다. `architect`는 호환 alias가 아니며 현재 role 이름은
`designer`입니다.

### 역할

| 역할 | 출력 | verdict | 재진입 조건 |
|------|------|---------|-----------|
| analyzer | `.dev/logs/<date>_analyzer_<stem>.md` | — | — |
| refiner | `.dev/REQUIREMENTS.md` | — | — |
| planner | `.dev/WORKFLOWS.md` | — | — |
| designer | `.dev/logs/<date>_designer_<stem>.md` | — | — |
| developer | (`.dev/` 내 상태 파일) | — | tester `FAIL` 또는 reviewer `NEEDS_WORK` |
| tester | `.dev/logs/<date>_tester_<stem>.md` | `OVERALL: PASS` / `OVERALL: FAIL` | — |
| reviewer | `.dev/logs/<date>_reviewer_<stem>.md` | `VERDICT: APPROVED` / `VERDICT: NEEDS_WORK` | — |
| committer | `.dev/logs/<date>_committer_<stem>.md` | — | — |
| evaluator | `.dev/logs/<date>_evaluator_<stem>.md` | `VERDICT: goal_achieved` / `VERDICT: partial` / `VERDICT: not_achieved` | goals-scheduler prompt만 |

**Refiner** (mandatory): runtime prompt를 읽어 `.dev/REQUIREMENTS.md`에 범위,
수용 기준, 제약 사항, 리스크를 정리합니다. `agents.refiner.cli`가 설정되면
그 값을 사용하고, 없으면 `active_agent_cli`로 fallback 됩니다.

**Planner** (mandatory): `.dev/REQUIREMENTS.md` (또는 raw prompt)를 읽어
`.dev/WORKFLOWS.md` — 적응형 `[ ] Phase N.` 체크리스트를 작성합니다.
`PLAN.md`와 `DASHBOARD.md`도 갱신합니다. `agents.planner.cli`가 설정되면
그 값을 사용하고, 없으면 `active_agent_cli`로 fallback 됩니다.

**Tester**는 black-box one-shot 에이전트입니다. goal에 기술된 관찰 가능한
동작을 기준으로 테스트 케이스를 설계하고 실행한 뒤 마지막 출력 줄에
`OVERALL: PASS` 또는 `OVERALL: FAIL`을 씁니다. `FAIL` verdict가 나오면
tester 리포트를 원본 프롬프트에 붙여서 developer가 다시 실행합니다.

**Reviewer**는 goal과 designer 설계 문서(`.dev/logs/<date>_designer_<stem>.md`)를
기준으로 코드 리뷰를 수행합니다. 마지막 줄에 `VERDICT: APPROVED` 또는
`VERDICT: NEEDS_WORK`를 씁니다. `NEEDS_WORK`이면 developer가 다시 진입합니다.

**재진입 한도**: tester 또는 reviewer 루프에서 설정된 iteration max에
도달하면 파이프라인이 다음 단계를 강제로 진행하지 않고
`manual_review_needed`로 멈춘 뒤 운영자 검토를 요구합니다.

### 역할별 CLI 해석 순서

각 역할에 대한 CLI는 다음 순서로 해석됩니다:

1. `dormammu.json`의 `agents.<role>.cli`
2. `active_agent_cli` (전역 fallback)

모든 런타임 역할은 역할별 CLI가 없으면 `active_agent_cli`로 fallback 됩니다.

---

## Goals 자동화

`daemonize.json`에 `goals`가 설정되면 `GoalsScheduler` 스레드가 데몬과
함께 실행됩니다. `interval_minutes` 마다 `goals.path` 디렉터리를 스캔하고
`.md` 파일을 발견하면 다음 파이프라인 실행을 위해 `prompt_path/`에 프롬프트로
넣습니다. 이미 처리된 파일(`<date>_<stem>` 기준)은 건너뜁니다.

프롬프트를 큐에 넣기 전에 goals 전용 전문가 prelude를 사용할 수 있습니다:

- `analyzer`가 goal을 요구사항 분석 문서로 정리
- `planner`가 이를 authoritative plan으로 변환
- 필요하면 `designer`가 기술 설계 문맥을 추가

이 prelude는 prompt synthesis 전용입니다. 그 다음 큐에 들어간 prompt는
런타임 파이프라인이 반드시 `refine -> plan`부터 시작하고, 이후 단계는
`.dev/WORKFLOWS.md`를 통해 runtime planner가 결정하도록 지시합니다.

goals 디렉터리는 Telegram 봇 연동을 통해 `/goals` 명령으로도 관리할 수
있습니다 (목록 조회, 추가, 삭제).

---

## Guidance 파일

Guidance 파일을 사용하면 저장소별 운영 규칙을 모든 에이전트 프롬프트에
주입할 수 있습니다. DORMAMMU는 다음 순서로 guidance를 해석합니다:

1. 명시적으로 전달한 `--guidance-file` 플래그 (전달 순서대로)
2. 저장소 guidance: 저장소 루트의 `AGENTS.md` 또는 `agents/AGENTS.md`
3. `~/.dormammu/agents` 아래 설치된 fallback guidance
4. DORMAMMU에 번들된 패키지 fallback guidance 에셋

예시 — 여러 guidance 파일을 명시적으로 전달:

```bash
dormammu run \
  --repo-root . \
  --agent-cli codex \
  --guidance-file AGENTS.md \
  --guidance-file docs/agent-rules.md \
  --prompt "요청된 변경을 구현하세요."
```

---

## `.dev` 디렉터리

`.dev/`는 사람과 자동화가 함께 사용하는 제어면입니다.

| 파일 | 역할 |
|------|------|
| `.dev/REQUIREMENTS.md` | refining agent가 작성한 구조화된 요구사항 |
| `.dev/WORKFLOWS.md` | planning agent가 작성한 적응형 단계 체크리스트 (`[ ]` / `[O]`) |
| `.dev/DASHBOARD.md` | 현재 운영자 관점 상태: 활성 단계, 다음 액션, 리스크 |
| `.dev/PLAN.md` | 프롬프트 기반 단계 체크리스트 (`[ ]` 미완료, `[O]` 완료) |
| `.dev/workflow_state.json` | 기계 기준 워크플로우 상태 — 진실의 근원 |
| `.dev/session.json` | 활성 세션 메타데이터 |
| `.dev/logs/` | 실행별 프롬프트, stdout, stderr, 메타데이터 및 단계 출력 문서 |

디버그 로그:

- `--debug`와 함께 `run`, `run-once`, `resume` → 저장소 루트의 `DORMAMMU.log`
- `daemonize --debug` → `<result_path>/../progress/<prompt>_progress.log`,
  새 프롬프트 세션마다 새로 생성

---

## 세션 관리

DORMAMMU는 세션 단위로 작업을 추적합니다. 각 세션에는 ID와 goal이 있습니다.

```bash
# 새로운 named 세션 시작
dormammu start-session --repo-root . --goal "Phase 2 후속 작업"

# 저장된 세션 목록 조회
dormammu sessions --repo-root .

# 이전 세션 복원
dormammu restore-session --repo-root . --session-id <id>
```

세션은 워크플로우 히스토리를 분기하거나 이후 작업을 버리지 않고
이전 체크포인트로 돌아가야 할 때 유용합니다.

---

## Fallback Agent CLI

기본 에이전트 CLI가 토큰 소진 또는 쿼터 한도에 도달하면(`token_exhaustion_patterns`
매칭) DORMAMMU는 자동으로 다음 설정된 fallback CLI로 전환합니다.

설정이 없을 때 기본 fallback 순서:

1. `codex`
2. `claude`
3. `gemini`

`dormammu.json`에서 fallback 설정:

```json
{
  "active_agent_cli": "codex",
  "fallback_agent_clis": [
    "claude",
    "gemini"
  ],
  "token_exhaustion_patterns": [
    "usage limit", "quota exceeded", "rate limit exceeded"
  ]
}
```

---

## Working Directory와 CLI Override

`--workdir`는 외부 CLI의 프로세스 작업 디렉터리를 설정합니다. 어댑터가
해당 CLI의 workdir 플래그를 알고 있으면 값을 그쪽에도 전달합니다.

```bash
dormammu run-once \
  --repo-root . \
  --agent-cli cline \
  --workdir ./subproject \
  --prompt "이 서브프로젝트를 분석하고 다음 단계를 요약하세요."
```

`cline` preset의 경우 `--workdir`가 `--cwd <path>`로 전달됩니다.

추가 플래그를 전달하려면:

```bash
dormammu run-once \
  --repo-root . \
  --agent-cli gemini \
  --prompt "저장소를 요약하세요." \
  --extra-arg=--approval-mode \
  --extra-arg=auto_edit
```

CLI별 기본값은 `cli_overrides`에서 설정합니다:

```json
{
  "cli_overrides": {
    "cline": { "extra_args": ["-y", "--timeout", "1200"] }
  }
}
```

---

## 대표 운영 흐름

```bash
# 1. 환경 확인
dormammu doctor --repo-root . --agent-cli codex

# 2. 상태 초기화
dormammu init-state --repo-root . --goal "요청된 변경을 안전하게 배포한다"

# 3. 설정 및 CLI 어댑터 확인
dormammu show-config --repo-root .
dormammu inspect-cli --repo-root . --agent-cli codex

# 4. 실행
dormammu run \
  --repo-root . \
  --agent-cli codex \
  --prompt-file PROMPT.md \
  --required-path README.md \
  --require-worktree-changes

# 5. 중단 시 재개
dormammu resume --repo-root .
```

---

## 저장소 구조

```text
backend/     Python 패키지 — 루프 엔진, CLI 어댑터, 상태, supervisor, 데몬
agents/      배포 가능한 workflow 및 skill guidance 번들
templates/   .dev/ 상태 파일 bootstrap 템플릿
docs/        사용자 및 운영자 문서
scripts/     설치 및 개발 보조 스크립트
tests/       런타임, 어댑터, 워크플로우 검증
```
