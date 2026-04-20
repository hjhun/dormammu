from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from pathlib import Path
import tempfile


_EXTERNAL_WORKSPACE_SEGMENT = "_external"
_WORKSPACE_DIRNAME = "workspace"
_RESULTS_DIRNAME = "results"
_DEV_DIRNAME = ".dev"
_TMP_DIRNAME = ".tmp"
_FALLBACK_HASH_LENGTH = 12


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _safe_path_label(path: Path) -> str:
    candidate = path.name or "project"
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", candidate).strip("-._")
    return normalized or "project"


@dataclass(frozen=True, slots=True)
class WorkspacePaths:
    repo_root: Path
    repo_dev_dir: Path
    home_dir: Path
    global_home_dir: Path
    workspace_root: Path
    workspace_project_root: Path
    base_dev_dir: Path
    dev_dir: Path
    logs_dir: Path
    sessions_dir: Path
    tmp_dir: Path
    results_dir: Path

    def runtime_path_prompt(self) -> str:
        lines = [
            f"- Real project root: `{self.repo_root}`",
            f"- Repository-local project docs root: `{self.repo_dev_dir}`",
            f"- Operational state directory (`.dev` in workflow docs): `{self.base_dev_dir}`",
            f"- Managed temporary directory (`.tmp`): `{self.tmp_dir}`",
            f"- Result reports directory: `{self.results_dir}`",
            (
                "Interpret any `.dev/...` reference in prompts and workflow guidance as "
                "relative to the operational state directory above, not to the real project root."
            ),
        ]
        return "\n".join(lines)


def resolve_workspace_project_root(
    *,
    repo_root: Path,
    home_dir: Path,
    global_home_dir: Path,
) -> Path:
    repo_root = repo_root.resolve()
    home_dir = home_dir.resolve()
    workspace_root = (global_home_dir / _WORKSPACE_DIRNAME).resolve()

    if _is_relative_to(repo_root, home_dir):
        relative_repo_path = repo_root.relative_to(home_dir)
        if relative_repo_path.parts:
            return workspace_root / relative_repo_path
        return workspace_root / _safe_path_label(repo_root)

    digest = hashlib.sha256(str(repo_root).encode("utf-8")).hexdigest()[:_FALLBACK_HASH_LENGTH]
    label = _safe_path_label(repo_root)
    return workspace_root / _EXTERNAL_WORKSPACE_SEGMENT / f"{label}-{digest}"


def resolve_workspace_paths(
    *,
    repo_root: Path,
    home_dir: Path,
    global_home_dir: Path,
) -> WorkspacePaths:
    repo_root = repo_root.resolve()
    repo_dev_dir = repo_root / _DEV_DIRNAME
    workspace_root = (global_home_dir / _WORKSPACE_DIRNAME).resolve()
    workspace_project_root = resolve_workspace_project_root(
        repo_root=repo_root,
        home_dir=home_dir,
        global_home_dir=global_home_dir,
    )
    base_dev_dir = workspace_project_root / _DEV_DIRNAME
    dev_dir = base_dev_dir
    return WorkspacePaths(
        repo_root=repo_root,
        repo_dev_dir=repo_dev_dir,
        home_dir=home_dir.resolve(),
        global_home_dir=global_home_dir.resolve(),
        workspace_root=workspace_root,
        workspace_project_root=workspace_project_root,
        base_dev_dir=base_dev_dir,
        dev_dir=dev_dir,
        logs_dir=dev_dir / "logs",
        sessions_dir=dev_dir / "sessions",
        tmp_dir=workspace_project_root / _TMP_DIRNAME,
        results_dir=(global_home_dir / _RESULTS_DIRNAME).resolve(),
    )


def create_temp_text_file(
    tmp_dir: Path,
    *,
    prefix: str,
    suffix: str,
    content: str,
) -> Path:
    tmp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=suffix,
        prefix=prefix,
        dir=tmp_dir,
        delete=False,
        encoding="utf-8",
    ) as handle:
        handle.write(content)
        return Path(handle.name)


def remove_temp_path(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink(missing_ok=True)
    except OSError:
        return
