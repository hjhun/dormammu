# DORMAMMU 가이드

`dormammu`는 코딩 에이전트를 위한 CLI 중심 워크플로우 루프 오케스트레이터입니다.
외부 에이전트 CLI를 감싸서 실행하고, `.dev/` 아래에 재개 가능한 상태를
저장하며, Supervisor 관점의 검증과 재시도 흐름을 함께 제공합니다.

짧은 소개는 [README.md](../../README.md)를 먼저 보면 됩니다.

## DORMAMMU가 잘하는 일

`dormammu`는 다음과 같은 요구가 있는 저장소 운영에 맞춰져 있습니다.

- 반복 가능해야 함
- 실행 근거를 나중에 다시 확인할 수 있어야 함
- 중단 이후 재개가 가능해야 함
- Supervisor 기준으로 결과를 검증할 수 있어야 함
- 터미널에서 바로 운영할 수 있어야 함

단순히 에이전트를 한 번 호출하는 대신, 프롬프트, 로그, 세션 상태,
검증 맥락을 `.dev/` 아래에 함께 남겨서 사람이 보기에도, 자동화가 읽기에도
좋은 흐름을 만듭니다.

## 핵심 기능

- 외부 코딩 에이전트 CLI 오케스트레이션
- 단일 실행과 supervised retry loop
- 중단 이후 resume 지원
- 세션 시작, 저장, 목록 조회, 복원
- `.dev/` 아래의 Markdown + JSON 상태 관리
- 저장소별 운영 규칙을 넣을 수 있는 guidance 파일 임베딩
- 쿼터 또는 토큰 소진 시 fallback agent CLI 지원
- 프롬프트 방식, workdir 지원, 승인 우회 힌트를 보는 `inspect-cli`
- 환경 점검용 `doctor`

## 지원하는 에이전트 CLI 패턴

`dormammu`는 다음과 같은 코딩 에이전트 CLI에 대해 preset 기반 동작을
제공합니다.

- `codex`
- `claude`
- `gemini`
- `cline`
- `aider`

preset 지원 덕분에 `dormammu`는 프롬프트 전달 방식, 명령 prefix, workdir
플래그, 승인 관련 기본 옵션을 더 안정적으로 다룰 수 있습니다.

확인 예시:

```bash
dormammu inspect-cli --repo-root . --agent-cli codex
```

## 설치

### 릴리스 설치 스크립트 사용

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

지원 Python 버전은 `3.10+`입니다.

## 빠른 시작

### 1. 환경 점검

```bash
dormammu doctor --repo-root . --agent-cli codex
```

이 단계에서는 Python 버전, 에이전트 CLI 경로, 저장소 쓰기 가능 여부,
`.agents` 같은 에이전트 작업 디렉터리 존재 여부를 확인합니다.

### 2. `.dev` 초기 상태 생성

```bash
dormammu init-state \
  --repo-root . \
  --goal "요청된 저장소 작업을 안전하게 구현한다."
```

이 명령은 다음과 같은 상태 파일을 초기화하거나 갱신합니다.

- `.dev/DASHBOARD.md`
- `.dev/PLAN.md`
- `.dev/session.json`
- `.dev/workflow_state.json`

또한 로컬 머신에서 지원되는 coding-agent CLI를 조사하고, 다음 우선순위로
가장 먼저 발견된 명령을 `active_agent_cli`로 갱신합니다:
`codex`, `claude`, `gemini`, `cline`.

### 3. 외부 CLI 어댑터 동작 확인

```bash
dormammu inspect-cli --repo-root . --agent-cli cline
```

실제 실행 전에 프롬프트 전달 방식, workdir 지원 여부, 승인 우회 힌트를
확인하고 싶을 때 유용합니다.

### 4. 단일 실행

```bash
dormammu run-once \
  --repo-root . \
  --agent-cli codex \
  --prompt "저장소 가이드를 읽고 다음 구현 단계를 요약하세요."
```

