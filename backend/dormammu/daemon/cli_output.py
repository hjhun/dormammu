from __future__ import annotations


def select_agent_output(stdout: str | None, stderr: str | None) -> str:
    """Return the most useful agent output for stage parsing and persistence."""
    if stdout and stdout.strip():
        return stdout
    if stderr and stderr.strip():
        return stderr
    return stdout or stderr or ""


# CLI-specific model flag mapping shared across daemon modules.
_MODEL_FLAGS: dict[str, str] = {
    "claude": "--model",
    "claude-code": "--model",
    "gemini": "--model",
    "codex": "-m",
    "aider": "--model",
}


def model_args(executable_name: str, model: str | None) -> list[str]:
    """Return the model flag arguments ``["--model", model]`` for the given CLI.

    Returns an empty list when ``model`` is ``None`` or the CLI name is unknown.
    This is the single authoritative implementation used by both
    ``PipelineRunner`` and ``GoalsScheduler``.
    """
    if model is None:
        return []
    flag = _MODEL_FLAGS.get(executable_name.lower())
    if flag is None:
        return []
    return [flag, model]
