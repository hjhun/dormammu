from __future__ import annotations

from pathlib import Path

from dormammu.agent.models import AgentRunRequest, CliCapabilities, CommandPlan


def _resolve_prompt_mode(request: AgentRunRequest, capabilities: CliCapabilities) -> str:
    if request.input_mode != "auto":
        return request.input_mode
    if request.prompt_flag or capabilities.prompt_file_flag:
        return "file"
    if capabilities.prompt_arg_flag:
        return "arg"
    return "stdin"


def build_command_plan(
    request: AgentRunRequest,
    capabilities: CliCapabilities,
    *,
    prompt_path: Path,
) -> CommandPlan:
    prompt_mode = _resolve_prompt_mode(request, capabilities)
    argv = [str(request.cli_path)]
    stdin_input: str | None = None

    if prompt_mode == "file":
        prompt_flag = request.prompt_flag or capabilities.prompt_file_flag
        if prompt_flag is None:
            raise ValueError("No prompt file flag is available for file mode.")
        argv.extend([prompt_flag, str(prompt_path)])
    elif prompt_mode == "arg":
        prompt_flag = request.prompt_flag or capabilities.prompt_arg_flag
        if prompt_flag is None:
            raise ValueError("No prompt argument flag is available for arg mode.")
        argv.extend([prompt_flag, request.prompt_text])
    elif prompt_mode == "stdin":
        stdin_input = request.prompt_text
    else:
        raise ValueError(f"Unsupported prompt mode: {prompt_mode}")

    argv.extend(request.extra_args)
    return CommandPlan(argv=argv, prompt_mode=prompt_mode, stdin_input=stdin_input)
