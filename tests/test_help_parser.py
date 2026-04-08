from __future__ import annotations

from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.agent import parse_help_text


class HelpParserTests(unittest.TestCase):
    def test_parse_help_text_detects_known_flags(self) -> None:
        capabilities = parse_help_text(
            "usage: fake-agent [--prompt-file PATH] [--prompt TEXT] [--workdir DIR]"
        )

        self.assertEqual(capabilities.prompt_file_flag, "--prompt-file")
        self.assertEqual(capabilities.prompt_arg_flag, "--prompt")
        self.assertEqual(capabilities.workdir_flag, "--workdir")

    def test_parse_help_text_applies_aider_preset(self) -> None:
        capabilities = parse_help_text(
            "usage: aider [OPTIONS] [FILE ...]",
            executable_name="aider",
        )

        self.assertEqual(capabilities.preset_key, "aider")
        self.assertEqual(capabilities.prompt_file_flag, "--message-file")
        self.assertEqual(capabilities.prompt_arg_flag, "--message")
        self.assertIsNotNone(capabilities.auto_approve)
        self.assertTrue(capabilities.auto_approve.supported)
        self.assertEqual(capabilities.auto_approve.candidates[0].value, "--yes")

    def test_parse_help_text_detects_codex_preset_for_positional_exec(self) -> None:
        capabilities = parse_help_text(
            "Usage: codex [OPTIONS] [PROMPT]",
            executable_name="codex",
        )

        self.assertEqual(capabilities.preset_key, "codex")
        self.assertEqual(list(capabilities.command_prefix), ["exec"])
        self.assertTrue(capabilities.prompt_positional)


if __name__ == "__main__":
    unittest.main()
