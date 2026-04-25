from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from dormammu.mcp import EffectiveMcpServer, McpCatalog, McpProfileResolution
from dormammu.workspace import WorkspacePaths

if TYPE_CHECKING:
    from dormammu.agent.manifest_loader import AgentManifestLoadResult
    from dormammu.agent.profiles import AgentProfile
    from dormammu.agent.role_config import AgentsConfig
    from dormammu.config import AppConfig


PROJECT_AGENT_MANIFESTS_SUBDIR = Path(".dormammu") / "agent-manifests"
USER_AGENT_MANIFESTS_DIRNAME = "agent-manifests"


@dataclass(frozen=True, slots=True)
class ConfigAssetLayout:
    asset_root: Path
    templates_dir: Path
    agents_dir: Path
    project_agents_dir: Path
    user_agents_dir: Path
    built_in_agents_dir: Path
    project_skills_dir: Path
    user_skills_dir: Path
    built_in_skills_dir: Path
    project_agent_manifests_dir: Path
    user_agent_manifests_dir: Path
    default_guidance_files: tuple[Path, ...]


class ConfigAssetResolver:
    """Resolve package, project, and user guidance asset locations."""

    def __init__(
        self,
        *,
        root: Path,
        env: Mapping[str, str],
        global_home_dir: Path,
    ) -> None:
        self._root = root
        self._env = env
        self._global_home_dir = global_home_dir

    def resolve_layout(self) -> ConfigAssetLayout:
        asset_root = self.discover_asset_root()
        agents_dir = self.discover_agents_dir(asset_root=asset_root)
        project_agents_dir = self.project_agents_dir(self._root)
        user_agents_dir = self.user_agents_dir(self._global_home_dir)
        built_in_agents_dir = self.built_in_agents_dir()
        default_guidance_files = (
            (agents_dir / "AGENTS.md",) if (agents_dir / "AGENTS.md").exists() else ()
        )
        return ConfigAssetLayout(
            asset_root=asset_root,
            templates_dir=asset_root / "templates",
            agents_dir=agents_dir,
            project_agents_dir=project_agents_dir,
            user_agents_dir=user_agents_dir,
            built_in_agents_dir=built_in_agents_dir,
            project_skills_dir=self.skills_dir(project_agents_dir),
            user_skills_dir=self.skills_dir(user_agents_dir),
            built_in_skills_dir=self.skills_dir(built_in_agents_dir),
            project_agent_manifests_dir=self.project_agent_manifests_dir(self._root),
            user_agent_manifests_dir=self.user_agent_manifests_dir(self._global_home_dir),
            default_guidance_files=default_guidance_files,
        )

    def discover_asset_root(self) -> Path:
        explicit_root = self._env.get("DORMAMMU_ASSET_ROOT")
        if explicit_root:
            candidate = Path(explicit_root).expanduser()
            if not candidate.is_absolute():
                candidate = (self._root / candidate).resolve()
            return candidate

        source_root = Path(__file__).resolve().parents[2]
        if (source_root / "templates").exists():
            return source_root

        packaged_asset_root = Path(__file__).resolve().parent / "assets"
        if (packaged_asset_root / "templates").exists():
            return packaged_asset_root
        return self._root

    def discover_agents_dir(self, *, asset_root: Path) -> Path:
        explicit_dir = self._env.get("DORMAMMU_AGENTS_DIR")
        if explicit_dir:
            candidate = Path(explicit_dir).expanduser()
            if not candidate.is_absolute():
                candidate = (self._root / candidate).resolve()
            return candidate

        global_agents_dir = self._global_home_dir / "agents"
        if (global_agents_dir / "AGENTS.md").exists():
            return global_agents_dir

        repo_agents_dir = self.project_agents_dir(self._root)
        if (repo_agents_dir / "AGENTS.md").exists():
            return repo_agents_dir

        packaged_agents_dir = asset_root / "agents"
        if (packaged_agents_dir / "AGENTS.md").exists():
            return packaged_agents_dir

        return repo_agents_dir

    @staticmethod
    def project_agents_dir(root: Path) -> Path:
        return (root / "agents").resolve()

    @staticmethod
    def user_agents_dir(global_home_dir: Path) -> Path:
        return (global_home_dir / "agents").resolve()

    @staticmethod
    def built_in_agents_dir() -> Path:
        return (Path(__file__).resolve().parent / "assets" / "agents").resolve()

    @staticmethod
    def skills_dir(agents_dir: Path) -> Path:
        return (agents_dir / "skills").resolve()

    @staticmethod
    def project_agent_manifests_dir(root: Path) -> Path:
        return (root / PROJECT_AGENT_MANIFESTS_SUBDIR).resolve()

    @staticmethod
    def user_agent_manifests_dir(global_home_dir: Path) -> Path:
        return (global_home_dir / USER_AGENT_MANIFESTS_DIRNAME).resolve()


