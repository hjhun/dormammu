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
        auto_approve_candidates=(
            PresetAutoApproveCandidate(
                value="--yolo",
                risk="high",
                summary="Auto-accepts all actions and should remain opt-in.",
            ),
            PresetAutoApproveCandidate(
                value="--approval-mode yolo",
                risk="high",
                summary="Enables yolo approval mode and should remain opt-in.",
            ),
        ),
    ),
    KnownCliPreset(
        key="claude_code",
        label="Claude Code",
        executable_names=("claude", "claude-code"),
        help_hints=("--permission-mode", "--output-format", "bypassPermissions"),
        prompt_arg_flag="-p",
        auto_approve_candidates=(
            PresetAutoApproveCandidate(
                value="--permission-mode auto",
                risk="medium",
                summary="Starts Claude Code in auto permission mode.",
            ),
            PresetAutoApproveCandidate(
                value="--permission-mode bypassPermissions",
                risk="high",
                summary="Bypasses permission prompts and should remain opt-in.",
            ),
        ),
    ),
    KnownCliPreset(
        key="cline",
        label="Cline",
        executable_names=("cline",),
        help_hints=("-y", "cline"),
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
