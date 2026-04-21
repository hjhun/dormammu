from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from shutil import which
from typing import TYPE_CHECKING, Any, Callable, Mapping
import os

from dormammu.agent.permissions import PermissionDecision
from dormammu.agent.profiles import AgentProfile
from dormammu.hooks import HookSubjectRef
from dormammu.mcp import EffectiveMcpServer, McpStdioTransport
from dormammu.runtime_hooks import (
    RuntimeHookBlocked,
    RuntimeHookController,
    RuntimeHookSummary,
)

if TYPE_CHECKING:
    from dormammu.config import AppConfig


MCP_TOOL_NAME = "mcp"


class McpAccessStatus(str, Enum):
    READY = "ready"
    DENIED = "denied"
    BLOCKED = "blocked"
    UNAVAILABLE = "unavailable"


class McpAccessReason(str, Enum):
    PROFILE_DENIED = "profile_denied"
    PERMISSION_DENIED = "permission_denied"
    PERMISSION_ASK = "permission_ask"
    HOOK_BLOCKED = "hook_blocked"
    SERVER_DISABLED = "server_disabled"
    SERVER_NOT_CONFIGURED = "server_not_configured"
    SERVER_UNAVAILABLE = "server_unavailable"


@dataclass(frozen=True, slots=True)
class McpPermissionResolution:
    decision: PermissionDecision
    matched_tool_name: str | None
    source: str

    def to_dict(self) -> dict[str, str | None]:
        return {
            "decision": self.decision.value,
            "matched_tool_name": self.matched_tool_name,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class McpAvailabilityCheck:
    available: bool
    message: str | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "available": self.available,
            "message": self.message,
            "diagnostics": dict(self.diagnostics),
        }


@dataclass(frozen=True, slots=True)
class McpAccessRequest:
    server_id: str
    profile: AgentProfile | str
    source: str
    operation: str = "invoke_server"
    session_id: str | None = None
    run_id: str | None = None
    agent_role: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def tool_target(self) -> str:
        return mcp_tool_target(self.server_id)


@dataclass(frozen=True, slots=True)
class McpAccessResult:
    status: McpAccessStatus
    request: McpAccessRequest
    profile_name: str
    message: str
    server: EffectiveMcpServer | None = None
    reason: McpAccessReason | None = None
    permission: McpPermissionResolution | None = None
    hook_summary: RuntimeHookSummary | None = None
    availability: McpAvailabilityCheck | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return self.status is McpAccessStatus.READY

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "profile_name": self.profile_name,
            "server_id": self.request.server_id,
            "operation": self.request.operation,
            "source": self.request.source,
            "message": self.message,
            "reason": self.reason.value if self.reason is not None else None,
            "server": self.server.to_dict() if self.server is not None else None,
            "permission": self.permission.to_dict() if self.permission is not None else None,
            "hook_summary": (
                self.hook_summary.to_state_dict()
                if self.hook_summary is not None
                else None
            ),
            "availability": (
                self.availability.to_dict()
                if self.availability is not None
                else None
            ),
            "diagnostics": dict(self.diagnostics),
        }

    def raise_for_status(self) -> None:
        if self.status is McpAccessStatus.READY:
            return
        if self.status is McpAccessStatus.DENIED:
            raise McpAccessDeniedError(self)
        if self.status is McpAccessStatus.BLOCKED:
            raise McpAccessBlockedError(self)
        raise McpServerUnavailableError(self)


class McpAccessError(RuntimeError):
    def __init__(self, result: McpAccessResult) -> None:
        self.result = result
        super().__init__(result.message)


class McpAccessDeniedError(McpAccessError):
    pass


class McpAccessBlockedError(McpAccessError):
    pass


class McpServerUnavailableError(McpAccessError):
    pass


AvailabilityProbe = Callable[[EffectiveMcpServer], McpAvailabilityCheck]


def mcp_tool_target(server_id: str) -> str:
    return f"{MCP_TOOL_NAME}:{server_id.strip()}"


def resolve_mcp_permission(
    profile: AgentProfile,
    *,
    server_id: str,
) -> McpPermissionResolution:
    rules = profile.permission_policy.tools.rules
    specific_target = mcp_tool_target(server_id)

    for rule in reversed(rules):
        if rule.tool == specific_target:
            return McpPermissionResolution(
                decision=rule.decision,
                matched_tool_name=specific_target,
                source="server_rule",
            )

    for rule in reversed(rules):
        if rule.tool == MCP_TOOL_NAME:
            return McpPermissionResolution(
                decision=rule.decision,
                matched_tool_name=MCP_TOOL_NAME,
                source="family_rule",
            )

    return McpPermissionResolution(
        decision=profile.permission_policy.tools.default,
        matched_tool_name=None,
        source="default",
    )


