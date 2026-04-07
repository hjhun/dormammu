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


if __name__ == "__main__":
    unittest.main()
