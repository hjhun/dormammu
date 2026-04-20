# Dormammu 참고 구현 계획

## 목적

이 문서는 Claude Code와 OpenCode의 구조를 참고해서 `dormammu`에 실제로 적용할 개발 계획으로 정리한 문서입니다.

분석 일자: 2026년 4월 19일

사용한 주요 자료:

- Claude Code 공식 문서
  - `https://docs.anthropic.com/en/docs/claude-code/overview`
  - `https://docs.anthropic.com/en/docs/claude-code/settings`
  - `https://docs.anthropic.com/en/docs/claude-code/hooks`
  - `https://docs.anthropic.com/en/docs/claude-code/sub-agents`
  - `https://docs.anthropic.com/en/docs/claude-code/mcp`
  - `https://docs.anthropic.com/en/docs/claude-code/ide-integrations`
- Claude Code npm 패키지 `@anthropic-ai/claude-code` 버전 `2.1.114`
- OpenCode 저장소 `sst/opencode` 커밋 `33b2795cc84c79e91e15549609713567eb08348a`
- `graphify` 기반 로컬 분석
  - Claude Code 문서/패키지 코퍼스
  - OpenCode 핵심 코퍼스
  - 현재 `dormammu` 저장소

참고: Claude Code는 전체 런타임 소스가 공개되어 있지 않으므로, 해당 항목은 내부 구현보다 공개된 구조와 확장 지점 위주로 분석했습니다.

## 구조 요약

### Claude Code

Claude Code는 공개 런타임 소스보다는 설정, 서브에이전트, 훅, MCP 같은 제품 인터페이스를 통해 구조가 드러납니다.

핵심 패턴:

- 계층형 설정 구조
  - `~/.claude/settings.json`
  - `.claude/settings.json`
  - `.claude/settings.local.json`
- 프로젝트/사용자 범위의 서브에이전트를 Markdown frontmatter 기반으로 정의
- 에이전트별로 프롬프트, 모델, 도구, 권한, 훅, 격리 worktree 동작을 제어
- 훅을 주요 생명주기 표면으로 사용
  - 프롬프트 제출
  - 도구 실행
  - 설정 변경
  - 세션 이벤트
  - worktree 생성/삭제
  - MCP elicitation
- MCP를 핵심 확장 경계로 취급하고 `claude mcp serve`도 제공
- IDE 연동은 존재하지만 핵심 제품 모델은 아님

`dormammu`에 중요한 점:

- 확장성을 제품 계약의 일부로 다룬다
- 저장소 단위 설정이 중심이다
- 동작 커스터마이징이 선언적이고 범위가 분명하다

### OpenCode

OpenCode는 `dormammu`보다 범위가 훨씬 넓지만, 참고해야 할 핵심은 터미널 에이전트 코어 구조입니다.

관찰한 핵심 구조:

- 터미널 에이전트 코어는 `packages/opencode/src`에 집중되어 있음
- 저장소 로컬 확장은 `.opencode/` 아래에 존재
  - `agent/`
  - `command/`
  - `tool/`
  - `opencode.jsonc`
- 내장 에이전트 모드가 명시적임
  - `build`
  - `plan`
  - `general`
  - `explore`
- 권한은 `allow`, `deny`, `ask`로 타입화되어 평가됨
- 스킬은 프로젝트 설정, 사용자 디렉터리, 외부 `.claude`/`.agents` 트리에서 탐색됨
- worktree는 임시 셸 관례가 아니라 전용 서비스로 구현됨
- MCP, 플러그인, 세션, 저장소, 공유, provider adapter가 명확히 분리됨

`dormammu`에 중요한 점:

- 에이전트 프로필, 스킬, 권한, worktree를 런타임의 기본 개념으로 취급한다
- 코어 실행 엔진과 확장 표면의 경계가 분명하다
- 저장소 로컬 확장 모델이 구체적이고 재현 가능하다

### dormammu 현재 상태

로컬 `graphify` 분석에서 현재 핵심 허브는 다음과 같습니다.

- `AppConfig`
- `LoopRunner`
- `AgentsConfig`
- `SupervisorReport`
- `LoopRunRequest`
- `DaemonRunner`
- `StateRepository`
- `SupervisorCheck`
- `PipelineRunner`

이 의미는 다음과 같습니다.

- 오케스트레이션 중심은 이미 잘 잡혀 있다
- 설정, 루프 실행, 파이프라인 실행, 슈퍼비전, 데몬, 재개 가능한 상태 모델이 이미 존재한다
- 현재 부족한 부분은 오케스트레이션 자체보다 확장 구조의 제품화다

## dormammu에 적용할 항목

### 1. 타입화된 에이전트 프로필

`dormammu`는 현재의 역할별 설정 조각을 넘어서, 명확한 에이전트 프로필 계약을 가져야 합니다.

필수 기능:

