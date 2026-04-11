# CLAUDE.md

## Project Overview

`dormammu`는 Python 기반 코딩 에이전트 루프 오케스트레이터입니다.

- CLI 전용 인터페이스 (Web UI 없음)
- `.dev/` 디렉토리 기반 Markdown 상태 관리
- 재개 가능한 실행 (resumable execution)
- 수퍼바이저 주도 검증

## Source Of Truth

다음 우선순위로 다음 작업을 결정한다:

1. 직접적인 사용자 요청
2. `.dev/PROJECT.md`
3. `.dev/ROADMAP.md`
4. 현재 `.dev` 실행 상태 파일
5. 현재 저장소 내용

## Skill Routing

모든 실질적인 구현 작업은 `agents/` 번들의 워크플로우 및 스킬을 통해 수행한다.

### 언제 어떤 스킬을 사용하는가

| 상황 | 사용할 워크플로우/스킬 |
|------|----------------------|
| 새 범위 시작 / 설계 결정 필요 | `agents/workflows/planning-design.md` |
| 구현 준비 완료 (코드 + 테스트) | `agents/workflows/develop-test-authoring.md` |
| 빌드/배포/검증/최종 확인 필요 | `agents/workflows/build-deploy-test-review.md` |
| 최종 검증 통과 후 커밋 준비 | `agents/workflows/cleanup-commit.md` |
| 멀티 단계 작업 또는 다음 워크플로우 불명확 | `agents/skills/supervising-agent/SKILL.md` |

### 스킬 경로 참조

- Planning: `agents/skills/planning-agent/SKILL.md`
- Design: `agents/skills/designing-agent/SKILL.md`
- Development: `agents/skills/developing-agent/SKILL.md`
- Test Authoring: `agents/skills/test-authoring-agent/SKILL.md`
- Build and Deploy: `agents/skills/building-and-deploying/SKILL.md`
- Test and Review: `agents/skills/testing-and-reviewing/SKILL.md`
- Commit: `agents/skills/committing-agent/SKILL.md`
- Supervision: `agents/skills/supervising-agent/SKILL.md`

## Required Workflow Sequence

실질적인 작업은 반드시 이 순서를 따른다:

```
1. Plan        → agents/skills/planning-agent/SKILL.md
2. Design      → agents/skills/designing-agent/SKILL.md
3. Develop     → agents/skills/developing-agent/SKILL.md
4. Test Author → agents/skills/test-authoring-agent/SKILL.md
5. Build/Deploy → agents/skills/building-and-deploying/SKILL.md  (패키징 필요시)
6. Test/Review  → agents/skills/testing-and-reviewing/SKILL.md
7. Final Verify → supervising-agent 최종 검증 게이트
8. Commit       → agents/skills/committing-agent/SKILL.md
```

- Supervisor가 모든 멀티 단계 구현의 컨트롤러 역할을 한다.
- Design 이후 Develop과 Test Authoring은 병렬 트랙으로 진행한다.
- 검증은 활성 구현 슬라이스가 완료된 후에만 실행한다.
- 기본 검증 범위: 단위 테스트 + 통합 테스트. 시스템 테스트는 명시적으로 요청된 경우에만 추가.

## Phase Gate Rules (Supervisor 전환 조건)

각 단계 전환은 증거가 있어야 한다:

- `planning → design`: tasks가 존재하고 다음 액션이 명확할 때
- `design → develop`: 활성 범위에 대한 인터페이스 또는 결정이 존재할 때
- `develop → test_author`: 의도한 파일에 제품 코드 변경이 있을 때
- `test_author → build`: 단위/통합 테스트 코드가 존재할 때
- `test_review → final_verify`: 실행된 검증에 명확한 결과가 있을 때
- `final_verify → commit`: 완료된 슬라이스가 최종 운영 관점 검증을 통과했을 때
- `commit`: diff 범위와 검증 모두 버전 관리를 지지할 때

작성된 테스트 코드만으로는 test_author → test_review 전환을 허용하지 않는다. 실행 증거가 필요하다.

## `.dev` State Management

워크플로우 진행 중 다음 파일을 항상 동기화한다:

| 파일 | 역할 |
|------|------|
| `.dev/DASHBOARD.md` | 현재 진행 상황, 활성 단계, 다음 액션, 리스크 |
| `.dev/PLAN.md` | 현재 프롬프트 기반 단계별 체크리스트 (`[ ] Phase N. <title>`) |
| `.dev/TASKS.md` | 현재 범위의 개발 항목 |
| `.dev/workflow_state.json` | 기계 상태 (진실의 근원) |
| `.dev/session.json` | 세션 컨텍스트 |
| `.dev/logs/` | 실행 로그 |

- `.dev/workflow_state.json`이 기계 진실(machine truth)이고 Markdown 파일은 운영자 대면 상태다.
- `PLAN.md`의 체크리스트 형식: 미완료 `[ ] Phase N. <title>`, 완료 `[O] Phase N. <title>`

## Resume Behavior

작업 중단 후 재개 시:

1. 현재 `.dev` 상태 읽기
2. dashboard, tasks, machine state 일치 여부 확인
3. 가장 이른 불확실 단계 식별
4. 나중 단계가 유효하다고 가정하지 말고 해당 단계부터 재개

## Roadmap Priority

사용자가 우선순위를 변경하지 않는 한 이 순서로 실행:

1. Phase 1. Core Foundation and Repository Bootstrap
2. Phase 2. `.dev` State Model and Template Generation
3. Phase 3. Agent CLI Adapter and Single-Run Execution
4. Phase 4. Supervisor Validation, Continuation Loop, and Resume
5. Phase 5. CLI Operator Experience and Progress Visibility
6. Phase 6. Installer, Commands, and Environment Diagnostics
7. Phase 7. Hardening, Multi-Session, and Productization

## Default Agent Posture

이 저장소에서 작업할 때:

- 활성 단계를 명시적으로 표시한다
- 해당 단계의 매핑된 워크플로우 스킬을 사용한다
- 핸드오프 또는 협업이 필요할 때 인접 워크플로우 스킬을 참조한다
- Supervisor가 단계 전환을 결정한다
- 진행 상황을 `.dev`에서 가시적으로 유지한다
- 의미론적 판단 전에 결정론적 검사를 우선한다
- 매 단계마다 재개 가능성을 보존한다
