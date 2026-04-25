from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from dormammu.agent.permissions import (
    AgentPermissionPolicy,
    WorktreePermissionPolicy,
    merge_permission_policy,
)
from dormammu.agent.role_config import ROLE_NAMES, AgentsConfig, RoleAgentConfig
from dormammu.agent.role_taxonomy import ROLE_TAXONOMY

if TYPE_CHECKING:
    from dormammu.agent.manifest_loader import LoadedAgentDefinition

BUILTIN_PROFILE_SOURCE = "built_in"
CONFIGURED_PROFILE_SOURCE = "configured"
PROJECT_PROFILE_SOURCE = "project"
USER_PROFILE_SOURCE = "user"
PROFILE_RUNTIME_METADATA_KEY = "dormammu_runtime"


@dataclass(frozen=True, slots=True)
class AgentProfile:
    """Typed internal profile for role-backed agent execution."""

    name: str
    description: str
    source: str = BUILTIN_PROFILE_SOURCE
    prompt_body: str | None = None
    cli_override: Path | None = None
    model_override: str | None = None
    permission_policy: AgentPermissionPolicy = field(default_factory=AgentPermissionPolicy)
    preloaded_skills: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def resolve_cli(self, active_agent_cli: Path | None) -> Path | None:
        return self.cli_override if self.cli_override is not None else active_agent_cli

    @property
    def worktree_policy(self) -> WorktreePermissionPolicy:
        return self.permission_policy.worktree

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "prompt_body": self.prompt_body,
            "cli_override": str(self.cli_override) if self.cli_override is not None else None,
            "model_override": self.model_override,
            "permission_policy": self.permission_policy.to_dict(),
            "preloaded_skills": list(self.preloaded_skills),
            "metadata": dict(self.metadata),
        }


_ROLE_DESCRIPTIONS: dict[str, str] = {
    entry.name: entry.description for entry in ROLE_TAXONOMY
}

ROLE_TO_PROFILE_NAME: dict[str, str] = {role: role for role in ROLE_NAMES}


def built_in_permission_policy_for_role(role: str) -> AgentPermissionPolicy:
    if role not in ROLE_TO_PROFILE_NAME:
        raise ValueError(f"Unknown role: {role!r}. Valid roles: {ROLE_NAMES}")
    return AgentPermissionPolicy()


BUILTIN_AGENT_PROFILES: tuple[AgentProfile, ...] = tuple(
    AgentProfile(
        name=ROLE_TO_PROFILE_NAME[role],
        description=_ROLE_DESCRIPTIONS[role],
        permission_policy=built_in_permission_policy_for_role(role),
    )
    for role in ROLE_NAMES
)

_BUILTIN_PROFILES_BY_NAME: dict[str, AgentProfile] = {
    profile.name: profile for profile in BUILTIN_AGENT_PROFILES
}


def _role_override_present(role_config: RoleAgentConfig | None) -> bool:
    return role_config is not None and (
        role_config.cli is not None
        or role_config.model is not None
        or role_config.permission_policy is not None
    )


def profile_name_for_role(
    role: str,
    role_config: RoleAgentConfig | None = None,
) -> str:
    if role not in ROLE_TO_PROFILE_NAME:
        raise ValueError(f"Unknown role: {role!r}. Valid roles: {ROLE_NAMES}")
    if role_config is not None and role_config.profile is not None:
        return role_config.profile
    return ROLE_TO_PROFILE_NAME[role]


def built_in_profiles() -> tuple[AgentProfile, ...]:
    return BUILTIN_AGENT_PROFILES


def built_in_profile_for_role(role: str) -> AgentProfile:
    profile_name = profile_name_for_role(role)
    profile = _BUILTIN_PROFILES_BY_NAME.get(profile_name)
    if profile is None:
        raise ValueError(
            f"Role {role!r} maps to profile {profile_name!r}, "
            "but no built-in profile with that name is available."
        )
    return profile


def is_built_in_profile_name(profile_name: str) -> bool:
    return profile_name in _BUILTIN_PROFILES_BY_NAME


def role_requires_manifest_resolution(
    role: str,
    *,
    agents_config: AgentsConfig | None = None,
) -> bool:
    role_config = agents_config.for_role(role) if agents_config is not None else None
    return not is_built_in_profile_name(profile_name_for_role(role, role_config))


