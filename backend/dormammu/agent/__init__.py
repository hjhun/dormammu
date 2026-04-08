"""External coding-agent CLI adapters."""

from dormammu.agent.cli_adapter import CliAdapter
from dormammu.agent.command_builder import CommandPlan, build_command_plan
from dormammu.agent.help_parser import parse_help_text
from dormammu.agent.models import (
    AgentRunRequest,
    AgentRunResult,
    AutoApproveCandidate,
    AutoApproveInfo,
    CliCapabilities,
)

__all__ = [
    "AgentRunRequest",
    "AgentRunResult",
    "AutoApproveCandidate",
    "AutoApproveInfo",
    "CliAdapter",
    "CliCapabilities",
    "CommandPlan",
    "build_command_plan",
    "parse_help_text",
]