- `plan`, `develop`, `test`, `review`, `commit` 같은 명명된 프로필
- 다음 항목에 대한 명시적 권한
  - 도구
  - 파일시스템 범위
  - 네트워크 사용
  - worktree 사용
- 프로필별 모델/CLI override
- 내장 기본값과 프로젝트 override 사이의 결정적 우선순위

중요한 이유:

- 이후 hooks, skills, MCP를 얹을 수 있는 안정된 기반이 된다
- `LoopRunner`, `PipelineRunner`, `CliAdapter`의 역할별 분기 로직을 줄일 수 있다

### 2. 사용자/프로젝트 에이전트 매니페스트

디스크에 저장되는 프로젝트 로컬, 사용자 로컬 에이전트 정의를 지원해야 합니다.

권장 형태:

- Markdown 또는 YAML 기반 매니페스트
- 프로젝트 공유용 경로
- 개인용 사용자 경로
- 매니페스트에 다음 정보 포함
  - 설명
  - 프롬프트
  - 권한
  - CLI override
  - 모델 선택
  - 선택적 스킬 목록

중요한 이유:

- Python 소스를 수정하지 않고도 프로젝트가 에이전트를 확장할 수 있어야 한다
- 현재 `agents/` 가이드 번들과도 잘 맞는다

### 3. 생명주기 훅

`dormammu`는 실행 생명주기 전반에 걸친 안전한 훅 시스템을 가져야 합니다.

초기 권장 훅 지점:

- 프롬프트 intake
- plan 시작
- stage 시작
- stage 완료
- 도구 실행
- 설정 변경
- final verification
- 세션 종료

권장 응답 모델:

- `allow`
- `deny`
- `warn`
- `annotate`
- `background_started`

중요한 이유:

- 저장소별 정책, 검증, 감사, 자동화를 런타임 내부 하드코딩 없이 붙일 수 있다
- Claude Code처럼 훅은 런타임이 안정화될수록 중요한 제품 표면이 된다

### 4. 관리되는 Worktree 격리 실행

위험도가 높거나 변경량이 큰 단계는 선택적으로 git worktree에서 실행할 수 있어야 합니다.

우선 적용 대상:

- developer 단계
- reviewer 재현 단계
- 실험성 기능 구현
- 충돌 없이 병렬 실행해야 하는 multi-agent 슬라이스

중요한 이유:

- 사용자 변경과 충돌할 가능성을 줄인다
- worktree 상태를 암묵적 셸 관례가 아니라 명시적이고 재개 가능한 상태로 만들 수 있다

### 5. 권한 인지형 스킬 탐색

현재도 스킬을 사용하고 있지만, 로딩과 노출 모델을 런타임의 1급 서브시스템으로 끌어올려야 합니다.

권장 기능:

- 프로젝트/사용자 로컬 스킬의 일관된 탐색
- 역할별 필터링
- 중복 이름 충돌 정책
- 로그와 운영자 상태에 노출
- 프로필별 preload/deny 지원

중요한 이유:

- 이 저장소에서는 스킬이 이미 작업 조직의 핵심이다
- OpenCode는 권한과 연결된 스킬 로딩이 얼마나 유용한지 보여준다

### 6. MCP를 1급 경계로 정식화

`dormammu`는 MCP를 설정과 런타임 경계에서 정식 개념으로 다뤄야 합니다.

권장 방향:

- 프로젝트 단위 MCP 서버 정의
- 에이전트별 MCP allowlist
- MCP 접근도 native tool과 동일한 권한/훅 계층을 거치게 구성
- 내부 stage 계약이 안정화된 뒤 `dormammu mcp serve` 검토

중요한 이유:

- Claude Code는 MCP를 제품 중심 기능으로 다룬다
- `dormammu`는 오케스트레이션 성격이 강하므로 도구 경계가 특히 중요하다

### 7. 타입화된 이벤트와 아티팩트 모델

현재의 휴리스틱 기반 stage 판단을 더 명시적인 이벤트/결과 모델로 바꿔야 합니다.

권장 범위:

- stage requested
- stage started
- stage finished
- hook blocked
- permission requested
- permission granted
- worktree created
- evaluator decided
- final verification passed/failed

중요한 이유:

- 정규식/텍스트 추론 의존도를 줄일 수 있다
- `LoopRunner`, `PipelineRunner`, `Supervisor`, daemon 흐름을 하나의 관찰 가능한 계약 아래 묶을 수 있다

### 8. 운영자용 Inspect / Bootstrap 명령

내부 구조를 CLI 명령으로 노출해야 합니다.

권장 명령:

- `inspect-agent`
- `inspect-skill`
- `inspect-hooks`
- `inspect-worktree`
- `inspect-state`
- `init-agent-files` 또는 동등한 명령

중요한 이유:

- 운영자가 `.dev/*.json`이나 소스를 직접 읽지 않고도 상태를 파악할 수 있어야 한다
- OpenCode의 bootstrap/관리 명령은 이 표면의 가치를 잘 보여준다