def probe_mcp_server_availability(server: EffectiveMcpServer) -> McpAvailabilityCheck:
    transport = server.definition.transport
    if not isinstance(transport, McpStdioTransport):
        return McpAvailabilityCheck(
            available=True,
            diagnostics={
                "transport_kind": transport.kind.value,
                "probe": "deferred_to_adapter",
            },
        )

    command = transport.command.strip()
    command_path: str | None = None
    candidate = Path(command).expanduser()
    if candidate.is_absolute() or "/" in command or "\\" in command:
        resolved = candidate.resolve(strict=False)
        command_path = str(resolved)
        exists = resolved.exists() and resolved.is_file()
        executable = os.access(resolved, os.X_OK)
        if not exists or not executable:
            return McpAvailabilityCheck(
                available=False,
                message=(
                    f"MCP server {server.id!r} is unavailable: configured command "
                    f"{command!r} could not be executed."
                ),
                diagnostics={
                    "transport_kind": transport.kind.value,
                    "command": command,
                    "resolved_command": command_path,
                    "exists": exists,
                    "executable": executable,
                },
            )
    else:
        command_path = which(command)
        if command_path is None:
            return McpAvailabilityCheck(
                available=False,
                message=(
                    f"MCP server {server.id!r} is unavailable: configured command "
                    f"{command!r} was not found in PATH."
                ),
                diagnostics={
                    "transport_kind": transport.kind.value,
                    "command": command,
                    "resolved_command": None,
                },
            )

    return McpAvailabilityCheck(
        available=True,
        diagnostics={
            "transport_kind": transport.kind.value,
            "command": command,
            "resolved_command": command_path,
        },
    )


