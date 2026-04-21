from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from shutil import which
from typing import TYPE_CHECKING, Any, Callable, Mapping
import os
import subprocess

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


class McpRuntimeStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class McpRuntimeFailureReason(str, Enum):
    TRANSPORT_UNSUPPORTED = "transport_unsupported"
    COMMAND_NOT_FOUND = "command_not_found"
    LAUNCH_ERROR = "launch_error"
    PROCESS_ERROR = "process_error"
    TIMEOUT = "timeout"
    EXECUTION_ERROR = "execution_error"


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
class McpRuntimeRequest:
    server: EffectiveMcpServer
    operation: str = "invoke_server"
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    stdin: str | None = None
    timeout_seconds: float | None = None

    @classmethod
    def from_access_result(
        cls,
        access_result: "McpAccessResult",
        *,
        payload: Mapping[str, Any] | None = None,
        metadata: Mapping[str, Any] | None = None,
        stdin: str | None = None,
        timeout_seconds: float | None = None,
    ) -> "McpRuntimeRequest":
        access_result.raise_for_status()
        if access_result.server is None:
            raise RuntimeError("MCP access result did not include a resolved server.")

        resolved_payload = dict(access_result.request.payload)
        if payload:
            resolved_payload.update(dict(payload))

        resolved_metadata = dict(access_result.request.metadata)
        if metadata:
            resolved_metadata.update(dict(metadata))

        return cls(
            server=access_result.server,
            operation=access_result.request.operation,
            payload=resolved_payload,
            metadata=resolved_metadata,
            stdin=stdin,
            timeout_seconds=timeout_seconds,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "server_id": self.server.id,
            "operation": self.operation,
            "payload": dict(self.payload),
            "metadata": dict(self.metadata),
            "stdin_present": self.stdin is not None,
            "stdin_length": len(self.stdin) if self.stdin is not None else 0,
            "timeout_seconds": self.timeout_seconds,
        }


@dataclass(frozen=True, slots=True)
class McpPreparedRuntimeInteraction:
    server: EffectiveMcpServer
    operation: str
    transport_kind: str
    target: dict[str, Any]
    payload: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "server": {
                "id": self.server.id,
                "scope": self.server.scope,
                "config_path": str(self.server.config_path),
            },
            "operation": self.operation,
            "transport_kind": self.transport_kind,
            "target": dict(self.target),
            "payload": dict(self.payload),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True, slots=True)
class McpRuntimeResponse:
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "payload": dict(self.payload),
            "diagnostics": dict(self.diagnostics),
        }


@dataclass(frozen=True, slots=True)
class McpRuntimeFailure:
    reason: McpRuntimeFailureReason
    message: str
    diagnostics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "reason": self.reason.value,
            "message": self.message,
            "diagnostics": dict(self.diagnostics),
        }


@dataclass(frozen=True, slots=True)
class McpRuntimeResult:
    status: McpRuntimeStatus
    request: McpRuntimeRequest
    interaction: McpPreparedRuntimeInteraction
    message: str
    response: McpRuntimeResponse | None = None
    failure: McpRuntimeFailure | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def succeeded(self) -> bool:
        return self.status is McpRuntimeStatus.SUCCEEDED

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "message": self.message,
            "request": self.request.to_dict(),
            "interaction": self.interaction.to_dict(),
            "response": self.response.to_dict() if self.response is not None else None,
            "failure": self.failure.to_dict() if self.failure is not None else None,
            "diagnostics": dict(self.diagnostics),
        }

    def raise_for_status(self) -> None:
        if self.status is McpRuntimeStatus.SUCCEEDED:
            return
        raise McpRuntimeInvocationError(self)


class McpRuntimeInvocationError(RuntimeError):
    def __init__(self, result: McpRuntimeResult) -> None:
        self.result = result
        super().__init__(result.message)


