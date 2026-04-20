from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from dormammu.agent.permissions import (
    AgentPermissionPolicyOverride,
    merge_permission_policy_override,
    parse_permission_policy_override,
)

ROLE_NAMES: tuple[str, ...] = (
    "refiner",
    "analyzer",   # goals-scheduler path only (not used in the interactive pipeline)
    "planner",
    "designer",   # aligns with designing-agent skill and designer-runtime.md rule
    "developer",
    "tester",
    "reviewer",
    "committer",
    "evaluator",
)


@dataclass(frozen=True, slots=True)
class RoleAgentConfig:
    """Agent CLI and model configuration for a single pipeline role.

    ``profile=None`` means use the built-in base profile mapped to the runtime
    role. When set, the runtime selects that named profile first and then
    applies any role-level CLI/model/permission overrides on top.
    ``cli=None`` means inherit from ``active_agent_cli`` at call time.
    ``model=None`` means use the CLI's default model (no ``--model`` flag).
    """

    profile: str | None = None
    cli: Path | None = None
    model: str | None = None
    permission_policy: AgentPermissionPolicyOverride | None = None

    def resolve_cli(self, active_agent_cli: Path | None) -> Path | None:
        """Return the effective CLI path.

        Priority:
        1. ``self.cli`` — role-specific explicit setting
        2. ``active_agent_cli`` — global AppConfig fallback
        """
        return self.cli if self.cli is not None else active_agent_cli

    def to_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "cli": str(self.cli) if self.cli is not None else None,
            "model": self.model,
            "permission_policy": (
                self.permission_policy.to_dict()
                if self.permission_policy is not None
                else None
            ),
        }


@dataclass(frozen=True, slots=True)
class AgentsConfig:
    """Pipeline role agent configurations for all pipeline roles."""

    refiner: RoleAgentConfig = RoleAgentConfig()
    analyzer: RoleAgentConfig = RoleAgentConfig()
    planner: RoleAgentConfig = RoleAgentConfig()
    designer: RoleAgentConfig = RoleAgentConfig()
    developer: RoleAgentConfig = RoleAgentConfig()
    tester: RoleAgentConfig = RoleAgentConfig()
    reviewer: RoleAgentConfig = RoleAgentConfig()
    committer: RoleAgentConfig = RoleAgentConfig()
    evaluator: RoleAgentConfig = RoleAgentConfig()

    def for_role(self, role: str) -> RoleAgentConfig:
        """Return the config for the given role name."""
        if role not in ROLE_NAMES:
            raise ValueError(f"Unknown role: {role!r}. Valid roles: {ROLE_NAMES}")
        return getattr(self, role)

    def to_dict(self) -> dict[str, object]:
        return {role: getattr(self, role).to_dict() for role in ROLE_NAMES}


def merge_role_agent_config(
    base: RoleAgentConfig,
    override: RoleAgentConfig,
) -> RoleAgentConfig:
    return RoleAgentConfig(
        profile=override.profile if override.profile is not None else base.profile,
        cli=override.cli if override.cli is not None else base.cli,
        model=override.model if override.model is not None else base.model,
        permission_policy=merge_permission_policy_override(
            base.permission_policy,
            override.permission_policy,
        ),
    )


def merge_agents_config(
    base: AgentsConfig | None,
    override: AgentsConfig | None,
) -> AgentsConfig | None:
    if base is None:
        return override
    if override is None:
        return base
    return AgentsConfig(
        **{
            role: merge_role_agent_config(base.for_role(role), override.for_role(role))
            for role in ROLE_NAMES
        }
    )


def _parse_role_agent_config(
    value: Any,
    *,
    role: str,
    config_path: Path | None,
) -> RoleAgentConfig:
    if value is None:
        return RoleAgentConfig()
    source = str(config_path) if config_path is not None else "dormammu.json"
    if not isinstance(value, Mapping):
        raise RuntimeError(f"agents.{role} must be a JSON object in {source}")

    profile_raw = value.get("profile")
    profile: str | None = None
    if profile_raw is not None:
        if not isinstance(profile_raw, str) or not profile_raw.strip():
            raise RuntimeError(
                f"agents.{role}.profile must be a non-empty string in {source}"
            )
        profile = profile_raw.strip()

    cli_raw = value.get("cli")
    cli: Path | None = None
    if cli_raw is not None:
        if not isinstance(cli_raw, str) or not cli_raw.strip():
            raise RuntimeError(
                f"agents.{role}.cli must be a non-empty string in {source}"
            )
        raw = cli_raw.strip()
        candidate = Path(raw).expanduser()
        config_dir = config_path.parent if config_path is not None else None
        if candidate.is_absolute():
            cli = candidate
        elif config_dir is not None and ("/" in raw or raw.startswith(".")):
            cli = (config_dir / candidate).resolve()
        else:
            cli = candidate

    model_raw = value.get("model")
    model: str | None = None
    if model_raw is not None:
        if not isinstance(model_raw, str) or not model_raw.strip():
            raise RuntimeError(
                f"agents.{role}.model must be a non-empty string in {source}"
            )
        model = model_raw.strip()

    permission_policy_raw = value.get("permission_policy")
    permission_policy: AgentPermissionPolicyOverride | None = None
    if permission_policy_raw is not None:
        permission_policy = parse_permission_policy_override(
            permission_policy_raw,
            config_root=config_path.parent if config_path is not None else None,
            field_name=f"agents.{role}.permission_policy",
            source=source,
        )

    return RoleAgentConfig(
        profile=profile,
        cli=cli,
        model=model,
        permission_policy=permission_policy,
    )


def parse_agents_config(
    value: Any,
    *,
    config_path: Path | None,
) -> AgentsConfig | None:
    """Parse the ``agents`` section of dormammu.json.

    Returns ``None`` when the section is absent (callers fall back to
    ``active_agent_cli`` for every role).  Returns an :class:`AgentsConfig`
    with :class:`RoleAgentConfig` defaults for any omitted roles.
    """
    if value is None:
        return None
    source = str(config_path) if config_path is not None else "dormammu.json"
    if not isinstance(value, Mapping):
        raise RuntimeError(f"agents must be a JSON object in {source}")

    return AgentsConfig(
        **{
            role: _parse_role_agent_config(
                value.get(role), role=role, config_path=config_path
            )
            for role in ROLE_NAMES
        }
    )
