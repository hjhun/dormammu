from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


def load_rule_text(agents_dir: Path, rule_name: str) -> str:
    """Load a packaged runtime rule from ``agents/rules``."""
    tried_paths: list[Path] = []
    for rule_path in _candidate_rule_paths(agents_dir, rule_name):
        tried_paths.append(rule_path)
        try:
            return rule_path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
    searched = ", ".join(str(path) for path in tried_paths)
    raise RuntimeError(f"Runtime rule file was not found: {searched}")


def load_agent_guidance_text(agents_dir: Path, relative_path: str) -> str:
    """Load a guidance document from ``agents/`` or the packaged asset mirror."""
    tried_paths: list[Path] = []
    for candidate in _candidate_agent_paths(agents_dir, relative_path):
        tried_paths.append(candidate)
        try:
            return candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
    searched = ", ".join(str(path) for path in tried_paths)
    raise RuntimeError(f"Agent guidance file was not found: {searched}")


def build_rule_prompt(
    rule_text: str,
    *,
    sections: Iterable[tuple[str, str | None]] = (),
) -> str:
    """Append markdown sections onto a stable rule contract."""
    parts: list[str] = [rule_text.strip()]
    for title, body in sections:
        if body is None:
            continue
        content = body.strip()
        if not content:
            continue
        parts.extend(["", f"# {title}", "", content])
    return "\n".join(parts).rstrip() + "\n"


def _candidate_rule_paths(agents_dir: Path, rule_name: str) -> tuple[Path, ...]:
    packaged_agents_dir = Path(__file__).resolve().parents[1] / "assets" / "agents"
    candidates: list[Path] = [agents_dir / "rules" / rule_name]
    packaged_rule_path = packaged_agents_dir / "rules" / rule_name
    if packaged_rule_path not in candidates:
        candidates.append(packaged_rule_path)
    return tuple(candidates)


def _candidate_agent_paths(agents_dir: Path, relative_path: str) -> tuple[Path, ...]:
    packaged_agents_dir = Path(__file__).resolve().parents[1] / "assets" / "agents"
    candidates: list[Path] = [agents_dir / relative_path]
    packaged_path = packaged_agents_dir / relative_path
    if packaged_path not in candidates:
        candidates.append(packaged_path)
    return tuple(candidates)