`run-once`는 재시도 루프 없이 한 번만 실행하고, 관련 아티팩트를 남길 때
적합합니다.

### 5. supervised loop 실행

```bash
dormammu run \
  --repo-root . \
  --agent-cli codex \
  --prompt-file PROMPT.md \
  --required-path README.md \
  --require-worktree-changes \
  --max-iterations 50
```

`run`은 다음 흐름이 필요할 때 사용합니다.

- 외부 에이전트 실행
- 결과 검증
- 결과가 불완전할 때 continuation 맥락 생성
- 설정된 정책에 따라 재시도

`--max-iterations`와 `--max-retries`를 모두 주지 않으면 Dormammu는 총
`50`회 시도를 기본값으로 사용합니다. 그보다 먼저 supervisor가 작업을
승인하면 남은 budget을 소진하지 않고 즉시 종료합니다.

### 6. 나중에 이어서 실행

```bash
dormammu resume --repo-root .
```

`resume`은 전체 작업을 처음부터 다시 시작하는 대신, 저장된 loop 상태에서
이어갑니다.

## 주요 명령 이해하기

### `dormammu doctor`

다음 항목을 점검합니다.

- Python 버전
- agent CLI 사용 가능 여부
- `.agent` 또는 `.agents` 디렉터리 존재 여부
- 저장소 루트 쓰기 가능 여부

### `dormammu init-state`

활성 저장소를 위한 bootstrap 상태를 생성하거나 병합합니다. 실제 실행 전에
`.dev/`를 준비하는 가장 간단한 방법입니다. bootstrap 과정에서 지원되는 CLI를
다시 확인하고 `active_agent_cli`를 우선순위 `codex`, `claude`, `gemini`,
`cline` 순으로 사용 가능한 값으로 갱신합니다.

### `dormammu run-once`

외부 에이전트를 한 번 실행하고 다음 정보를 저장합니다.

- 프롬프트 아티팩트
- stdout / stderr 로그
- 명령과 CLI capability 메타데이터
- 최신 실행 정보

### `dormammu run`

supervised loop를 실행합니다. 자주 쓰는 옵션은 다음과 같습니다.

- `--max-iterations`
- `--required-path`
- `--require-worktree-changes`
- `--max-retries`
- `--workdir`
- `--extra-arg`
- `--guidance-file`

### `dormammu resume`

저장된 loop 상태와 continuation 맥락을 다시 읽어서 복구 흐름을 재시작합니다.

### `dormammu inspect-cli`

다음 정보를 JSON으로 보여줍니다.

- 감지된 프롬프트 모드
- 매칭된 preset
- command prefix
- workdir 플래그 지원 여부
- 승인 관련 힌트

### 세션 명령

다음 명령도 함께 제공합니다.

- `start-session`
- `sessions`
- `restore-session`

이 명령들은 작업 흐름을 새로 시작하거나, 예전 세션 스냅샷으로 돌아가야 할
때 유용합니다.

### `dormammu daemonize`

별도의 daemon JSON 설정 파일을 기준으로 프롬프트 디렉터리를 감시하고,
들어오는 프롬프트를 하나씩 순차 처리합니다.

예시:

```bash
dormammu daemonize --repo-root . --config daemonize.json
```

`daemonize`는 다음 흐름이 필요할 때 사용합니다.

- `prompt_path`에 새 프롬프트 파일이 들어오는 것을 감시
- 파일명 앞의 숫자 prefix 우선, 그다음 알파벳 prefix 우선, 마지막으로 일반
  파일명 순서로 정렬
- 각 프롬프트마다 설정된 phase를 순서대로 실행
- `result_path`에 프롬프트별 결과 리포트 생성

시작점으로는 [daemonize.json.example](../../daemonize.json.example)를
사용하면 됩니다.

## `.dev` 디렉터리

`dormammu`는 `.dev/`를 사람과 자동화가 함께 보는 제어면으로 사용합니다.

중요한 파일은 다음과 같습니다.

