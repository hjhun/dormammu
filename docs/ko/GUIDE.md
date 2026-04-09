# DORMAMMU 가이드

`dormammu`는 코딩 에이전트용 CLI 중심 워크플로우 루프 엔진입니다. 외부
에이전트 CLI를 실행하고, `.dev/` 아래에 사람이 읽을 수 있는 상태와 기계가
읽을 수 있는 상태를 함께 저장하며, Supervisor가 결과를 검증하고, 작업이
중단되었을 때 안전하게 이어서 진행할 수 있게 도와줍니다.

## DORMAMMU가 하는 일

`dormammu`는 반복적인 에이전트 작업을 더 안전하게 운영할 수 있도록
도와줍니다.

제공하는 핵심 기능은 다음과 같습니다.

- 터미널 전용 워크플로우 표면
- `.dev/` 아래에 저장되는 재개 가능한 상태
- 필수 파일과 작업 트리 변경 여부를 확인하는 Supervisor 검증
- 첫 실행으로 충분하지 않을 때 이어서 실행할 수 있는 continuation 흐름
- 기본 백엔드가 쿼터나 토큰 한도에 걸렸을 때를 위한 fallback CLI 지원

## 핵심 개념

### 1. CLI 우선 아키텍처

중요한 워크플로우는 Python 모듈과 CLI 엔트리포인트만으로 동작합니다.

### 2. `.dev/` 아래에 저장되는 상태

`dormammu`는 사람용 상태와 기계용 상태를 모두 `.dev/` 아래에 기록하므로,
나중에 실행 결과를 확인하거나 안전하게 재개할 수 있습니다.

### 3. Supervisor 기반 검증

실행이 끝난 뒤 Supervisor가 기대한 결과가 실제로 존재하는지 확인합니다.

### 4. 재시작보다 재개

프로세스가 중단되었을 때 전체 세션을 버리는 대신 저장된 상태에서 이어서
작업할 수 있습니다.

## 저장소 구조

```text
backend/     Python 패키지, 루프 엔진, 어댑터, supervisor
templates/   .dev 상태 초기화 템플릿
docs/        프로젝트 문서
scripts/     설치 및 개발 보조 스크립트
tests/       런타임 및 워크플로우 검증
```

## 설치

```bash
curl -fsSL https://raw.githubusercontent.com/hjhun/dormammu/main/install.sh | bash
```

로컬 개발 환경에서는 아래처럼 설치할 수 있습니다.

```bash
./scripts/install.sh
```

## 빠른 시작

```bash
dormammu doctor --repo-root . --agent-cli codex
dormammu init-state
dormammu run \
  --repo-root . \
  --agent-cli codex \
  --prompt "Inspect the repo and implement the requested change." \
  --required-path README.md
```

## `.dev` 디렉터리 이해하기

중요한 파일은 다음과 같습니다.

- `.dev/DASHBOARD.md`: 지금 실제로 진행 중인 내용을 보여주는 운영 대시보드
- `.dev/TASKS.md`: PROMPT 기반으로 진행해야 할 개발 항목을 나열한 체크리스트
- `.dev/workflow_state.json`
- `.dev/session.json`
- `.dev/logs/`

## 주요 명령

### `dormammu run`

외부 에이전트 CLI를 Supervisor가 감싸는 루프 안에서 실행합니다.

### `dormammu resume`

저장된 상태를 바탕으로 가장 최근의 supervised loop를 재개합니다.

### `dormammu doctor`

현재 환경이 `dormammu` 실행 준비가 되었는지 점검합니다.

### `dormammu inspect-cli`

외부 CLI가 프롬프트를 어떻게 처리하는지, 위험한 승인 우회 힌트가 있는지
점검합니다.
