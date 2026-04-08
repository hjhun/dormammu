from __future__ import annotations

import re

from dormammu.agent.models import AutoApproveCandidate, AutoApproveInfo, CliCapabilities
from dormammu.agent.presets import match_known_preset


KNOWN_PROMPT_FILE_FLAGS = (
    "--prompt-file",
    "--input-file",
    "--message-file",
)
KNOWN_PROMPT_ARG_FLAGS = (
    "--prompt",
    "--message",
    "--input",
)
KNOWN_WORKDIR_FLAGS = (
    "--workdir",
    "--cwd",
    "-C",
)


AUTO_APPROVE_FLAG_PATTERN = re.compile(
    r"--[a-z0-9][a-z0-9-]*(?:approve|approval|permission|permissions|yes|auto)[a-z0-9-]*",
    re.IGNORECASE,
)


def _flag_present(help_text: str, flag: str) -> bool:
    return re.search(
        r"(?<![A-Za-z0-9_-])" + re.escape(flag) + r"(?![A-Za-z0-9_-])",
        help_text,
    ) is not None


def _first_matching_flag(help_text: str, candidates: tuple[str, ...]) -> str | None:
    for flag in candidates:
        if _flag_present(help_text, flag):
            return flag
    return None


def _risk_for_candidate(value: str) -> str:
    normalized = value.lower()
    if any(token in normalized for token in ("danger", "bypass", "skip-permissions")):
        return "high"
    if any(token in normalized for token in ("full-auto", "auto", "yes", "permission-mode")):
        return "medium"
    return "low"


def _detect_auto_approve(
    help_text: str,
    *,
    preset_candidates: tuple[AutoApproveCandidate, ...],
) -> AutoApproveInfo:
    candidates: list[AutoApproveCandidate] = list(preset_candidates)
    seen = {candidate.value for candidate in candidates}

    for match in AUTO_APPROVE_FLAG_PATTERN.findall(help_text):
        if match in seen:
            continue
        seen.add(match)
        candidates.append(
            AutoApproveCandidate(
                value=match,
                risk=_risk_for_candidate(match),
                source="help_text",
                summary="Detected in CLI help output and requires explicit operator review.",
            )
        )

    notes: list[str] = []
    if candidates:
        notes.append("Auto-approve candidates are advisory only in this slice.")
        if any(candidate.risk == "high" for candidate in candidates):
            notes.append(
                "High-risk candidates should remain opt-in and require explicit confirmation."
            )

    return AutoApproveInfo(
        supported=bool(candidates),
        requires_confirmation=bool(candidates),
        candidates=tuple(candidates),
        notes=tuple(notes),
    )


def parse_help_text(
    help_text: str,
    *,
    executable_name: str | None = None,
    help_exit_code: int = 0,
) -> CliCapabilities:
    preset, preset_source = match_known_preset(executable_name, help_text)
    preset_candidates = tuple(
        AutoApproveCandidate(
            value=item.value,
            risk=item.risk,
            source=f"preset:{preset.key}",
            summary=item.summary,
        )
        for item in (preset.auto_approve_candidates if preset is not None else ())
    )
    return CliCapabilities(
        help_flag="--help",
        prompt_file_flag=_first_matching_flag(help_text, KNOWN_PROMPT_FILE_FLAGS)
        or (preset.prompt_file_flag if preset is not None else None),
        prompt_arg_flag=_first_matching_flag(help_text, KNOWN_PROMPT_ARG_FLAGS)
        or (preset.prompt_arg_flag if preset is not None else None),
        workdir_flag=_first_matching_flag(help_text, KNOWN_WORKDIR_FLAGS)
        or (preset.workdir_flag if preset is not None else None),
        help_text=help_text,
        help_exit_code=help_exit_code,
        command_prefix=preset.command_prefix if preset is not None else (),
        prompt_positional=preset.prompt_positional if preset is not None else False,
        preset_key=preset.key if preset is not None else None,
        preset_label=preset.label if preset is not None else None,
        preset_source=preset_source,
        auto_approve=_detect_auto_approve(help_text, preset_candidates=preset_candidates),
    )