- `.dev/DASHBOARD.md`: 운영자 관점의 현재 상태
- `.dev/PLAN.md`: 프롬프트에서 파생된 구현 체크리스트
- `.dev/workflow_state.json`: 기계 기준 워크플로우 상태
- `.dev/session.json`: 활성 세션 메타데이터
- `.dev/logs/`: 실행 아티팩트와 로그

저장소 루트의 `DORMAMMU.log`는 `run`, `run-once`, `resume` 실행 시점의
배너와 미러링된 stderr 출력을 함께 남깁니다.

## Guidance 파일 동작 방식

guidance 파일은 저장소별 운영 규칙을 실행 프롬프트에 주입할 수 있게 해줍니다.

예시:

```bash
dormammu run \
  --repo-root . \
  --agent-cli codex \
  --guidance-file AGENTS.md \
  --guidance-file docs/agent-rules.md \
  --prompt "요청된 변경을 구현하세요."
```

해결 순서는 다음과 같습니다.

1. 명시적으로 넘긴 `--guidance-file`
2. 저장소 가이드 파일인 `AGENTS.md`, `agents/AGENTS.md`
3. `~/.dormammu/agents` 아래 설치된 fallback guidance
4. 패키지에 포함된 fallback guidance asset

## Daemonize 설정 규칙

`daemonize`는 `dormammu.json`과 별도의 JSON 설정 파일을 사용합니다.

- `dormammu.json`은 Dormammu 전체 런타임 기본 설정
- `daemonize.json`은 하나의 장기 실행 감시 워크플로 정의

핵심 필드는 다음과 같습니다.

- `prompt_path`
- `result_path`
- `watch`
- `queue`
- `phases`

## Phase의 Skill 지정 규칙

각 phase는 아래 둘 중 하나를 반드시 지정해야 합니다.

- `skill_name`
- `skill_path`

같은 phase에서 둘을 동시에 지정하면 안 됩니다.

### `skill_name`

`skill_name`은 재사용 가능한 named skill을 가리키는 방식입니다.
예를 들어 `planning-agent`, `developing-agent` 같은 이름을 넣습니다.

탐색 순서는 다음과 같습니다.

1. `repo_root/agents/skills/<skill_name>/SKILL.md`
2. `~/.dormammu/agents/skills/<skill_name>/SKILL.md`

두 위치 어디에도 없으면 daemon은 감시를 시작하지 않고, 설정 로딩 단계에서
즉시 실패합니다.

예시:

```json
{
  "skill_name": "planning-agent",
  "agent_cli": {
    "path": "codex",
    "input_mode": "auto",
    "extra_args": []
  }
}
```

`skill_name`을 쓰는 것이 좋은 경우:

- 저장소의 `agents/skills/` 아래 skill을 그대로 쓰고 싶을 때
- `~/.dormammu/agents/skills/`에 설치된 skill을 재사용하고 싶을 때
- 여러 머신에서 같은 skill 레이아웃을 기준으로 portable하게 운영하고 싶을 때

### `skill_path`

`skill_path`는 실제 skill 파일 경로를 직접 지정하는 방식입니다.
표준 named skill 레이아웃 바깥에 있는 파일을 사용하거나, 특정 skill 파일에
정확히 고정하고 싶을 때 적합합니다.

상대 경로는 셸의 현재 작업 디렉터리가 아니라 daemon config 파일이 있는
디렉터리를 기준으로 해석됩니다.

예시:

```json
{
  "skill_path": "./custom-skills/release-checklist.md",
  "agent_cli": {
    "path": "codex",
    "input_mode": "auto",
    "extra_args": []
  }
}
```

`skill_path`를 쓰는 것이 좋은 경우:

- 저장소 전용 커스텀 skill 문서를 쓰고 싶을 때
- 파일이 `agents/skills/<name>/SKILL.md` 구조를 따르지 않을 때
- config가 하나의 정확한 skill 문서를 가리키도록 고정하고 싶을 때

## Skill 규칙 요약

