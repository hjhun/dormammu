# Runner Result Semantics

작성일: 2026-04-25

## 목적

Runner별 완료, 실패, blocked, manual review 의미를 한 곳에서 유지한다.
`runner_results.py`는 runner orchestration code 밖에서 `LoopRunResult`를
조립하는 공통 helper 계층이다.

## 공통 Helper

| Helper | 역할 |
| --- | --- |
| `finalize_loop_run_result()` | stage 결과를 집계해 최종 loop-compatible run result를 만든다. |
| `terminal_loop_result()` | blocked, failed, manual_review_needed 같은 조기 종료 result를 같은 형태로 만든다. |

`PipelineRunner`는 stage ordering과 re-entry orchestration에 집중하고,
최종 status/verdict/summary/artifact 집계는 이 helper에 위임한다.

## Result 의미

- `completed`: runner 자체가 끝났고 최신 stage result들이 terminal 상태를
  설명한다. domain verdict는 `supervisor_verdict`에 따로 남는다.
- `failed`: stage가 실패했거나 retry 가능한 negative verdict가 남아 더
  진행할 수 없다.
- `blocked`: runtime hook, CLI availability, permission gate 등 외부 조건이
  진행을 막았다.
- `manual_review_needed`: stage iteration budget을 소진했거나 명시적으로
  operator review가 필요하다.

## Artifact 규칙

최종 result artifact 목록은 latest stage attempt 기준으로 모은다. 같은 stage
key의 이전 실패 artifact는 top-level result artifact에서 제외하되, 각 stage
result에는 개별 evidence로 남을 수 있다.

## Migration Rule

새 runner가 `LoopRunResult` 호환 결과를 만들어야 한다면:

- stage ordering과 retry orchestration은 runner 내부에 둔다
- status/verdict/summary/artifact 집계는 `runner_results.py`를 사용한다
- stage-specific report persistence와 lifecycle event emission은 runner가
  소유하되, final run result 조립은 helper를 거친다
