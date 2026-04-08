# DORMAMMU 가이드

이 문서는 `dormammu`를 처음 사용하는 사용자와 기여자를 위한 입문 가이드입니다.

`dormammu`는 코딩 에이전트용 터미널 중심 워크플로우 루프 엔진입니다. 외부
에이전트 CLI를 실행하고, `.dev/` 아래에 사람이 읽을 수 있는 상태와 기계가
읽을 수 있는 상태를 함께 저장하며, Supervisor가 결과를 검증하고, 작업이
중단되었을 때 안전하게 이어서 진행할 수 있게 도와줍니다.

만약 "에이전트를 한 번 실행하고 잘 되길 바란다" 수준보다 더 구조적인
워크플로우가 필요하다면, 이 프로젝트는 바로 그 목적에 맞게 설계되어
있습니다.

## 이 가이드가 필요한 사람

다음에 해당하면 이 문서가 도움이 됩니다.

- `dormammu`가 처음이다
- 이 프로젝트가 어떤 문제를 해결하는지 이해하고 싶다
- 첫 실행에 바로 쓸 수 있는 명령 예제가 필요하다
- `.dev` 파일이 무엇을 의미하는지 먼저 알고 싶다

## DORMAMMU가 하는 일

`dormammu`는 반복적인 에이전트 작업을 더 안전하게 운영할 수 있도록
도와줍니다.

단순히 코딩 에이전트를 한 번 실행하는 방식이 아니라, 다음과 같은 구조를
제공합니다.

- 웹 UI 없이도 동작하는 터미널 중심 코어
- `.dev/` 아래에 저장되는 재개 가능한 상태
- 필수 파일과 작업 트리 변경 여부를 확인하는 Supervisor 검증
- 첫 실행으로 충분하지 않을 때 이어서 실행할 수 있는 continuation 흐름
- 진행 상황을 볼 수 있는 선택형 로컬 브라우저 UI
- 기본 백엔드가 쿼터나 토큰 한도에 걸렸을 때를 위한 fallback CLI 지원

## 핵심 개념

### 1. 터미널 우선 아키텍처

중요한 워크플로우는 먼저 Python 모듈과 CLI 엔트리포인트에서 동작합니다.
로컬 웹 UI는 유용하지만 필수는 아닙니다.

### 2. `.dev/` 아래에 저장되는 상태

`dormammu`는 사람용 상태와 기계용 상태를 모두 `.dev/` 아래에 기록하므로,
나중에 실행 결과를 확인하거나 안전하게 재개할 수 있습니다.

### 3. Supervisor 기반 검증

실행이 끝난 뒤 Supervisor가 기대한 결과가 실제로 존재하는지 확인합니다.
조건을 만족하지 못하면, 작업이 끝났다고 가정하는 대신 continuation 작업을
준비할 수 있습니다.

### 4. 재시작보다 재개

프로세스가 중단되었을 때 전체 세션을 버리고 처음부터 다시 시작하는 대신,
저장된 상태에서 이어서 작업할 수 있습니다.

## 저장소 구조

주요 디렉터리는 아래와 같습니다.

```text
backend/     Python 패키지, 루프 엔진, 어댑터, supervisor, API
frontend/    가벼운 로컬 UI 자산
templates/   .dev 상태 초기화 템플릿
docs/        프로젝트 문서
scripts/     설치 및 개발 보조 스크립트
tests/       런타임 및 워크플로우 검증
```

## 설치 방법

사용 목적에 맞는 경로를 선택하면 됩니다.

### 옵션 1: 저장소 설치 스크립트로 사용자 설치

가장 쉽게 실행 가능한 `dormammu` 명령을 얻는 방법입니다.

```bash
curl -fsSL https://raw.githubusercontent.com/hjhun/dormammu/main/install.sh | bash
```

기본적으로 이 설치 스크립트는 다음을 수행합니다.

- `~/.dormammu` 아래에 런타임 생성
- `~/.dormammu/bin` 아래에 `dormammu` 링크 생성
- `~/.dormammu/config`에 설정 저장
- `~/.bashrc`를 중복 없이 갱신
- `codex`, `claude`, `gemini`, `cline` 같은 에이전트 CLI 탐지 시도

### 옵션 2: 로컬 저장소 설치

이미 저장소를 클론했고 로컬 개발 환경으로 사용하고 싶다면:

```bash
./scripts/install.sh
```

이 스크립트는 `.venv`를 생성하거나 재사용하고, `pip`를 업데이트한 뒤
프로젝트를 editable 모드로 설치합니다.

### 옵션 3: 수동 editable 설치

가상환경을 직접 관리하고 싶다면:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

## 소스 트리에서 직접 CLI 실행하기

패키지를 아직 설치하지 않았더라도 저장소에서 직접 실행할 수 있습니다.

