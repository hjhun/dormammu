from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PresetAutoApproveCandidate:
    value: str
    risk: str
    summary: str


@dataclass(frozen=True, slots=True)
class KnownCliPreset:
    key: str
    label: str
    executable_names: tuple[str, ...]
    help_hints: tuple[str, ...] = ()
    command_prefix: tuple[str, ...] = ()
    prompt_file_flag: str | None = None
    prompt_arg_flag: str | None = None
    prompt_positional: bool = False
    workdir_flag: str | None = None
    default_extra_args: tuple[str, ...] = ()
    suppress_default_extra_args_when_present: tuple[str, ...] = ()
    auto_approve_candidates: tuple[PresetAutoApproveCandidate, ...] = ()


KNOWN_CLI_PRESETS: tuple[KnownCliPreset, ...] = (
    KnownCliPreset(
        key="codex",
        label="OpenAI Codex",
        executable_names=("codex",),
        help_hints=("codex exec", "--full-auto", "--dangerously-bypass-approvals-and-sandbox"),
        command_prefix=("exec",),
        prompt_positional=True,
        auto_approve_candidates=(
            PresetAutoApproveCandidate(
                value="--full-auto",
                risk="medium",
                summary="Allows Codex to apply changes automatically in exec mode.",
            ),
        ),
    ),
    KnownCliPreset(
        key="gemini",
        label="Gemini CLI",
        executable_names=("gemini",),
        help_hints=("--approval-mode", "--prompt-interactive", "gemini cli"),
        prompt_arg_flag="--prompt",
        default_extra_args=("--approval-mode", "yolo", "--include-directories", "/"),
        suppress_default_extra_args_when_present=(
            "--approval-mode",
            "--yolo",
            "--include-directories",
        ),
        auto_approve_candidates=(
            PresetAutoApproveCandidate(
                value="--approval-mode yolo",
                risk="high",
                summary="Auto-accepts all actions without confirmation and should remain opt-in.",
            ),
            PresetAutoApproveCandidate(
                value="--yolo",
                risk="high",
                summary="Auto-accepts all actions without confirmation and should remain opt-in.",
            ),
            PresetAutoApproveCandidate(
                value="--approval-mode auto_edit",
                risk="medium",
                summary="Auto-accepts edit operations without enabling full yolo mode.",
            ),
        ),
    ),
    KnownCliPreset(
        key="claude_code",
        label="Claude Code",
        executable_names=("claude", "claude-code"),
        help_hints=("--permission-mode", "--output-format", "bypassPermissions"),
        command_prefix=("--print",),
        prompt_positional=True,
        default_extra_args=("--dangerously-skip-permissions",),
        suppress_default_extra_args_when_present=(
            "--permission-mode",
            "--dangerously-skip-permissions",
            "--allow-dangerously-skip-permissions",
        ),
        auto_approve_candidates=(
            PresetAutoApproveCandidate(
                value="--dangerously-skip-permissions",
                risk="high",
                summary="Bypasses all permission checks and should remain opt-in.",
            ),
            PresetAutoApproveCandidate(
                value="--permission-mode bypassPermissions",
                risk="high",
                summary="Bypasses permission prompts for the full session and should remain opt-in.",
            ),
            PresetAutoApproveCandidate(
                value="--permission-mode auto",
                risk="medium",
                summary="Starts Claude Code in auto permission mode.",
            ),
        ),
    ),
    KnownCliPreset(
        key="cline",
        label="Cline",
        executable_names=("cline",),
        help_hints=("-y", "--verbose", "--cwd", "--timeout", "cline"),
        prompt_positional=True,
        workdir_flag="--cwd",
        default_extra_args=("--verbose", "--timeout", "1200"),
        suppress_default_extra_args_when_present=("--verbose", "--timeout"),
        auto_approve_candidates=(
            PresetAutoApproveCandidate(
                value="-y",
                risk="high",
                summary="Enables non-interactive plain-text mode and should remain opt-in.",
            ),
        ),
    ),
    KnownCliPreset(
        key="aider",
        label="aider",
        executable_names=("aider",),
        help_hints=("--message-file", "--message", "--yes"),
        prompt_file_flag="--message-file",
        prompt_arg_flag="--message",
        auto_approve_candidates=(
            PresetAutoApproveCandidate(
                value="--yes",
                risk="medium",
                summary="Accepts confirmations automatically during scripted runs.",
            ),
        ),
    ),
)


def match_known_preset(
    executable_name: str | None,
    help_text: str,
) -> tuple[KnownCliPreset | None, str | None]:
    normalized_name = (executable_name or "").strip().lower()
    normalized_help = help_text.lower()

    for preset in KNOWN_CLI_PRESETS:
        if normalized_name in preset.executable_names:
            return preset, "executable_name"

    for preset in KNOWN_CLI_PRESETS:
        if any(hint.lower() in normalized_help for hint in preset.help_hints):
            return preset, "help_text"

    return None, None


def preset_for_executable_name(executable_name: str | None) -> KnownCliPreset | None:
    normalized_name = (executable_name or "").strip().lower()
    for preset in KNOWN_CLI_PRESETS:
        if normalized_name in preset.executable_names:
            return preset
    return None
