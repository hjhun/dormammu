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
  --max-retries 2
```

`run`은 다음 흐름이 필요할 때 사용합니다.

- 외부 에이전트 실행
- 결과 검증
- 결과가 불완전할 때 continuation 맥락 생성
- 설정된 정책에 따라 재시도

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
`.dev/`를 준비하는 가장 간단한 방법입니다.

### `dormammu run-once`

외부 에이전트를 한 번 실행하고 다음 정보를 저장합니다.

- 프롬프트 아티팩트
- stdout / stderr 로그
- 명령과 CLI capability 메타데이터
- 최신 실행 정보

### `dormammu run`

supervised loop를 실행합니다. 자주 쓰는 옵션은 다음과 같습니다.

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
4. 패키지에 포함된 fallback guidance

## Working Directory와 CLI Override

`--workdir`를 주면 `dormammu`는 항상 그 디렉터리를 외부 CLI의 프로세스
작업 디렉터리로 사용합니다. 그리고 해당 CLI의 workdir 플래그를 알고 있으면
그 값도 함께 전달합니다.

예를 들어 Cline preset은 다음을 지원합니다.

- positional prompt
- `-y`
- 기본 `--verbose`
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
      "extra_args": ["-y", "--verbose"]
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