```bash
PYTHONPATH=backend python3 -m dormammu --help
```

이 가이드에서는 가장 단순한 사용자 경험을 위해 설치된 `dormammu`
실행 파일을 기준으로 예제를 보여줍니다. 만약 소스 트리에서만 작업 중이라면
`dormammu` 대신 아래 형태를 사용하면 됩니다.

```bash
PYTHONPATH=backend python3 -m dormammu
```

## 첫 실행 전에 확인할 것

저장소 안에 `.agent` 또는 `.agents` 디렉터리가 있어야 합니다.
`doctor` 명령은 이 디렉터리 중 하나가 존재하는지 확인합니다. 이 프로젝트는
그 디렉터리를 에이전트 작업 공간 계약의 일부로 취급합니다.

또한 사용할 코딩 에이전트 CLI가 준비되어 있어야 합니다. `--agent-cli`로
직접 전달할 수도 있고, 설정 파일의 `active_agent_cli`로 기본값을 지정할
수도 있습니다.

## 빠른 시작

가장 작은 유효 실행 흐름은 아래와 같습니다.

```bash
dormammu doctor --repo-root . --agent-cli codex
dormammu init-state
dormammu run \
  --repo-root . \
  --agent-cli codex \
  --prompt "Inspect the repo and implement the requested change." \
  --required-path README.md
dormammu ui
```

UI를 시작했다면 브라우저에서 `http://127.0.0.1:8000/`를 열면 됩니다.

각 단계의 의미는 다음과 같습니다.

1. `doctor`는 현재 환경이 실행 준비가 되었는지 확인합니다.
2. `init-state`는 기본 `.dev` 상태 파일을 생성하거나 병합합니다.
3. `run`은 외부 에이전트 CLI를 Supervisor가 감싸는 재시도 루프로 실행합니다.
4. `ui`는 로그와 상태를 볼 수 있는 선택형 브라우저 화면을 띄웁니다.

## `.dev` 디렉터리 이해하기

`dormammu`에서 가장 중요한 개념 중 하나는 상태가 파일에 저장된다는 점입니다.

특히 아래 파일들이 중요합니다.

- `.dev/DASHBOARD.md`
  사람이 읽는 워크플로우 요약, 현재 단계, 다음 액션, Supervisor verdict
- `.dev/TASKS.md`
  현재 작업 슬라이스의 체크리스트
- `.dev/workflow_state.json`
  워크플로우 상태의 기계용 소스 오브 트루스
- `.dev/session.json`
  활성 세션 메타데이터, resume 체크포인트, 최근 루프 세부 정보
- `.dev/logs/`
  프롬프트, stdout, stderr, 메타데이터 등 실행 산출물

이 구조가 중요한 이유는 다음과 같습니다.

- 사람은 별도 도구 없이 진행 상황을 읽을 수 있다
- 자동화는 JSON 상태를 구조적으로 읽을 수 있다
- 중단된 세션을 증거와 함께 재개할 수 있다

## 주요 명령

### `dormammu run`

외부 에이전트 CLI를 Supervisor가 감싸는 루프 안에서 실행합니다.

예시:

```bash
dormammu run \
  --repo-root . \
  --agent-cli codex \
  --prompt "Add a setup guide to the repo." \
  --required-path docs/GUIDE.md \
  --require-worktree-changes
```

자주 쓰는 옵션:

- `--prompt` 또는 `--prompt-file`
- `--agent-cli`
- `--required-path`
- `--require-worktree-changes`
- `--max-retries`
- `--extra-arg`

첫 시도 이후에도 무한 재시도를 원하면 `--max-retries -1`을 사용합니다.

### `dormammu resume`

저장된 상태를 바탕으로 가장 최근의 supervised loop를 재개합니다.

예시:

```bash
dormammu resume --repo-root .
```

저장된 세션을 사용 중이라면 특정 세션을 복원한 뒤 재개할 수도 있습니다.

```bash
dormammu resume --repo-root . --session-id your-session-id
```

### `dormammu doctor`

현재 환경이 `dormammu` 실행 준비가 되었는지 점검합니다.

점검 항목:

- Python 버전
- 에이전트 CLI 사용 가능 여부
- `.agent` 또는 `.agents` 존재 여부
- 저장소 쓰기 권한

예시:

```bash
dormammu doctor --repo-root . --agent-cli codex
```

### `dormammu inspect-cli`

외부 CLI가 프롬프트를 어떻게 처리하는지, 위험한 승인 우회 힌트가 있는지
점검합니다.

예시:

```bash
dormammu inspect-cli --repo-root . --agent-cli codex --include-help-text
```

### `dormammu ui`

선택형 로컬 UI를 시작합니다.

예시:

