from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from dormammu._utils import iso_now as _iso_now


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    kind: str
    path: Path
    label: str | None = None
    content_type: str | None = None
    created_at: str | None = None
    run_id: str | None = None
    role: str | None = None
    stage_name: str | None = None
    session_id: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_path(
        cls,
        *,
        kind: str,
        path: Path | str,
        label: str | None = None,
        content_type: str | None = None,
        created_at: str | None = None,
        run_id: str | None = None,
        role: str | None = None,
        stage_name: str | None = None,
        session_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ArtifactRef:
        return cls(
            kind=kind,
            path=Path(path),
            label=label,
            content_type=content_type,
            created_at=created_at,
            run_id=run_id,
            role=role,
            stage_name=stage_name,
            session_id=session_id,
            metadata=dict(metadata or {}),
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any] | None) -> ArtifactRef | None:
        if not isinstance(payload, Mapping):
            return None
        kind = payload.get("kind")
        path = payload.get("path")
        if not isinstance(kind, str) or not kind.strip():
            return None
        if not isinstance(path, str) or not path.strip():
            return None
        metadata = payload.get("metadata")
        return cls.from_path(
            kind=kind,
            path=path,
            label=payload.get("label") if isinstance(payload.get("label"), str) else None,
            content_type=(
                payload.get("content_type")
                if isinstance(payload.get("content_type"), str)
                else None
            ),
            created_at=(
                payload.get("created_at") if isinstance(payload.get("created_at"), str) else None
            ),
            run_id=payload.get("run_id") if isinstance(payload.get("run_id"), str) else None,
            role=payload.get("role") if isinstance(payload.get("role"), str) else None,
            stage_name=(
                payload.get("stage_name") if isinstance(payload.get("stage_name"), str) else None
            ),
            session_id=(
                payload.get("session_id") if isinstance(payload.get("session_id"), str) else None
            ),
            metadata=metadata if isinstance(metadata, Mapping) else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "path": str(self.path),
            "label": self.label,
            "content_type": self.content_type,
            "created_at": self.created_at,
            "run_id": self.run_id,
            "role": self.role,
            "stage_name": self.stage_name,
            "session_id": self.session_id,
            "metadata": dict(self.metadata),
        }


class ArtifactWriter:
    def __init__(
        self,
        *,
        base_dir: Path,
        logs_dir: Path | None = None,
        now_factory: Callable[[], str] | None = None,
        default_run_id: str | None = None,
        default_role: str | None = None,
        default_stage_name: str | None = None,
        default_session_id: str | None = None,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.logs_dir = Path(logs_dir) if logs_dir is not None else self.base_dir / "logs"
        self._now_factory = now_factory or _iso_now
        self._default_run_id = default_run_id
        self._default_role = default_role
        self._default_stage_name = default_stage_name
        self._default_session_id = default_session_id

    def bind(
        self,
        *,
        run_id: str | None = None,
        role: str | None = None,
        stage_name: str | None = None,
        session_id: str | None = None,
    ) -> ArtifactWriter:
        return ArtifactWriter(
            base_dir=self.base_dir,
            logs_dir=self.logs_dir,
            now_factory=self._now_factory,
            default_run_id=run_id if run_id is not None else self._default_run_id,
            default_role=role if role is not None else self._default_role,
            default_stage_name=(
                stage_name if stage_name is not None else self._default_stage_name
            ),
            default_session_id=(
                session_id if session_id is not None else self._default_session_id
            ),
        )

    def logs_path(self, filename: str) -> Path:
        return self.logs_dir / filename

    def state_path(self, filename: str) -> Path:
        return self.base_dir / filename

    def stage_report_path(self, *, role: str, stem: str, date_str: str) -> Path:
        return self.logs_path(f"{date_str}_{role}_{stem}.md")

    def checkpoint_report_path(
        self,
        *,
        checkpoint_kind: str,
        stem: str,
        date_str: str,
    ) -> Path:
        return self.logs_path(f"check_{checkpoint_kind}_{stem}_{date_str}.md")

    def evaluator_report_path(self, *, stem: str, date_str: str) -> Path:
        return self.logs_path(f"{date_str}_evaluator_{stem}.md")

    def supervisor_report_path(self) -> Path:
        return self.state_path("supervisor_report.md")

    def continuation_prompt_path(self) -> Path:
        return self.state_path("continuation_prompt.txt")

    def run_prompt_path(self, *, run_id: str) -> Path:
        return self.logs_path(f"{run_id}.prompt.txt")

    def run_stdout_path(self, *, run_id: str) -> Path:
        return self.logs_path(f"{run_id}.stdout.log")

    def run_stderr_path(self, *, run_id: str) -> Path:
        return self.logs_path(f"{run_id}.stderr.log")

    def run_metadata_path(self, *, run_id: str) -> Path:
        return self.logs_path(f"{run_id}.meta.json")

    def reference(
        self,
        *,
        kind: str,
        path: Path | str,
        label: str | None = None,
        content_type: str | None = None,
        created_at: str | None = None,
        run_id: str | None = None,
        role: str | None = None,
        stage_name: str | None = None,
        session_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ArtifactRef:
        return ArtifactRef.from_path(
            kind=kind,
            path=self._resolve_path(path),
            label=label,
            content_type=content_type,
            created_at=created_at,
            run_id=run_id if run_id is not None else self._default_run_id,
            role=role if role is not None else self._default_role,
            stage_name=(
                stage_name if stage_name is not None else self._default_stage_name
            ),
            session_id=(
                session_id if session_id is not None else self._default_session_id
            ),
            metadata=metadata,
        )

    def write_markdown_report(
        self,
        *,
        kind: str,
        markdown: str,
        path: Path | str,
        label: str | None = None,
        run_id: str | None = None,
        role: str | None = None,
        stage_name: str | None = None,
        session_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ArtifactRef:
        return self.write_text_output(
            kind=kind,
            text=markdown,
            path=path,
            label=label,
            content_type="text/markdown",
            run_id=run_id,
            role=role,
            stage_name=stage_name,
            session_id=session_id,
            metadata=metadata,
        )

    def write_text_output(
        self,
        *,
        kind: str,
        text: str,
        path: Path | str,
        label: str | None = None,
        content_type: str = "text/plain",
        run_id: str | None = None,
        role: str | None = None,
        stage_name: str | None = None,
        session_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ArtifactRef:
        created_at = self._now_factory()
        target_path = self._resolve_path(path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(text, encoding="utf-8")
        return self.reference(
            kind=kind,
            path=target_path,
            label=label,
            content_type=content_type,
            created_at=created_at,
            run_id=run_id,
            role=role,
            stage_name=stage_name,
            session_id=session_id,
            metadata=metadata,
        )

    def write_json_metadata(
        self,
        *,
        kind: str,
        payload: Any,
        path: Path | str,
        label: str | None = None,
        run_id: str | None = None,
        role: str | None = None,
        stage_name: str | None = None,
        session_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ArtifactRef:
        serialized = json.dumps(payload, indent=2, ensure_ascii=True) + "\n"
        return self.write_text_output(
            kind=kind,
            text=serialized,
            path=path,
            label=label,
            content_type="application/json",
            run_id=run_id,
            role=role,
            stage_name=stage_name,
            session_id=session_id,
            metadata=metadata,
        )

    def _resolve_path(self, path: Path | str) -> Path:
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        return self.base_dir / candidate