- 모든 phase는 skill 참조가 하나 필요합니다.
- `skill_name`과 `skill_path`는 상호 배타적입니다.
- `skill_name`은 저장소 로컬 skill을 먼저 찾고, 그다음
  `~/.dormammu/agents` 아래 설치된 skill을 찾습니다.
- `skill_path`는 실제 존재하는 파일이어야 합니다.
- skill 설정이 누락되거나 충돌하면 startup error로 처리합니다.

## 권장 기본 매핑

현재 내장 워크플로 번들 기준으로 일반적인 phase 매핑은 다음과 같습니다.

- `plan` -> `planning-agent`
- `design` -> `designing-agent`
- `develop` -> `developing-agent`
- `build_and_deploy` -> `building-and-deploying`
- `test_and_review` -> `testing-and-reviewing`
- `commit` -> `committing-agent`

## `~/.dormammu/agents` 아래 설치되는 Skill Path 예시

`skill_name` 대신 명시적인 `skill_path`를 쓰고 싶다면, 설치된 skill 번들의
일반적인 경로는 다음과 같습니다.

- `plan` -> `~/.dormammu/agents/skills/planning-agent/SKILL.md`
- `design` -> `~/.dormammu/agents/skills/designing-agent/SKILL.md`
- `develop` -> `~/.dormammu/agents/skills/developing-agent/SKILL.md`
- `build_and_deploy` -> `~/.dormammu/agents/skills/building-and-deploying/SKILL.md`
- `test_and_review` -> `~/.dormammu/agents/skills/testing-and-reviewing/SKILL.md`
- `commit` -> `~/.dormammu/agents/skills/committing-agent/SKILL.md`

예시:

```json
{
  "phases": {
    "plan": {
      "skill_path": "~/.dormammu/agents/skills/planning-agent/SKILL.md",
      "agent_cli": {
        "path": "codex",
        "input_mode": "auto",
        "extra_args": []
      }
    }
  }
}
```

명시적 `skill_path`가 특히 유용한 경우:

- config가 정확히 어떤 설치된 skill 파일에 의존하는지 분명히 보여주고 싶을 때
- 저장소 안에 `agents/skills/`가 없고 설치된 번들을 직접 쓰고 싶을 때
- 운영 리뷰 시 `skill_name` 해석 규칙보다 실제 파일 경로를 바로 보이고 싶을 때

## 추가 example 파일

Dormammu는 여러 운영 패턴을 바로 시작할 수 있도록 daemon config example을
여러 개 제공합니다.

- `daemonize.json.example`
  - `~/.dormammu/agents` 아래 설치된 기본 skill bundle의 `skill_path`를
    명시적으로 사용합니다.
  - phase와 skill 파일의 실제 연결을 리뷰하기 쉽게 보여주고 싶을 때 적합합니다.
- `daemonize.named-skill.example.json`
  - 모든 phase를 `skill_name` 기반으로 작성한 예시입니다.
  - 여러 저장소와 머신에서 portable하게 쓰고 싶을 때 적합합니다.
- `daemonize.mixed-skill-resolution.example.json`
  - `skill_name`과 `skill_path`를 섞어서 쓰는 예시입니다.
  - 대부분은 표준 skill을 쓰고 일부 phase만 저장소 로컬 custom skill로
    덮어쓰고 싶을 때 적합합니다.
- `daemonize.phase-specific-clis.example.json`
  - skill은 표준 매핑을 유지하면서 phase별 `agent_cli`를 다르게 두는
    예시입니다.
  - 계획, 구현, 리뷰, 배포 단계를 서로 다른 에이전트 CLI로 분리하고 싶을 때
    적합합니다.

## 어떤 example부터 시작하면 좋나요

처음 선택이 헷갈리면 아래 기준으로 고르면 됩니다.

- `daemonize.json.example`부터 시작
  - 설치된 기본 skill bundle의 `skill_path`를 전부 명시적으로 보고 싶을 때
  - 운영 리뷰에서 phase와 skill 파일 연결을 바로 확인하고 싶을 때
