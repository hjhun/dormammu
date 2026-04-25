from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "graphify_review.py"
spec = importlib.util.spec_from_file_location("graphify_review", SCRIPT)
assert spec is not None and spec.loader is not None
graphify_review = importlib.util.module_from_spec(spec)
sys.modules["graphify_review"] = graphify_review
spec.loader.exec_module(graphify_review)


def _graph() -> dict:
    return {
        "nodes": [
            {"id": "path", "label": "path()", "source_file": "backend/dormammu/config.py"},
            {"id": "app_config", "label": "AppConfig", "source_file": "backend/dormammu/config.py"},
            {"id": "runner", "label": "LoopRunner", "source_file": "backend/dormammu/loop_runner.py"},
        ],
        "links": [
            {"source": "path", "target": "app_config"},
            {"source": "path", "target": "runner"},
            {"source": "app_config", "target": "runner"},
        ],
    }


def test_generic_symbols_are_demoted_from_architecture_candidates(tmp_path: Path) -> None:
    repo = tmp_path
    source = repo / "backend" / "dormammu" / "config.py"
    source.parent.mkdir(parents=True)
    source.write_text("class AppConfig:\n    pass\n", encoding="utf-8")
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_config.py").write_text("from dormammu.config import AppConfig\n", encoding="utf-8")

    reviews = graphify_review.review_graph(_graph(), repo_root=repo)

    generic_labels = [item.label for item in reviews if item.generic_symbol]
    candidate_labels = [item.label for item in reviews if not item.generic_symbol]

    assert "path()" in generic_labels
    assert "path()" not in candidate_labels
    assert "AppConfig" in candidate_labels
    app_config = next(item for item in reviews if item.label == "AppConfig")
    assert app_config.test_mentions == 1
    assert app_config.runtime_area == "runtime"


def test_render_markdown_separates_demoted_symbols() -> None:
    reviews = graphify_review.review_graph(_graph())

    markdown = graphify_review.render_markdown(reviews, limit=5)

    assert "## Demoted Generic Symbols" in markdown
    assert "`path()`" in markdown
    assert "## Architecture Review Candidates" in markdown
    assert "`AppConfig`" in markdown


def test_analysis_tooling_runbook_documents_filter_command() -> None:
    text = (ROOT / "docs" / "analysis-tooling.md").read_text(encoding="utf-8")

    assert "graphify update /home/hjhun/samba/github/dormammu" in text
    assert "scripts/graphify_review.py" in text
    assert "--graph graphify-out/graph.json" in text
    assert "docs/graphify-review.md" in text
