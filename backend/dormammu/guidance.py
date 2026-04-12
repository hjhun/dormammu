from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

from dormammu.config import AppConfig


def _normalize_path(path: Path, *, repo_root: Path) -> Path:
    candidate = path.expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (repo_root / candidate).resolve()


def _has_content(path: Path) -> bool:
    return path.exists() and path.is_file() and bool(path.read_text(encoding="utf-8").strip())


def _display_path(path: Path, *, repo_root: Path) -> str:
    try:
        return path.relative_to(repo_root).as_posix()
    except ValueError:
        return str(path)


def resolve_guidance_files(
    config: AppConfig,
    *,
    explicit_paths: Sequence[Path] | None = None,
) -> tuple[Path, ...]:
    if explicit_paths is None and config.guidance_files:
        configured = tuple(path for path in config.guidance_files if _has_content(path))
        if configured:
            return configured

    resolved_explicit = tuple(
        _normalize_path(path, repo_root=config.repo_root)
        for path in (explicit_paths or ())
    )
    explicit_with_content = tuple(path for path in resolved_explicit if _has_content(path))
    if explicit_with_content:
        return explicit_with_content

    repo_candidates = (
        config.repo_root / "AGENTS.md",
        config.repo_root / "agents" / "AGENTS.md",
    )
    repo_files = tuple(path for path in repo_candidates if _has_content(path))
    if repo_files:
        return repo_files

    fallback_candidates = [config.agents_dir / "AGENTS.md"]
    fallback_candidates.extend(config.default_guidance_files)
    fallback_files: list[Path] = []
    for candidate in fallback_candidates:
        if _has_content(candidate) and candidate not in fallback_files:
            fallback_files.append(candidate)
    return tuple(fallback_files)


def describe_guidance_files(paths: Iterable[Path], *, repo_root: Path) -> tuple[str, ...]:
    return tuple(_display_path(path, repo_root=repo_root) for path in paths)


def build_guidance_prompt(
    prompt_text: str,
    *,
    guidance_files: Sequence[Path],
    repo_root: Path,
    patterns_text: str | None = None,
) -> str:
    if not guidance_files and not patterns_text:
        return prompt_text

    sections: list[str] = []

    if guidance_files:
        sections.extend([
            "Follow the guidance files below before making changes.",
            "Treat them as required instructions for this run.",
            "",
            "Guidance files:",
        ])
        for path in guidance_files:
            sections.append(f"- {_display_path(path, repo_root=repo_root)}")

        for path in guidance_files:
            sections.extend(
                [
                    "",
                    f"Begin guidance from {_display_path(path, repo_root=repo_root)}:",
                    path.read_text(encoding="utf-8").rstrip(),
                    f"End guidance from {_display_path(path, repo_root=repo_root)}.",
                ]
            )

    if patterns_text and patterns_text.strip():
        _default_placeholder = "(no patterns recorded yet"
        if _default_placeholder not in patterns_text:
            sections.extend([
                "",
                "Codebase patterns accumulated from prior agent runs (.dev/PATTERNS.md):",
                "Review these before making changes, and append any new patterns you discover.",
                "",
                patterns_text.rstrip(),
                "",
                "End of codebase patterns.",
            ])

    sections.extend(["", "Task prompt:", prompt_text])
    return "\n".join(sections).strip() + "\n"