class McpRuntimeExecutionFailure(RuntimeError):
    def __init__(
        self,
        *,
        reason: McpRuntimeFailureReason,
        message: str,
        diagnostics: Mapping[str, Any] | None = None,
    ) -> None:
        self.reason = reason
        self.diagnostics = dict(diagnostics or {})
        super().__init__(message)


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
RuntimeExecutor = Callable[[McpRuntimeRequest, McpPreparedRuntimeInteraction], McpRuntimeResponse]


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


class McpRuntimeAdapter:
    """Transport-facing MCP runtime adapter behind the governed access boundary."""

    def __init__(
        self,
        *,
        executors: Mapping[str, RuntimeExecutor] | None = None,
    ) -> None:
        resolved_executors = {"stdio": self._execute_stdio}
        if executors:
            resolved_executors.update(dict(executors))
        self._executors = resolved_executors

    def prepare(self, request: McpRuntimeRequest) -> McpPreparedRuntimeInteraction:
        transport = request.server.definition.transport
        if isinstance(transport, McpStdioTransport):
            target = {
                "command": transport.command,
                "args": list(transport.args),
                "cwd": str(transport.cwd) if transport.cwd is not None else None,
                "env_keys": sorted(transport.env.keys()),
            }
        else:
            target = {
                "url": transport.url,
                "header_keys": sorted(transport.headers.keys()),
            }

        return McpPreparedRuntimeInteraction(
            server=request.server,
            operation=request.operation,
            transport_kind=transport.kind.value,
            target=target,
            payload=dict(request.payload),
            metadata=dict(request.metadata),
        )

    def invoke(self, request: McpRuntimeRequest) -> McpRuntimeResult:
        interaction = self.prepare(request)
        executor = self._executors.get(interaction.transport_kind)
        if executor is None:
            failure = McpRuntimeFailure(
                reason=McpRuntimeFailureReason.TRANSPORT_UNSUPPORTED,
                message=(
                    f"MCP runtime transport {interaction.transport_kind!r} is not "
                    "implemented by this adapter."
                ),
                diagnostics={
                    "transport_kind": interaction.transport_kind,
                    "target": dict(interaction.target),
                },
            )
            return self._failure_result(request, interaction, failure)

        try:
            response = self._validate_response(
                request,
                interaction,
                executor(request, interaction),
            )
        except (FileNotFoundError, PermissionError) as exc:
            failure = self._launch_failure(request, interaction, exc)
            return self._failure_result(request, interaction, failure)
        except subprocess.TimeoutExpired as exc:
            failure = McpRuntimeFailure(
                reason=McpRuntimeFailureReason.TIMEOUT,
                message=(
                    f"MCP runtime interaction for server {request.server.id!r} "
                    f"timed out after {exc.timeout} seconds."
                ),
                diagnostics={
                    "transport_kind": interaction.transport_kind,
                    "target": dict(interaction.target),
                    "timeout_seconds": exc.timeout,
                },
            )
            return self._failure_result(request, interaction, failure)
        except McpRuntimeExecutionFailure as exc:
            failure = McpRuntimeFailure(
                reason=exc.reason,
                message=str(exc),
                diagnostics=dict(exc.diagnostics),
            )
            return self._failure_result(request, interaction, failure)
        except Exception as exc:  # pragma: no cover - defensive fallback
            failure = McpRuntimeFailure(
                reason=McpRuntimeFailureReason.EXECUTION_ERROR,
                message=(
                    f"MCP runtime interaction for server {request.server.id!r} "
                    f"failed unexpectedly: {exc}"
                ),
                diagnostics={
                    "transport_kind": interaction.transport_kind,
                    "target": dict(interaction.target),
                    "exception_type": type(exc).__name__,
                },
            )
            return self._failure_result(request, interaction, failure)

        diagnostics = self._base_diagnostics(request, interaction)
        diagnostics.update(response.diagnostics)
        return McpRuntimeResult(
            status=McpRuntimeStatus.SUCCEEDED,
            request=request,
            interaction=interaction,
            response=response,
            message=(
                f"MCP runtime interaction for server {request.server.id!r} "
                f"completed via {interaction.transport_kind!r}."
            ),
            diagnostics=diagnostics,
        )

    def _validate_response(
        self,
        request: McpRuntimeRequest,
        interaction: McpPreparedRuntimeInteraction,
        response: object,
    ) -> McpRuntimeResponse:
        if not isinstance(response, McpRuntimeResponse):
            raise McpRuntimeExecutionFailure(
                reason=McpRuntimeFailureReason.EXECUTION_ERROR,
                message=(
                    f"MCP runtime interaction for server {request.server.id!r} "
                    "returned an invalid response object."
                ),
                diagnostics={
                    "transport_kind": interaction.transport_kind,
                    "target": dict(interaction.target),
                    "response_type": type(response).__name__,
                },
            )

        for field_name, value in (
            ("payload", response.payload),
            ("diagnostics", response.diagnostics),
        ):
            if not isinstance(value, Mapping):
                raise McpRuntimeExecutionFailure(
                    reason=McpRuntimeFailureReason.EXECUTION_ERROR,
                    message=(
                        f"MCP runtime interaction for server {request.server.id!r} "
                        f"returned invalid response {field_name!r} data."
                    ),
                    diagnostics={
                        "transport_kind": interaction.transport_kind,
                        "target": dict(interaction.target),
                        "response_type": type(response).__name__,
                        f"{field_name}_type": type(value).__name__,
                    },
                )

        for field_name, value in (
            ("stdout", response.stdout),
            ("stderr", response.stderr),
        ):
            if not isinstance(value, str):
                raise McpRuntimeExecutionFailure(
                    reason=McpRuntimeFailureReason.EXECUTION_ERROR,
                    message=(
                        f"MCP runtime interaction for server {request.server.id!r} "
                        f"returned invalid response {field_name!r} data."
                    ),
                    diagnostics={
                        "transport_kind": interaction.transport_kind,
                        "target": dict(interaction.target),
                        "response_type": type(response).__name__,
                        f"{field_name}_type": type(value).__name__,
                    },
                )

        if response.exit_code is not None and type(response.exit_code) is not int:
            raise McpRuntimeExecutionFailure(
                reason=McpRuntimeFailureReason.EXECUTION_ERROR,
                message=(
                    f"MCP runtime interaction for server {request.server.id!r} "
                    "returned invalid response 'exit_code' data."
                ),
                diagnostics={
                    "transport_kind": interaction.transport_kind,
                    "target": dict(interaction.target),
                    "response_type": type(response).__name__,
                    "exit_code_type": type(response.exit_code).__name__,
                },
            )

        return response

    def _execute_stdio(
        self,
        request: McpRuntimeRequest,
        interaction: McpPreparedRuntimeInteraction,
    ) -> McpRuntimeResponse:
        transport = request.server.definition.transport
        if not isinstance(transport, McpStdioTransport):
            raise McpRuntimeExecutionFailure(
                reason=McpRuntimeFailureReason.EXECUTION_ERROR,
                message=(
                    f"MCP runtime stdio executor received incompatible transport "
                    f"{interaction.transport_kind!r}."
                ),
                diagnostics={"transport_kind": interaction.transport_kind},
            )

        env = os.environ.copy()
        env.update(transport.env)
        completed = subprocess.run(
            [transport.command, *transport.args],
            input=request.stdin,
            text=True,
            capture_output=True,
            cwd=str(transport.cwd) if transport.cwd is not None else None,
            env=env,
            timeout=request.timeout_seconds,
            check=False,
        )
        if completed.returncode != 0:
            raise McpRuntimeExecutionFailure(
                reason=McpRuntimeFailureReason.PROCESS_ERROR,
                message=(
                    f"MCP runtime interaction for server {request.server.id!r} "
                    f"failed with exit code {completed.returncode}."
                ),
                diagnostics={
                    "returncode": completed.returncode,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                },
            )

        return McpRuntimeResponse(
            stdout=completed.stdout,
            stderr=completed.stderr,
            exit_code=completed.returncode,
            diagnostics={"returncode": completed.returncode},
        )

    def _failure_result(
        self,
        request: McpRuntimeRequest,
        interaction: McpPreparedRuntimeInteraction,
        failure: McpRuntimeFailure,
    ) -> McpRuntimeResult:
        diagnostics = self._base_diagnostics(request, interaction)
        diagnostics.update(failure.diagnostics)
        return McpRuntimeResult(
            status=McpRuntimeStatus.FAILED,
            request=request,
            interaction=interaction,
            failure=failure,
            message=failure.message,
            diagnostics=diagnostics,
        )

    def _base_diagnostics(
        self,
        request: McpRuntimeRequest,
        interaction: McpPreparedRuntimeInteraction,
    ) -> dict[str, Any]:
        return {
            "server_id": request.server.id,
            "operation": request.operation,
            "transport_kind": interaction.transport_kind,
            "target": dict(interaction.target),
        }

    def _describe_target(self, interaction: McpPreparedRuntimeInteraction) -> str:
        if "command" in interaction.target:
            return str(interaction.target["command"])
        if "url" in interaction.target:
            return str(interaction.target["url"])
        return repr(interaction.target)

    def _launch_failure(
        self,
        request: McpRuntimeRequest,
        interaction: McpPreparedRuntimeInteraction,
        exc: FileNotFoundError | PermissionError,
    ) -> McpRuntimeFailure:
        diagnostics = {
            "transport_kind": interaction.transport_kind,
            "target": dict(interaction.target),
            "exception_type": type(exc).__name__,
        }
        diagnostics.update(self._launch_target_diagnostics(request))
        reason = self._classify_launch_failure(request, diagnostics)
        if reason is McpRuntimeFailureReason.LAUNCH_ERROR:
            message = (
                f"MCP runtime target for server {request.server.id!r} "
                "could not be started due to insufficient permissions: "
                f"{self._describe_target(interaction)!r}"
            )
        else:
            message = (
                f"MCP runtime target for server {request.server.id!r} "
                f"could not be started: {self._describe_target(interaction)!r}"
            )
        return McpRuntimeFailure(
            reason=reason,
            message=message,
            diagnostics=diagnostics,
        )

    def _classify_launch_failure(
        self,
        request: McpRuntimeRequest,
        diagnostics: Mapping[str, Any],
    ) -> McpRuntimeFailureReason:
        transport = request.server.definition.transport
        if isinstance(transport, McpStdioTransport):
            if diagnostics.get("resolved_command") is None or diagnostics.get("exists") is False:
                return McpRuntimeFailureReason.COMMAND_NOT_FOUND
            if diagnostics.get("executable") is False:
                return McpRuntimeFailureReason.LAUNCH_ERROR
        if diagnostics.get("exception_type") == "PermissionError":
            return McpRuntimeFailureReason.LAUNCH_ERROR
        return McpRuntimeFailureReason.COMMAND_NOT_FOUND

    def _launch_target_diagnostics(
        self,
        request: McpRuntimeRequest,
    ) -> dict[str, Any]:
        transport = request.server.definition.transport
        if not isinstance(transport, McpStdioTransport):
            return {}

        command = transport.command.strip()
        candidate = Path(command).expanduser()
        if candidate.is_absolute() or "/" in command or "\\" in command:
            resolved = candidate.resolve(strict=False)
            exists = resolved.exists() and resolved.is_file()
            return {
                "command": command,
                "resolved_command": str(resolved),
                "exists": exists,
                "executable": os.access(resolved, os.X_OK) if exists else False,
            }

        resolved_command = which(command)
        return {
            "command": command,
            "resolved_command": resolved_command,
            "executable": (
                os.access(resolved_command, os.X_OK)
                if resolved_command is not None
                else False
            ),
        }


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