def profile_from_role_config(
    role: str,
    role_config: RoleAgentConfig | None,
    *,
    available_profiles: Mapping[str, AgentProfile] | None = None,
    manifest_definitions: Sequence["LoadedAgentDefinition"] = (),
) -> AgentProfile:
    base_profile_name = profile_name_for_role(role, role_config)
    catalog = (
        dict(available_profiles)
        if available_profiles is not None
        else available_profile_catalog(manifest_definitions=manifest_definitions)
    )
    base_profile = catalog.get(base_profile_name)
    if base_profile is None:
        raise ValueError(
            f"Role {role!r} maps to profile {base_profile_name!r}, "
            "but no effective profile with that name is available."
        )

    effective_profile = base_profile
    if _role_override_present(role_config):
        assert role_config is not None
        effective_profile = replace(
            base_profile,
            source=CONFIGURED_PROFILE_SOURCE,
            cli_override=role_config.cli if role_config.cli is not None else base_profile.cli_override,
            model_override=role_config.model if role_config.model is not None else base_profile.model_override,
            permission_policy=merge_permission_policy(
                base_profile.permission_policy,
                role_config.permission_policy,
            ),
        )

    runtime_metadata = _runtime_resolution_metadata(
        role=role,
        base_profile=base_profile,
        role_config=role_config,
        manifest_metadata=_manifest_metadata_by_profile_name(manifest_definitions).get(
            base_profile.name
        ),
    )
    metadata = dict(effective_profile.metadata)
    metadata[PROFILE_RUNTIME_METADATA_KEY] = runtime_metadata
    return replace(effective_profile, metadata=metadata)


def available_profile_catalog(
    *,
    manifest_definitions: Sequence["LoadedAgentDefinition"] = (),
) -> dict[str, AgentProfile]:
    profiles = {profile.name: profile for profile in built_in_profiles()}
    for definition in manifest_definitions:
        if definition.name in profiles:
            raise ValueError(
                "Manifest-backed profile "
                f"{definition.name!r} conflicts with an existing built-in profile name."
            )
        profiles[definition.name] = definition.to_profile()
    return profiles


def _manifest_metadata_by_profile_name(
    manifest_definitions: Sequence["LoadedAgentDefinition"],
) -> dict[str, dict[str, str]]:
    return {
        definition.name: {
            "manifest_scope": definition.manifest_scope,
            "manifest_path": str(definition.manifest_path),
        }
        for definition in manifest_definitions
    }


def _runtime_resolution_metadata(
    *,
    role: str,
    base_profile: AgentProfile,
    role_config: RoleAgentConfig | None,
    manifest_metadata: Mapping[str, str] | None,
) -> dict[str, object]:
    return {
        "runtime_role": role,
        "selected_profile_name": base_profile.name,
        "selected_profile_source": base_profile.source,
        "selected_via_role_config": (
            role_config.profile is not None if role_config is not None else False
        ),
        "role_overrides": {
            "cli": role_config.cli is not None if role_config is not None else False,
            "model": role_config.model is not None if role_config is not None else False,
            "permission_policy": (
                role_config.permission_policy is not None
                if role_config is not None
                else False
            ),
        },
        **(dict(manifest_metadata) if manifest_metadata is not None else {}),
    }


def resolve_agent_profile(
    role: str,
    *,
    agents_config: AgentsConfig | None = None,
    normalized_profiles: Mapping[str, AgentProfile] | None = None,
    manifest_definitions: Sequence["LoadedAgentDefinition"] = (),
) -> AgentProfile:
    return resolve_runtime_role_profile(
        role,
        agents_config=agents_config,
        normalized_profiles=normalized_profiles,
        manifest_definitions=manifest_definitions,
    )


def normalize_agent_profiles(
    *,
    agents_config: AgentsConfig | None = None,
    manifest_definitions: Sequence["LoadedAgentDefinition"] = (),
) -> dict[str, AgentProfile]:
    catalog = available_profile_catalog(manifest_definitions=manifest_definitions)
    profiles: dict[str, AgentProfile] = {}
    for role in ROLE_NAMES:
        role_config = agents_config.for_role(role) if agents_config is not None else None
        profiles[role] = profile_from_role_config(
            role,
            role_config,
            available_profiles=catalog,
            manifest_definitions=manifest_definitions,
        )
    return profiles


def resolve_runtime_role_profile(
    role: str,
    *,
    agents_config: AgentsConfig | None = None,
    normalized_profiles: Mapping[str, AgentProfile] | None = None,
    manifest_definitions: Sequence["LoadedAgentDefinition"] = (),
) -> AgentProfile:
    if role not in ROLE_TO_PROFILE_NAME:
        raise ValueError(f"Unknown role: {role!r}. Valid roles: {ROLE_NAMES}")

    if normalized_profiles is not None:
        profile = normalized_profiles.get(role)
        if profile is None:
            role_config = agents_config.for_role(role) if agents_config is not None else None
            profile_name = profile_name_for_role(role, role_config)
            raise ValueError(
                f"Role {role!r} maps to profile {profile_name!r}, "
                "but no effective profile with that name is available."
            )
        return profile

    role_config = agents_config.for_role(role) if agents_config is not None else None
    return profile_from_role_config(
        role,
        role_config,
        manifest_definitions=manifest_definitions,
    )