class ConfigAgentProfileResolver:
    """Resolve runtime agent profiles and profile-backed manifests."""

    def __init__(self, config: "AppConfig") -> None:
        self._config = config

    def resolve_profile(self, role: str) -> "AgentProfile":
        from dormammu.agent.profiles import resolve_agent_profile  # noqa: PLC0415

        return resolve_agent_profile(
            role,
            agents_config=self._config.agents,
            normalized_profiles=self._config.agent_profiles,
        )

    def load_manifest_definitions(
        self,
        *,
        names: tuple[str, ...] | None = None,
    ) -> "AgentManifestLoadResult":
        from dormammu.agent.manifest_loader import load_agent_manifest_definitions  # noqa: PLC0415

        return load_agent_manifest_definitions(self._config, names=names)

    def normalize_loaded_profiles(
        self,
        *,
        agents_config: "AgentsConfig | None",
    ) -> "dict[str, AgentProfile]":
        from dormammu.agent.profiles import normalize_agent_profiles  # noqa: PLC0415

        manifest_definitions = ()
        requested_names = self.requested_manifest_profile_names(agents_config)
        if requested_names:
            manifest_definitions = self.load_manifest_definitions(
                names=requested_names,
            ).definitions
        return normalize_agent_profiles(
            agents_config=agents_config,
            manifest_definitions=manifest_definitions,
        )

    @staticmethod
    def requested_manifest_profile_names(
        agents_config: "AgentsConfig | None",
    ) -> tuple[str, ...]:
        if agents_config is None:
            return ()

        from dormammu.agent.profiles import (  # noqa: PLC0415
            profile_name_for_role,
            role_requires_manifest_resolution,
        )
        from dormammu.agent.role_config import ROLE_NAMES  # noqa: PLC0415

        names: list[str] = []
        seen: set[str] = set()
        for role in ROLE_NAMES:
            if not role_requires_manifest_resolution(role, agents_config=agents_config):
                continue
            role_config = agents_config.for_role(role)
            profile_name = profile_name_for_role(role, role_config)
            if profile_name in seen:
                continue
            seen.add(profile_name)
            names.append(profile_name)
        return tuple(names)


class ConfigMcpAccessResolver:
    """Resolve MCP visibility for effective agent profiles."""

    def __init__(self, config: "AppConfig") -> None:
        self._config = config

    def resolve_profile_access(
        self,
        profile: "AgentProfile | str",
    ) -> McpProfileResolution:
        catalog = self._config.mcp or McpCatalog()
        return catalog.resolve_profile_access(profile)

    def servers_for_profile(
        self,
        profile: "AgentProfile | str",
    ) -> tuple[EffectiveMcpServer, ...]:
        return self.resolve_profile_access(profile).visible_servers

    def servers_for_role(self, role: str) -> tuple[EffectiveMcpServer, ...]:
        profile = ConfigAgentProfileResolver(self._config).resolve_profile(role)
        return self.servers_for_profile(profile)


class ConfigRuntimePathResolver:
    """Render runtime path guidance from an AppConfig value object."""

    def __init__(self, config: "AppConfig") -> None:
        self._config = config

    def runtime_path_prompt(self) -> str:
        paths = WorkspacePaths(
            repo_root=self._config.repo_root,
            repo_dev_dir=self._config.repo_dev_dir,
            home_dir=self._config.home_dir,
            global_home_dir=self._config.global_home_dir,
            workspace_root=self._config.workspace_root,
            workspace_project_root=self._config.workspace_project_root,
            base_dev_dir=self._config.base_dev_dir,
            dev_dir=self._config.dev_dir,
            logs_dir=self._config.logs_dir,
            sessions_dir=self._config.sessions_dir,
            tmp_dir=self._config.workspace_tmp_dir,
            results_dir=self._config.results_dir,
        )
        return paths.runtime_path_prompt()
