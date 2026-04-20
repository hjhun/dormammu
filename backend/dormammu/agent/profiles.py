from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from dormammu.agent.permissions import (
    AgentPermissionPolicy,
    WorktreePermissionPolicy,
    merge_permission_policy,
)
from dormammu.agent.role_config import ROLE_NAMES, AgentsConfig, RoleAgentConfig

BUILTIN_PROFILE_SOURCE = "built_in"
CONFIGURED_PROFILE_SOURCE = "configured"
PROJECT_PROFILE_SOURCE = "project"
USER_PROFILE_SOURCE = "user"


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
    "refiner": "Refines the raw request into explicit implementation requirements.",
    "analyzer": "Analyzes a goals-scheduler prompt before planning begins.",
    "planner": "Plans the task and updates the operator-facing workflow state.",
    "designer": "Defines module boundaries, interfaces, and validation strategy for the slice.",
    "developer": "Implements the active product-code slice under supervisor control.",
    "tester": "Runs black-box validation against the observable behavior of the slice.",
    "reviewer": "Reviews changed code for regressions, bugs, and missing coverage.",
    "committer": "Prepares validated changes for version-control handoff.",
    "evaluator": "Evaluates checkpoint or final goal completion when configured.",
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


def profile_name_for_role(role: str) -> str:
    if role not in ROLE_TO_PROFILE_NAME:
        raise ValueError(f"Unknown role: {role!r}. Valid roles: {ROLE_NAMES}")
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


def profile_from_role_config(
    role: str,
    role_config: RoleAgentConfig | None,
) -> AgentProfile:
    base_profile = built_in_profile_for_role(role)
    if not _role_override_present(role_config):
        return base_profile
    assert role_config is not None
    return replace(
        base_profile,
        source=CONFIGURED_PROFILE_SOURCE,
        cli_override=role_config.cli,
        model_override=role_config.model,
        permission_policy=merge_permission_policy(
            base_profile.permission_policy,
            role_config.permission_policy,
        ),
    )


def resolve_agent_profile(
    role: str,
    *,
    agents_config: AgentsConfig | None = None,
    normalized_profiles: Mapping[str, AgentProfile] | None = None,
) -> AgentProfile:
    return resolve_runtime_role_profile(
        role,
        agents_config=agents_config,
        normalized_profiles=normalized_profiles,
    )


def normalize_agent_profiles(
    *,
    agents_config: AgentsConfig | None = None,
) -> dict[str, AgentProfile]:
    profiles: dict[str, AgentProfile] = {}
    for role in ROLE_NAMES:
        role_config = agents_config.for_role(role) if agents_config is not None else None
        profile = profile_from_role_config(role, role_config)
        if profile.name in profiles:
            raise ValueError(
                f"Duplicate effective profile name {profile.name!r} while normalizing roles."
            )
        profiles[profile.name] = profile
    return profiles


def resolve_runtime_role_profile(
    role: str,
    *,
    agents_config: AgentsConfig | None = None,
    normalized_profiles: Mapping[str, AgentProfile] | None = None,
) -> AgentProfile:
    if role not in ROLE_TO_PROFILE_NAME:
        raise ValueError(f"Unknown role: {role!r}. Valid roles: {ROLE_NAMES}")

    profile_name = ROLE_TO_PROFILE_NAME[role]
    profiles = (
        dict(normalized_profiles)
        if normalized_profiles is not None
        else normalize_agent_profiles(agents_config=agents_config)
    )
    profile = profiles.get(profile_name)
    if profile is None:
        raise ValueError(
            f"Role {role!r} maps to profile {profile_name!r}, "
            "but no effective profile with that name is available."
        )
    return profile
