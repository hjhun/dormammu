from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from dormammu.agent.permissions import (
    AgentPermissionPolicy,
    WorktreePermissionPolicy,
    merge_permission_policy,
)
from dormammu.agent.role_config import ROLE_NAMES, AgentsConfig, RoleAgentConfig

BUILTIN_PROFILE_SOURCE = "built_in"
CONFIGURED_PROFILE_SOURCE = "configured"


@dataclass(frozen=True, slots=True)
class AgentProfile:
    """Typed internal profile for role-backed agent execution."""

    name: str
    description: str
    source: str = BUILTIN_PROFILE_SOURCE
    cli_override: Path | None = None
    model_override: str | None = None
    permission_policy: AgentPermissionPolicy = field(default_factory=AgentPermissionPolicy)

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
            "cli_override": str(self.cli_override) if self.cli_override is not None else None,
            "model_override": self.model_override,
            "permission_policy": self.permission_policy.to_dict(),
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
    return _BUILTIN_PROFILES_BY_NAME[profile_name_for_role(role)]


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
) -> AgentProfile:
    role_config = agents_config.for_role(role) if agents_config is not None else None
    return profile_from_role_config(role, role_config)


def normalize_agent_profiles(
    *,
    agents_config: AgentsConfig | None = None,
) -> dict[str, AgentProfile]:
    return {
        role: resolve_agent_profile(role, agents_config=agents_config)
        for role in ROLE_NAMES
    }
