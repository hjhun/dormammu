from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dormammu.agent.manifests import (
    AgentManifestDiscovery,
    AgentManifestError,
    DiscoveredAgentManifest,
    discover_agent_manifests,
)
from dormammu.agent.permissions import AgentPermissionPolicy
from dormammu.agent.profiles import AgentProfile

if TYPE_CHECKING:
    from dormammu.config import AppConfig


class AgentManifestLoadError(RuntimeError):
    """Raised when manifest discovery or runtime-definition loading fails."""


@dataclass(frozen=True, slots=True)
class LoadedAgentDefinition:
    """Runtime-ready custom agent definition loaded from a manifest."""

    name: str
    description: str
    prompt_body: str
    source: str
    manifest_scope: str
    manifest_path: Path
    cli_override: Path | None = None
    model_override: str | None = None
    permission_policy: AgentPermissionPolicy = field(default_factory=AgentPermissionPolicy)
    preloaded_skills: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_discovered_manifest(
        cls,
        discovered: DiscoveredAgentManifest,
    ) -> "LoadedAgentDefinition":
        manifest = discovered.manifest
        return cls(
            name=manifest.name,
            description=manifest.description,
            prompt_body=manifest.prompt,
            source=manifest.source,
            manifest_scope=discovered.scope,
            manifest_path=discovered.path,
            cli_override=manifest.cli_override,
            model_override=manifest.model_override,
            permission_policy=manifest.permission_policy,
            preloaded_skills=manifest.preloaded_skills,
            metadata=dict(manifest.metadata),
        )

    def to_profile(self) -> AgentProfile:
        return AgentProfile(
            name=self.name,
            description=self.description,
            source=self.source,
            prompt_body=self.prompt_body,
            cli_override=self.cli_override,
            model_override=self.model_override,
            permission_policy=self.permission_policy,
            preloaded_skills=self.preloaded_skills,
            metadata=dict(self.metadata),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "prompt_body": self.prompt_body,
            "source": self.source,
            "manifest_scope": self.manifest_scope,
            "manifest_path": str(self.manifest_path),
            "cli_override": str(self.cli_override) if self.cli_override is not None else None,
            "model_override": self.model_override,
            "permission_policy": self.permission_policy.to_dict(),
            "preloaded_skills": list(self.preloaded_skills),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class AgentManifestLoadResult:
    """Selected runtime definitions plus the discovery data used to load them."""

    discovery: AgentManifestDiscovery
    definitions: tuple[LoadedAgentDefinition, ...]

    def definitions_by_name(self) -> dict[str, LoadedAgentDefinition]:
        return {definition.name: definition for definition in self.definitions}

    def to_dict(self) -> dict[str, object]:
        return {
            "discovery": self.discovery.to_dict(),
            "definitions": [definition.to_dict() for definition in self.definitions],
        }


def load_agent_manifest_definitions(config: "AppConfig") -> AgentManifestLoadResult:
    """Load selected manifest-backed custom agent definitions for the runtime."""

    try:
        discovery = discover_agent_manifests(config)
        definitions = tuple(
            LoadedAgentDefinition.from_discovered_manifest(discovered)
            for discovered in discovery.selected
        )
        _validate_unique_definition_names(definitions)
    except AgentManifestError as exc:
        raise AgentManifestLoadError(str(exc)) from exc

    return AgentManifestLoadResult(
        discovery=discovery,
        definitions=definitions,
    )


def _validate_unique_definition_names(
    definitions: tuple[LoadedAgentDefinition, ...],
) -> None:
    seen: dict[str, Path] = {}
    for definition in definitions:
        existing_path = seen.get(definition.name)
        if existing_path is not None:
            raise AgentManifestError(
                "Duplicate loaded agent definition "
                f"{definition.name!r}: {existing_path} and {definition.manifest_path}. "
                "Loaded manifest definitions must have unique names."
            )
        seen[definition.name] = definition.manifest_path
