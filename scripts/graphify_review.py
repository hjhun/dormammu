#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any


DEFAULT_GENERIC_SYMBOLS = frozenset(
    {
        "path",
        "path()",
        "str",
        "str()",
        "dict",
        "dict()",
        "list",
        "list()",
        "tuple",
        "tuple()",
        "set",
        "set()",
        "load",
        "load()",
        "from_dict",
        "from_dict()",
        ".from_dict()",
        "to_dict",
        "to_dict()",
        ".to_dict()",
        "from_path",
        "from_path()",
        "run",
        "run()",
        ".run()",
        "start",
        "start()",
        ".start()",
        "stop",
        "stop()",
        ".stop()",
        "get",
        "get()",
        ".get()",
        "set",
        "set()",
        ".set()",
        "read_text",
        "read_text()",
        "write_text",
        "write_text()",
    }
)


@dataclass(frozen=True, slots=True)
class GraphNodeReview:
    label: str
    node_id: str
    degree: int
    source_file: str | None
    loc: int
    test_mentions: int
    runtime_area: str
    generic_symbol: bool


def _normalize_symbol(label: str) -> str:
    return label.strip().lower()


def is_generic_symbol(label: str, extra_symbols: set[str] | None = None) -> bool:
    normalized = _normalize_symbol(label)
    symbols = set(DEFAULT_GENERIC_SYMBOLS)
    if extra_symbols:
        symbols.update(_normalize_symbol(item) for item in extra_symbols)
    if normalized in symbols:
        return True
    if normalized.startswith(".") and normalized[1:] in symbols:
        return True
    return False


def _node_id(node: dict[str, Any]) -> str:
    value = node.get("id")
    return str(value) if value is not None else str(node.get("label", ""))


def _node_label(node: dict[str, Any]) -> str:
    value = node.get("label")
    return str(value) if value is not None else _node_id(node)


def _degree_by_node(graph: dict[str, Any]) -> Counter[str]:
    degree: Counter[str] = Counter()
    for link in graph.get("links", []):
        if not isinstance(link, dict):
            continue
        source = link.get("source") or link.get("_src")
        target = link.get("target") or link.get("_tgt")
        if source is not None:
            degree[str(source)] += 1
        if target is not None:
            degree[str(target)] += 1
    return degree


def _line_count(path: Path | None) -> int:
    if path is None or not path.exists() or not path.is_file():
        return 0
    try:
        return len(path.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return 0


def _source_path(source_file: str | None, repo_root: Path | None) -> Path | None:
    if not source_file:
        return None
    path = Path(source_file)
    if path.is_absolute() or repo_root is None:
        return path
    return repo_root / path


def _label_search_token(label: str) -> str | None:
    token = label.strip().lstrip(".")
    token = re.sub(r"\(\)$", "", token)
    if not token or len(token) < 3:
        return None
    if not re.search(r"[A-Za-z_]", token):
        return None
    return token


def _test_mentions(repo_root: Path | None, label: str) -> int:
    token = _label_search_token(label)
    if repo_root is None or token is None:
        return 0
    tests_dir = repo_root / "tests"
    if not tests_dir.exists():
        return 0
    mentions = 0
    for path in tests_dir.rglob("test_*.py"):
        try:
            if token in path.read_text(encoding="utf-8", errors="replace"):
                mentions += 1
        except OSError:
            continue
    return mentions


def _runtime_area(source_file: str | None, repo_root: Path | None) -> str:
    if not source_file:
        return "unknown"
    path = Path(source_file)
    try:
        rel = path.resolve().relative_to(repo_root.resolve()) if repo_root else path
    except (OSError, ValueError):
        rel = path
    parts = rel.parts
    if not parts:
        return "unknown"
    if parts[0] == "tests":
        return "tests"
    if parts[0] == "docs":
        return "docs"
    if len(parts) >= 3 and parts[0] == "backend" and parts[1] == "dormammu":
        return parts[2] if len(parts) > 3 else "runtime"
    if parts[0] in {"agents", "config", "scripts"}:
        return parts[0]
    return "other"


def review_graph(
    graph: dict[str, Any],
    *,
    repo_root: Path | None = None,
    extra_generic_symbols: set[str] | None = None,
) -> list[GraphNodeReview]:
    degree = _degree_by_node(graph)
    reviews: list[GraphNodeReview] = []
    for node in graph.get("nodes", []):
        if not isinstance(node, dict):
            continue
        node_id = _node_id(node)
        label = _node_label(node)
        source_file = node.get("source_file")
        source_path = _source_path(str(source_file) if source_file else None, repo_root)
        reviews.append(
            GraphNodeReview(
                label=label,
                node_id=node_id,
                degree=degree[node_id],
                source_file=str(source_file) if source_file else None,
                loc=_line_count(source_path),
                test_mentions=_test_mentions(repo_root, label),
                runtime_area=_runtime_area(str(source_file) if source_file else None, repo_root),
                generic_symbol=is_generic_symbol(label, extra_generic_symbols),
            )
        )
    return sorted(reviews, key=lambda item: item.degree, reverse=True)


def _format_table(rows: list[GraphNodeReview], *, include_source: bool) -> str:
    headers = ["Rank", "Label", "Degree", "LOC", "Test mentions", "Runtime area"]
    if include_source:
        headers.append("Source")
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for idx, item in enumerate(rows, start=1):
        cells = [
            str(idx),
            f"`{item.label}`",
            str(item.degree),
            str(item.loc),
            str(item.test_mentions),
            item.runtime_area,
        ]
        if include_source:
            cells.append(item.source_file or "")
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_markdown(reviews: list[GraphNodeReview], *, limit: int) -> str:
    generic = [item for item in reviews if item.generic_symbol and item.degree > 0][:limit]
    candidates = [item for item in reviews if not item.generic_symbol and item.degree > 0][:limit]
    return "\n\n".join(
        [
            "# Graphify Review",
            "Generic AST symbols are demoted before architecture prioritization. "
            "Use the candidate table with LOC, test mentions, and runtime area instead "
            "of graph degree alone.",
            "## Demoted Generic Symbols",
            _format_table(generic, include_source=False) if generic else "_None found._",
            "## Architecture Review Candidates",
            _format_table(candidates, include_source=True) if candidates else "_None found._",
        ]
    ) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Post-process graphify graph.json for architecture review.")
    parser.add_argument("--graph", type=Path, required=True, help="Path to graphify graph.json.")
    parser.add_argument("--repo-root", type=Path, default=None, help="Repository root for LOC and test-mention hints.")
    parser.add_argument("--output", type=Path, default=None, help="Optional markdown output path.")
    parser.add_argument("--limit", type=int, default=10, help="Rows per output section.")
    parser.add_argument(
        "--generic-symbol",
        action="append",
        default=None,
        help="Additional symbol label to demote. Repeat for multiple labels.",
    )
    args = parser.parse_args(argv)

    graph = json.loads(args.graph.read_text(encoding="utf-8"))
    reviews = review_graph(
        graph,
        repo_root=args.repo_root,
        extra_generic_symbols=set(args.generic_symbol or ()),
    )
    markdown = render_markdown(reviews, limit=args.limit)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown, encoding="utf-8")
    else:
        print(markdown, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
