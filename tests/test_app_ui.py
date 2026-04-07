from __future__ import annotations

import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest

try:
    from fastapi.testclient import TestClient
except ModuleNotFoundError:  # pragma: no cover - optional dependency in test env
    TestClient = None

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.app import create_app
from dormammu.config import AppConfig
from dormammu.state import StateRepository


@unittest.skipIf(TestClient is None, "fastapi is not installed in the current test environment")
class LocalUiTests(unittest.TestCase):
    def test_summary_and_files_endpoints_expose_phase_5_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            config = self._load_config(root)
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(active_roadmap_phase_ids=["phase_5"])
            (root / ".dev" / "continuation_prompt.txt").write_text(
                "continue from the saved repo state\n",
                encoding="utf-8",
            )

            with TestClient(create_app(config)) as client:
                summary = client.get("/api/state/summary")
                self.assertEqual(summary.status_code, 200)
                payload = summary.json()
                self.assertEqual(payload["workflow"]["roadmap"]["active_phase_ids"], ["phase_5"])
                self.assertTrue(payload["files"]["dashboard"]["exists"])
                self.assertFalse(payload["files"]["prompt_artifact"]["exists"])
                self.assertIsNone(payload["files"]["prompt_artifact"]["path"])

                dashboard = client.get("/api/state/files/dashboard")
                self.assertEqual(dashboard.status_code, 200)
                self.assertIn("# DASHBOARD", dashboard.json()["content"])

                continuation = client.get("/api/state/files/continuation")
                self.assertEqual(continuation.status_code, 200)
                self.assertIn("continue from the saved repo state", continuation.json()["content"])

                ui = client.get("/")
                self.assertEqual(ui.status_code, 200)
                self.assertIn("Run setup", ui.text)
                self.assertIn("Run details", ui.text)

    def test_start_run_endpoint_executes_loop_and_exposes_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_cli(root)
            config = self._load_config(root)
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(active_roadmap_phase_ids=["phase_5"])

            with TestClient(create_app(config)) as client:
                response = client.post(
                    "/api/runs/start",
                    json={
                        "agent_cli": str(fake_cli),
                        "prompt": "Render the latest progress snapshot.",
                        "run_label": "ui-test",
                    },
                )
                self.assertEqual(response.status_code, 202)

                status_payload = None
                for _ in range(40):
                    status_payload = client.get("/api/runs/active").json()
                    if status_payload["status"] in {"completed", "failed"}:
                        break
                    time.sleep(0.1)

                self.assertIsNotNone(status_payload)
                self.assertEqual(status_payload["status"], "completed")
                self.assertEqual(status_payload["result"]["status"], "completed")

                stdout_payload = client.get("/api/state/logs/stdout").json()
                self.assertIn("PROMPT::Render the latest progress snapshot.", stdout_payload["content"])

                summary = client.get("/api/state/summary").json()
                self.assertEqual(summary["workflow"]["latest_run"]["exit_code"], 0)
                self.assertIsNone(summary["workflow"]["current_run"])
                self.assertTrue(summary["files"]["prompt_artifact"]["exists"])
                self.assertTrue(summary["files"]["metadata_artifact"]["exists"])

                prompt_file = client.get("/api/state/files/prompt_artifact").json()
                self.assertTrue(prompt_file["exists"])
                self.assertIn("Render the latest progress snapshot.", prompt_file["content"])

    def _load_config(self, root: Path) -> AppConfig:
        return AppConfig.load(repo_root=root).with_overrides(
            templates_dir=ROOT / "templates",
            frontend_dir=ROOT / "frontend",
        )

    def _seed_repo(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / "AGENTS.md").write_text("bootstrap\n", encoding="utf-8")

    def _write_fake_cli(self, root: Path) -> Path:
        script = root / "fake-ui-agent"
        script.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                from pathlib import Path
                import sys

                def main() -> int:
                    args = sys.argv[1:]
                    if "--help" in args:
                        print("usage: fake-ui-agent [--prompt-file PATH]")
                        return 0

                    prompt = ""
                    if "--prompt-file" in args:
                        index = args.index("--prompt-file")
                        prompt = Path(args[index + 1]).read_text(encoding="utf-8")
                    else:
                        prompt = sys.stdin.read()

                    print(f"PROMPT::{{prompt.strip()}}")
                    return 0

                raise SystemExit(main())
                """
            ),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script


if __name__ == "__main__":
    unittest.main()