class McpAccessBoundary:
    def __init__(
        self,
        config: AppConfig,
        *,
        hook_controller: RuntimeHookController | None = None,
        availability_probe: AvailabilityProbe | None = None,
    ) -> None:
        self._config = config
        self._hook_controller = hook_controller or RuntimeHookController(config)
        self._availability_probe = availability_probe or probe_mcp_server_availability

    def evaluate_access(self, request: McpAccessRequest) -> McpAccessResult:
        profile = self._resolve_profile(request.profile)
        profile_name = profile.name
        server = self._resolve_server(request.server_id)

        if server is None:
            return self._result(
                status=McpAccessStatus.UNAVAILABLE,
                request=request,
                profile_name=profile_name,
                message=f"MCP server {request.server_id!r} is not configured.",
                reason=McpAccessReason.SERVER_NOT_CONFIGURED,
                diagnostics={"tool_target": request.tool_target},
            )

        if not server.is_visible_to_profile(profile_name):
            return self._result(
                status=McpAccessStatus.DENIED,
                request=request,
                profile_name=profile_name,
                server=server,
                message=(
                    f"MCP server {server.id!r} is denied for profile {profile_name!r} "
                    "by MCP access configuration."
                ),
                reason=McpAccessReason.PROFILE_DENIED,
            )

        if not server.enabled:
            return self._result(
                status=McpAccessStatus.UNAVAILABLE,
                request=request,
                profile_name=profile_name,
                server=server,
                message=f"MCP server {server.id!r} is configured but disabled.",
                reason=McpAccessReason.SERVER_DISABLED,
            )

        permission = resolve_mcp_permission(profile, server_id=server.id)
        if permission.decision is PermissionDecision.DENY:
            matched = permission.matched_tool_name or "default tool permission policy"
            return self._result(
                status=McpAccessStatus.DENIED,
                request=request,
                profile_name=profile_name,
                server=server,
                permission=permission,
                message=(
                    f"MCP server {server.id!r} is denied for profile {profile_name!r} "
                    f"by tool permission {matched!r}."
                ),
                reason=McpAccessReason.PERMISSION_DENIED,
            )
        if permission.decision is PermissionDecision.ASK:
            matched = permission.matched_tool_name or "default tool permission policy"
            return self._result(
                status=McpAccessStatus.DENIED,
                request=request,
                profile_name=profile_name,
                server=server,
                permission=permission,
                message=(
                    f"MCP server {server.id!r} requires approval for profile "
                    f"{profile_name!r} via tool permission {matched!r}."
                ),
                reason=McpAccessReason.PERMISSION_ASK,
            )

        try:
            hook_summary = self._hook_controller.emit_tool_execution(
                source=request.source,
                tool_name=MCP_TOOL_NAME,
                tool_target=request.tool_target,
                session_id=request.session_id,
                run_id=request.run_id,
                agent_role=request.agent_role or profile_name,
                subject=HookSubjectRef(
                    kind="mcp_server",
                    id=server.id,
                    name=request.tool_target,
                    metadata={
                        "profile_name": profile_name,
                        "transport_kind": server.definition.transport.kind.value,
                    },
                ),
                payload={
                    "operation": request.operation,
                    "server_id": server.id,
                    "profile_name": profile_name,
                    "transport_kind": server.definition.transport.kind.value,
                    "failure_policy": server.definition.failure_policy.value,
                    **request.payload,
                },
                metadata={
                    "config_path": str(server.config_path),
                    "scope": server.scope,
                    **request.metadata,
                },
            )
        except RuntimeHookBlocked as exc:
            return self._result(
                status=McpAccessStatus.BLOCKED,
                request=request,
                profile_name=profile_name,
                server=server,
                permission=permission,
                hook_summary=exc.summary,
                message=(
                    f"MCP server {server.id!r} was blocked by runtime hook: "
                    f"{exc.summary.message or 'no message'}"
                ),
                reason=McpAccessReason.HOOK_BLOCKED,
            )

        availability = self._availability_probe(server)
        if not availability.available:
            return self._result(
                status=McpAccessStatus.UNAVAILABLE,
                request=request,
                profile_name=profile_name,
                server=server,
                permission=permission,
                hook_summary=hook_summary,
                availability=availability,
                message=availability.message
                or f"MCP server {server.id!r} is unavailable.",
                reason=McpAccessReason.SERVER_UNAVAILABLE,
            )

        return self._result(
            status=McpAccessStatus.READY,
            request=request,
            profile_name=profile_name,
            server=server,
            permission=permission,
            hook_summary=hook_summary,
            availability=availability,
            message=(
                f"MCP server {server.id!r} is ready for governed runtime access "
                f"for profile {profile_name!r}."
            ),
        )

    def require_access(self, request: McpAccessRequest) -> McpAccessResult:
        result = self.evaluate_access(request)
        result.raise_for_status()
        return result

    def _resolve_profile(self, profile: AgentProfile | str) -> AgentProfile:
        if isinstance(profile, AgentProfile):
            return profile

        catalog = self._config.agent_profiles or {}
        resolved = catalog.get(profile)
        if resolved is not None:
            return resolved

        try:
            return self._config.resolve_agent_profile(profile)
        except ValueError as exc:
            raise RuntimeError(f"Unknown MCP access profile {profile!r}.") from exc

    def _resolve_server(self, server_id: str) -> EffectiveMcpServer | None:
        catalog = self._config.mcp
        if catalog is None:
            return None
        return catalog.definitions_by_id().get(server_id.strip())

    def _result(
        self,
        *,
        status: McpAccessStatus,
        request: McpAccessRequest,
        profile_name: str,
        message: str,
        server: EffectiveMcpServer | None = None,
        reason: McpAccessReason | None = None,
        permission: McpPermissionResolution | None = None,
        hook_summary: RuntimeHookSummary | None = None,
        availability: McpAvailabilityCheck | None = None,
        diagnostics: Mapping[str, Any] | None = None,
    ) -> McpAccessResult:
        result_diagnostics: dict[str, Any] = {
            "tool_name": MCP_TOOL_NAME,
            "tool_target": request.tool_target,
        }
        if server is not None:
            result_diagnostics.update(
                {
                    "config_path": str(server.config_path),
                    "scope": server.scope,
                    "transport_kind": server.definition.transport.kind.value,
                }
            )
        if hook_summary is not None:
            result_diagnostics["hook_blocked"] = hook_summary.blocked
        if availability is not None:
            result_diagnostics["availability"] = dict(availability.diagnostics)
        if diagnostics:
            result_diagnostics.update(dict(diagnostics))
        return McpAccessResult(
            status=status,
            request=request,
            profile_name=profile_name,
            message=message,
            server=server,
            reason=reason,
            permission=permission,
            hook_summary=hook_summary,
            availability=availability,
            diagnostics=result_diagnostics,
        )
