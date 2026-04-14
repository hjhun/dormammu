from __future__ import annotations

from pathlib import Path


def prepend_cli_identity(prompt_text: str, cli_path: Path) -> str:
    """Prefix prompts with the target CLI identity once."""
    cli_name = cli_path.name or str(cli_path).strip() or "agent"
    header = f"[{cli_name}]"
    if prompt_text == header or prompt_text.startswith(f"{header}\n"):
        return prompt_text
    return f"{header}\n{prompt_text}"
