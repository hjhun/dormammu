from __future__ import annotations


def select_agent_output(stdout: str | None, stderr: str | None) -> str:
    """Return the most useful agent output for stage parsing and persistence."""
    if stdout and stdout.strip():
        return stdout
    if stderr and stderr.strip():
        return stderr
    return stdout or stderr or ""