```bash
dormammu ui --repo-root .
```

### 세션 관리 명령

여러 개의 저장된 워크플로우 상태를 다루고 싶다면 아래 명령을 사용합니다.

- `dormammu start-session`
- `dormammu sessions`
- `dormammu restore-session`

## 설정 파일

`dormammu`는 아래 순서로 설정을 읽습니다.

1. `DORMAMMU_CONFIG_PATH`
2. 저장소 루트의 `dormammu.json`
3. `~/.dormammu/config`

이 우선순위가 중요한 이유는 다음과 같습니다.

- 특정 셸 세션에서만 쓰는 일회성 override 가능
- 팀과 공유할 저장소 단위 설정 가능
- 평소 사용하는 사용자 기본 설정 유지 가능

### 설정 예시

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
      "extra_args": ["-y"]
    }
  },
  "token_exhaustion_patterns": [
    "usage limit",
    "quota exceeded",
    "rate limit exceeded",
    "token limit"
  ]
}
```

### 각 필드의 의미

- `active_agent_cli`
  `--agent-cli`를 생략했을 때 사용할 기본 CLI
- `fallback_agent_clis`
  기본 백엔드가 소진되었을 때 시도할 추가 CLI 목록
- `cli_overrides`
  CLI 계열별 기본 옵션 설정
- `token_exhaustion_patterns`
  fallback 시도를 시작할지 판단하는 출력 패턴

## Fallback CLI 동작 방식

기본 코딩 에이전트 CLI가 쿼터나 토큰 한도에 도달하면, `dormammu`는 일반
재시도 예산을 소모하지 않고 다른 CLI를 시도할 수 있습니다.

중요한 동작 규칙:

- 명시적으로 요청한 CLI를 항상 먼저 시도한다
- fallback은 토큰 소진 패턴이 실제 출력과 일치할 때만 일어난다
- fallback 시도는 일반 retry 횟수를 소모하지 않는다
- 모든 CLI가 소진되면 실행은 `blocked` 상태로 멈춘다

## 초보자에게 추천하는 운영 순서

처음에는 아래 순서로 작업하면 안전합니다.

1. `dormammu doctor` 실행
2. 사용할 CLI에 대해 `dormammu inspect-cli` 한 번 실행
3. `dormammu init-state` 실행
4. `--required-path`를 1개 또는 2개만 둔 작은 `dormammu run` 실행
5. 필요하면 `dormammu ui`로 진행 상황 확인
6. 중단 시 수동 재구성 대신 `dormammu resume` 사용

## 문제 해결

### `doctor`가 에이전트 CLI를 찾지 못한다

전체 경로를 직접 넘겨보세요.

```bash
dormammu doctor --repo-root . --agent-cli /full/path/to/codex
```

또는 설정 파일의 `active_agent_cli`에 기본값을 저장해두면 매번 경로를
반복하지 않아도 됩니다.

### `doctor`가 `.agent` 또는 `.agents`가 없다고 말한다

이 저장소가 기대하는 에이전트 작업 공간 디렉터리를 생성하거나 복원해야
합니다. 이 프로젝트에서는 해당 디렉터리를 워크플로우 계약의 일부로 봅니다.

### 설치 후 `dormammu` 명령을 찾을 수 없다

새 셸을 열거나, `~/.dormammu/bin`이 `PATH`에 포함되어 있는지 확인하세요.

또는 아래처럼 소스 트리에서 직접 실행할 수 있습니다.

```bash
PYTHONPATH=backend python3 -m dormammu --help
```

### 작업이 끝나기 전에 실행이 멈췄다

먼저 아래 파일을 확인하세요.

- `.dev/DASHBOARD.md`의 다음 액션
- `.dev/TASKS.md`의 진행 상태
- `.dev/supervisor_report.md`의 마지막 검증 결과
- `.dev/logs/`의 프롬프트, stdout, stderr, 메타데이터 산출물

그 다음 아래 명령으로 재개하면 됩니다.

```bash
dormammu resume --repo-root .
```

### UI가 없어도 핵심 워크플로우는 계속 된다

정상적인 동작입니다. 이 프로젝트는 의도적으로 웹 UI 없이도 핵심 기능을
쓸 수 있도록 설계되어 있습니다. UI를 사용할 수 없더라도 터미널과 `.dev`
기반 워크플로우는 계속 진행할 수 있습니다.

## 다음에 보면 좋은 것

기본 흐름에 익숙해졌다면 다음도 함께 보세요.

- [README.md](../../README.md)에서 더 짧은 프로젝트 개요 확인
- 제품 방향에 기여하려면 `.dev/PROJECT.md`와 `.dev/ROADMAP.md` 읽기
- 기대 동작을 이해하려면 `tests/` 아래 테스트 살펴보기
