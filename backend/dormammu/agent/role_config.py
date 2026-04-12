from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

ROLE_NAMES: tuple[str, ...] = (
    "planner",
    "architect",
    "developer",
    "tester",
    "reviewer",
    "committer",
)


@dataclass(frozen=True, slots=True)
class RoleAgentConfig:
    """Agent CLI and model configuration for a single pipeline role.

    ``cli=None`` means inherit from ``active_agent_cli`` at call time.
    ``model=None`` means use the CLI's default model (no ``--model`` flag).
    """

    cli: Path | None = None
    model: str | None = None

    def resolve_cli(self, active_agent_cli: Path | None) -> Path | None:
        """Return the effective CLI path.

        Priority:
        1. ``self.cli`` — role-specific explicit setting
        2. ``active_agent_cli`` — global AppConfig fallback
        """
        return self.cli if self.cli is not None else active_agent_cli

    def to_dict(self) -> dict[str, object]:
        return {
            "cli": str(self.cli) if self.cli is not None else None,
            "model": self.model,
        }


@dataclass(frozen=True, slots=True)
class AgentsConfig:
    """Pipeline role agent configurations for all six roles."""

    planner: RoleAgentConfig = RoleAgentConfig()
    architect: RoleAgentConfig = RoleAgentConfig()
    developer: RoleAgentConfig = RoleAgentConfig()
    tester: RoleAgentConfig = RoleAgentConfig()
    reviewer: RoleAgentConfig = RoleAgentConfig()
    committer: RoleAgentConfig = RoleAgentConfig()

    def for_role(self, role: str) -> RoleAgentConfig:
        """Return the config for the given role name."""
        if role not in ROLE_NAMES:
            raise ValueError(f"Unknown role: {role!r}. Valid roles: {ROLE_NAMES}")
        return getattr(self, role)

    def to_dict(self) -> dict[str, object]:
        return {role: getattr(self, role).to_dict() for role in ROLE_NAMES}


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

    return RoleAgentConfig(cli=cli, model=model)


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