- `daemonize.named-skill.example.json`부터 시작
  - 가장 portable한 구성을 원할 때
  - 저장소 로컬 또는 설치된 skill 탐색 규칙을 그대로 활용하고 싶을 때
- `daemonize.mixed-skill-resolution.example.json`부터 시작
  - 대부분은 표준 skill을 쓰되 일부 phase만 저장소 전용 custom skill로
    바꾸고 싶을 때
- `daemonize.phase-specific-clis.example.json`부터 시작
  - 계획, 구현, 테스트/리뷰, 배포 단계를 서로 다른 agent CLI로 실행하고
    싶을 때

운영 상황별 추천은 보통 이렇게 보면 됩니다.

- 팀 공용으로 설치된 workflow bundle 중심 운영 -> `daemonize.json.example`
- 여러 저장소에 배포할 portable 템플릿 -> `daemonize.named-skill.example.json`
- 저장소에 릴리스/리뷰 전용 custom skill이 하나 섞인 경우 -> `daemonize.mixed-skill-resolution.example.json`
- planning/review/implementation backend를 분리해서 쓰는 경우 -> `daemonize.phase-specific-clis.example.json`

## 왜 이렇게 분리하나요

Dormammu는 다음 두 가지를 분리합니다.

- 이 phase에서 어떤 skill 계약을 따를지
- 그 skill을 어떤 외부 agent CLI로 실행할지

이 분리를 해두면 운영이 쉬워집니다.

- skill은 그대로 두고 `codex`에서 다른 CLI로 바꿀 수 있습니다.
- CLI는 그대로 두고 특정 phase만 다른 skill로 바꿀 수 있습니다.
- JSON 안에 긴 skill 본문을 중복해서 넣지 않아도 됩니다.

## Working Directory와 CLI Override

`--workdir`를 주면 `dormammu`는 항상 그 디렉터리를 외부 CLI의 프로세스
작업 디렉터리로 사용합니다. 그리고 해당 CLI의 workdir 플래그를 알고 있으면
그 값도 함께 전달합니다.

예를 들어 Cline preset은 다음을 지원합니다.

- positional prompt
- `-y`
- 기본 `--verbose`
- 기본 `--timeout 1200`
- `--cwd <path>`

예시:

```bash
dormammu run-once \
  --repo-root . \
  --agent-cli cline \
  --workdir ./subproject \
  --prompt "이 서브프로젝트를 분석하고 다음 단계를 요약하세요."
```

## Fallback Agent CLI

기본 백엔드가 토큰 또는 쿼터 문제를 만나면, `dormammu`는 다른 CLI로
넘어가도록 설정할 수 있습니다. 명시적 설정이 없으면 기본 순서는 다음과
같습니다.

- `codex`
- `claude`
- `gemini`

예시 설정:

```json
{
  "active_agent_cli": "/home/you/.local/bin/codex",
  "fallback_agent_clis": [
    "claude",
    {
      "path": "aider",
      "extra_args": ["--yes"]
    }
  ],
  "cli_overrides": {
    "cline": {
      "extra_args": ["-y", "--verbose", "--timeout", "1200"]
    }
  }
}
```

## 대표 운영 흐름

```bash
dormammu doctor --repo-root . --agent-cli codex
dormammu init-state --repo-root . --goal "요청된 변경을 안전하게 배포한다"
dormammu inspect-cli --repo-root . --agent-cli codex
dormammu run --repo-root . --agent-cli codex --prompt-file PROMPT.md --required-path README.md
dormammu resume --repo-root .
```

## 저장소 구조

```text
backend/     Python 패키지, 루프 엔진, 어댑터, 상태, supervisor
agents/      배포 가능한 workflow 및 skill 가이드 번들
templates/   `.dev` bootstrap 템플릿
docs/        문서
scripts/     설치 및 개발 보조 스크립트
tests/       런타임 및 워크플로우 검증
```
