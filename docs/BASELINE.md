# Dormammu Development Baseline

작성일: 2026-04-25

## 목적

이 문서는 `docs/ROADMAP.md` Phase 0의 기준선이다. 이후 Phase 1-6의
리팩터링은 이 기준선을 먼저 통과해야 한다.

## 빠른 기준선

일상 개발 중 먼저 실행할 명령:

```bash
scripts/verify-baseline.sh quick
```

동일한 수동 명령:

```bash
scripts/verify-agents-sync.sh
pytest -q tests/test_packaging_sync.py tests/test_results.py tests/test_supervisor.py
```

이 기준선이 보호하는 영역:

- `agents/`와 `backend/dormammu/assets/agents/` guidance bundle 동기화
- `StageResult`, `RunResult`, verdict/status aggregation
- supervisor 완료 판정과 최근 false-failure 회귀 경로

## 전체 기준선

Phase 단위 변경을 마치기 전에 실행할 명령:

```bash
scripts/verify-baseline.sh full
```

동일한 수동 명령:

```bash
scripts/verify-agents-sync.sh
pytest -q tests/test_packaging_sync.py tests/test_results.py tests/test_supervisor.py
pytest -q
```

## CI 후보

가벼운 PR gate:

```bash
scripts/verify-baseline.sh quick
```

main branch 또는 release 전 gate:

```bash
scripts/verify-baseline.sh full
```

현재 `.github/workflows/release.yml`는 release artifact build만 담당한다.
별도 CI workflow를 추가할 때는 quick baseline을 PR/push에 먼저 붙이고,
full baseline은 main 또는 scheduled run으로 시작하는 것이 적절하다.

## graphify 분석 산출물

최근 분석 산출물:

```text
/home/hjhun/samba/github/dormammu/graphify-out/graph.html
/home/hjhun/samba/github/dormammu/graphify-out/GRAPH_REPORT.md
/home/hjhun/samba/github/dormammu/graphify-out/graph.json
```

해석 주의사항:

- `path()`, `str`, `.to_dict()`, `from_dict()` 같은 generic AST symbol은
  실제 아키텍처 중심축보다 과대평가될 수 있다.
- graph centrality만으로 우선순위를 정하지 않는다. LOC, 테스트 소유권,
  runtime ownership, 사용자-facing 영향도를 함께 본다.
- Phase 7 이후에는 `graphify update /home/hjhun/samba/github/dormammu`로
  변경된 구조를 다시 확인하고, `scripts/graphify_review.py`로
  `docs/graphify-review.md`를 갱신한다.
- 자세한 재실행 절차와 해석 기준은 `docs/analysis-tooling.md`를 따른다.

## 마지막 확인 결과

2026-04-25 Phase 7 완료 시 확인된 최신 기준선:

```text
scripts/verify-baseline.sh quick
```

결과:

```text
OK: agents/ and backend/dormammu/assets/agents/ are in sync.
41 passed in 0.77s
```

전체 기준선:

```text
scripts/verify-baseline.sh full
```

결과:

```text
OK: agents/ and backend/dormammu/assets/agents/ are in sync.
41 passed in 0.77s
1173 passed, 1 skipped, 2 subtests passed in 74.35s (0:01:14)
full pytest suite completed in 82s
```
