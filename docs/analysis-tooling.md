# Analysis Tooling Runbook

This runbook keeps graphify output useful for architecture review without
treating generic AST symbols as product design centers.

## Rerun Graphify

The current corpus is this repository:

```bash
cd /home/hjhun/samba/github/dormammu
graphify update /home/hjhun/samba/github/dormammu
```

Primary outputs:

```text
/home/hjhun/samba/github/dormammu/graphify-out/GRAPH_REPORT.md
/home/hjhun/samba/github/dormammu/graphify-out/graph.json
/home/hjhun/samba/github/dormammu/graphify-out/graph.html
```

## Filter Generic Symbols

After every graphify update, generate a filtered review:

```bash
cd /home/hjhun/samba/github/dormammu
python3 scripts/graphify_review.py \
  --graph graphify-out/graph.json \
  --repo-root . \
  --output docs/graphify-review.md
```

The script demotes generic symbols such as `path()`, `str`, `load()`,
`to_dict()`, `from_dict()`, `from_path()`, and generic lifecycle method names
such as `run()` into a separate section. These nodes can explain AST extraction
behavior, but they should not drive product remediation priority.

## Architecture Review Criteria

Use graph degree as one signal, not as the decision. Prioritize a node only
when several of these signals point in the same direction:

| Signal | Why it matters |
|--------|----------------|
| Graph degree | Shows broad coupling or navigational centrality in graphify. |
| LOC | Large modules are costlier to reason about and change. |
| Test mentions | High mention count shows established behavioral contracts; low mention count on a central node suggests test risk. |
| Runtime area | Runtime-owned nodes under `backend/dormammu/` usually matter more than docs-only or test-only nodes. |
| User-facing ownership | CLI, daemon, Telegram, state, result, and config surfaces have higher regression impact. |

Review priority should favor high-degree runtime nodes with high LOC and either
high user-facing impact or weak test ownership. Generic nodes stay low priority
unless the actual implementation of that helper is itself the requested scope.

## Validation

For Phase 7 or later analysis-refresh work, run:

```bash
python3 -m py_compile scripts/graphify_review.py
pytest -q tests/test_graphify_review.py
graphify update /home/hjhun/samba/github/dormammu
python3 scripts/graphify_review.py \
  --graph graphify-out/graph.json \
  --repo-root . \
  --output docs/graphify-review.md
```