## 지금은 하지 않을 것

현재 제품 범위에서는 다음 항목을 권장하지 않습니다.

- 데스크톱 또는 웹 제어 화면
- 호스팅된 control plane 또는 클라우드 협업 계층
- hooks와 agent manifest가 안정화되기 전의 marketplace형 plugin 배포

이 항목들은 제품 명확성보다 표면적 복잡도를 더 빠르게 키웁니다.

## 개발 계획

### Phase 1. Agent Contract and Permission Model

목표:

- 안정적인 `AgentProfile` 스키마 정의
- 도구, 파일시스템, 네트워크, worktree 권한 모델링
- 기존 역할 기반 설정을 새 스키마로 매핑

산출물:

- 타입화된 스키마와 로더
- 설정 우선순위 규칙
- 현재 역할 기반 설정에서의 마이그레이션 경로
- 권한 평가 단위 테스트

### Phase 2. User and Project Agent Manifests

목표:

- 프로젝트/사용자 위치에서 에이전트 매니페스트 로딩
- 매니페스트와 내장 역할 기본값의 병합
- 잘못된 매니페스트에 대한 정확한 검증 오류 제공

산출물:

- 탐색 규칙
- 우선순위 정책
- 매니페스트 파서와 검증기
- 충돌/override 테스트

### Phase 3. Hook Runtime

목표:

- 먼저 동기 훅을 도입
- 구조화된 입력/출력 계약 유지
- blocking / non-blocking 결과를 모두 지원

산출물:

- hook 스키마
- hook 실행 러너
- 타입화된 결과 모델
- allow / deny / warn / annotation 테스트

### Phase 4. Worktree Isolation

목표:

- 선택된 stage에서 관리형 git worktree 지원
- worktree 상태를 기계 판독 가능한 상태에 기록
- resume / cleanup 동작을 결정적으로 유지

산출물:

- worktree 서비스 모듈
- create/list/reset/remove CLI 명령
- worktree 생명주기 통합 테스트

### Phase 5. Skill Discovery and Role-Aware Loading

목표:

- 프로젝트/사용자 로컬 스킬 탐색 방식 통일
- 역할별 스킬 필터링
- 로드된 스킬을 로그와 운영자 상태에 노출

산출물:

- discovery 서비스
- 충돌 처리 규칙
- 권한 인지형 필터링
- 중복 이름/누락 파일 테스트

### Phase 6. MCP Integration Surface

목표:

- MCP 서버 설정을 프로젝트/에이전트 계약 안에 포함
- MCP 접근을 권한 및 훅 계층과 연결
- 서버 미가용 시 명확하게 실패 보고

산출물:

- MCP 설정 스키마
- 런타임 adapter 경계
- 실패 보고 및 검증 테스트

### Phase 7. Event and Artifact Unification

목표:

- 전체 파이프라인 생명주기에 대해 타입화된 이벤트 발행
- 가능한 영역은 추론 대신 명시적 stage 결과 저장
- `.dev` 파일과 기계 진실 모델을 더 긴밀하게 정렬

산출물:

- stage result 스키마
- 통합 artifact writer
- loop/pipeline/supervisor/daemon 통합 테스트

### Phase 8. Operator UX and Bootstrap Commands

목표:

- inspect/bootstrap 명령 추가
- 상태 파악 비용을 source diving보다 낮게 만들기
- CLI-only, documentation-first 성격 유지

산출물:

- `inspect-*` 명령군
- 프로젝트 가이드 파일 bootstrap/init 명령
- 문서와 예시 업데이트

## 권장 구현 순서

1. Phase 1. Agent Contract and Permission Model
2. Phase 2. User and Project Agent Manifests
3. Phase 3. Hook Runtime
4. Phase 4. Worktree Isolation
5. Phase 5. Skill Discovery and Role-Aware Loading
6. Phase 6. MCP Integration Surface
7. Phase 7. Event and Artifact Unification
8. Phase 8. Operator UX and Bootstrap Commands

## 이 순서를 권장하는 이유

- 권한과 매니페스트가 먼저 안정화되어야 hooks, skills, MCP를 올바르게 통제할 수 있다
- worktree는 유용하지만 에이전트 계약이 없는 상태에서는 위험하다
- 이벤트 통합은 확장 표면을 먼저 만든 뒤에 해야 재설계를 한 번만 하면 된다

## 성공 기준

- Python 소스를 수정하지 않고도 프로젝트별 에이전트를 추가할 수 있다
- 위험한 stage를 격리된 worktree에서 실행하고 깨끗하게 복구할 수 있다
- hooks가 타입화되고 테스트 가능한 방식으로 실행을 차단하거나 주석을 남길 수 있다
- skills와 MCP 서버를 역할별로 노출하면서 전역 권한을 불필요하게 넓히지 않는다
- 확장성이 늘어나도 `.dev` 상태는 더 명시적이고 덜 휴리스틱해진다
