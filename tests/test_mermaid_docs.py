from __future__ import annotations

import re
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MERMAID_BLOCK_RE = re.compile(r"```mermaid\n(.*?)```", re.DOTALL)


class MermaidDocsTests(unittest.TestCase):
    """Regression checks for Mermaid syntax used in public docs."""

    def test_mermaid_blocks_do_not_use_escaped_newlines_in_labels(self) -> None:
        """Use HTML breaks instead of escaped newlines so labels render correctly."""
        for relative_path in ("README.md", "docs/GUIDE.md"):
            with self.subTest(path=relative_path):
                content = (ROOT / relative_path).read_text(encoding="utf-8")
                mermaid_blocks = MERMAID_BLOCK_RE.findall(content)
                self.assertTrue(mermaid_blocks, f"{relative_path} should contain Mermaid blocks")
                for block in mermaid_blocks:
                    self.assertNotIn("\\n", block)
