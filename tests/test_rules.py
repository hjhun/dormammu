from __future__ import annotations

from pathlib import Path

from dormammu.daemon.rules import load_rule_text


def test_load_rule_text_falls_back_to_packaged_assets(tmp_path: Path) -> None:
    agents_dir = tmp_path / "global-agents"
    agents_dir.mkdir()

    text = load_rule_text(agents_dir, "refiner-runtime.md")

    assert "requirement refiner" in text
    assert "Pipeline Stage Protocol" in text
