from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import stat
import sys
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.config import AppConfig
from dormammu.daemon.config import load_daemon_config
from dormammu.daemon.queue import prompt_sort_key
from dormammu.daemon.runner import DaemonRunner


class DaemonConfigTests(unittest.TestCase):
    def test_load_daemon_config_resolves_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            config_path = root / "ops" / "daemon.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            cli_path = root / "bin" / "fake-agent"
            cli_path.parent.mkdir(parents=True, exist_ok=True)
            cli_path.write_text("", encoding="utf-8")
            config_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "prompt_path": "../queue/prompts",
                        "result_path": "../queue/results",
                        "phases": self._phase_payload("./../bin/fake-agent"),
                    }
                ),
                encoding="utf-8",
            )

            app_config = AppConfig.load(repo_root=root)
            config = load_daemon_config(config_path, app_config=app_config)

            self.assertEqual(config.prompt_path, (root / "queue" / "prompts").resolve())
            self.assertEqual(config.result_path, (root / "queue" / "results").resolve())
            self.assertEqual(config.phases["plan"].agent_cli.path, cli_path.resolve())
            self.assertEqual(config.phases["plan"].skill_name, "planning-agent")
            self.assertTrue(config.phases["plan"].skill_path.exists())

    def test_load_daemon_config_rejects_missing_phase(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            config_path = root / "daemon.json"
            config_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "prompt_path": "./prompts",
                        "result_path": "./results",
                        "phases": {
                            "plan": {
                                "skill_name": "planning-agent",
                                "agent_cli": {"path": "codex"},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            app_config = AppConfig.load(repo_root=root)
            with self.assertRaises(RuntimeError):
                load_daemon_config(config_path, app_config=app_config)

    def test_load_daemon_config_resolves_explicit_skill_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            skill_path = root / "custom-skill.md"
            skill_path.write_text("# Custom Skill\n\nDo the custom thing.\n", encoding="utf-8")
            config_path = root / "daemon.json"
            config_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "prompt_path": "./prompts",
                        "result_path": "./results",
                        "phases": self._phase_payload("codex", skill_path=str(skill_path)),
                    }
                ),
                encoding="utf-8",
            )

            app_config = AppConfig.load(repo_root=root)
            config = load_daemon_config(config_path, app_config=app_config)

            self.assertIsNone(config.phases["plan"].skill_name)
            self.assertEqual(config.phases["plan"].skill_path, skill_path.resolve())

    def _phase_payload(self, cli_path: str, *, skill_path: str | None = None) -> dict[str, object]:
        return {
            phase_name: {
                **(
                    {"skill_path": skill_path}
                    if skill_path is not None
                    else {"skill_name": self._skill_name_for_phase(phase_name)}
                ),
                "agent_cli": {
                    "path": cli_path,
                    "input_mode": "file",
                    "extra_args": [],
                },
            }
            for phase_name in (
                "plan",
                "design",
                "develop",
                "build_and_deploy",
                "test_and_review",
                "commit",
            )
        }

    def _skill_name_for_phase(self, phase_name: str) -> str:
        return {
            "plan": "planning-agent",
            "design": "designing-agent",
            "develop": "developing-agent",
            "build_and_deploy": "building-and-deploying",
            "test_and_review": "testing-and-reviewing",
            "commit": "committing-agent",
        }[phase_name]

    def _seed_repo(self, root: Path) -> None:
        (root / "AGENTS.md").write_text("bootstrap\n", encoding="utf-8")
        templates = root / "templates" / "dev"
        templates.mkdir(parents=True, exist_ok=True)
        (templates / "dashboard.md.tmpl").write_text("# DASHBOARD\n\n- Goal: ${goal}\n", encoding="utf-8")
        (templates / "plan.md.tmpl").write_text("# PLAN\n\n${task_items}\n", encoding="utf-8")
        skills_dir = root / "agents" / "skills"
        for name in (
            "planning-agent",
            "designing-agent",
            "developing-agent",
            "building-and-deploying",
            "testing-and-reviewing",
            "committing-agent",
        ):
            skill_dir = skills_dir / name
            skill_dir.mkdir(parents=True, exist_ok=True)
            (skill_dir / "SKILL.md").write_text(f"# {name}\n\nUse {name}.\n", encoding="utf-8")


class DaemonQueueTests(unittest.TestCase):
    def test_prompt_sort_key_orders_numeric_then_alpha_then_plain(self) -> None:
        filenames = [
            "b-task.md",
            "_scratch.md",
            "010-build.md",
            "002-plan.md",
            "A-design.md",
        ]

        ordered = sorted(filenames, key=prompt_sort_key)

        self.assertEqual(
            ordered,
            ["002-plan.md", "010-build.md", "A-design.md", "b-task.md", "_scratch.md"],
        )


class DaemonRunnerTests(unittest.TestCase):
    def test_run_pending_once_processes_existing_prompts_in_sorted_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_cli(root)
            daemon_config_path = self._write_daemon_config(root, fake_cli)
            daemon_config = load_daemon_config(daemon_config_path, app_config=AppConfig.load(repo_root=root))
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            (daemon_config.prompt_path / "b-second.md").write_text("Second prompt\n", encoding="utf-8")
            (daemon_config.prompt_path / "001-first.md").write_text("First prompt\n", encoding="utf-8")

            config = AppConfig.load(repo_root=root)
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                processed = DaemonRunner(config, daemon_config).run_pending_once(watcher_backend="polling")

            self.assertEqual(processed, 2)
            first_result = (daemon_config.result_path / "001-first_RESULT.md").read_text(encoding="utf-8")
            second_result = (daemon_config.result_path / "b-second_RESULT.md").read_text(encoding="utf-8")
            self.assertIn("Status: `completed`", first_result)
            self.assertIn("Status: `completed`", second_result)
            stderr_text = stderr.getvalue()
            self.assertLess(stderr_text.index("001-first.md"), stderr_text.index("b-second.md"))

    def test_run_pending_once_skips_prompts_with_existing_result_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            self._seed_repo(root)
            fake_cli = self._write_fake_cli(root)
            daemon_config_path = self._write_daemon_config(root, fake_cli)
            daemon_config = load_daemon_config(daemon_config_path, app_config=AppConfig.load(repo_root=root))
            daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
            daemon_config.result_path.mkdir(parents=True, exist_ok=True)
            prompt_path = daemon_config.prompt_path / "001-first.md"
            prompt_path.write_text("First prompt\n", encoding="utf-8")
            (daemon_config.result_path / "001-first_RESULT.md").write_text("existing\n", encoding="utf-8")

            config = AppConfig.load(repo_root=root)
            processed = DaemonRunner(config, daemon_config).run_pending_once(watcher_backend="polling")

            self.assertEqual(processed, 0)

    def _seed_repo(self, root: Path) -> None:
        (root / "AGENTS.md").write_text("bootstrap\n", encoding="utf-8")
        templates = root / "templates" / "dev"
        templates.mkdir(parents=True, exist_ok=True)
        (templates / "dashboard.md.tmpl").write_text("# DASHBOARD\n\n- Goal: ${goal}\n", encoding="utf-8")
        (templates / "plan.md.tmpl").write_text("# PLAN\n\n${task_items}\n", encoding="utf-8")

    def _write_daemon_config(self, root: Path, fake_cli: Path) -> Path:
        config_path = root / "daemonize.json"
        config_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "prompt_path": "./queue/prompts",
                    "result_path": "./queue/results",
                    "watch": {
                        "backend": "polling",
                        "poll_interval_seconds": 1,
                        "settle_seconds": 0,
                    },
                    "queue": {
                        "allowed_extensions": [".md"],
                        "ignore_hidden_files": True,
                    },
                    "phases": {
                        phase_name: {
                            "skill_name": self._skill_name_for_phase(phase_name),
                            "agent_cli": {
                                "path": str(fake_cli),
                                "input_mode": "file",
                                "extra_args": ["--phase", phase_name],
                            },
                        }
                        for phase_name in (
                            "plan",
                            "design",
                            "develop",
                            "build_and_deploy",
                            "test_and_review",
                            "commit",
                        )
                    },
                }
            ),
            encoding="utf-8",
        )
        return config_path

    def _skill_name_for_phase(self, phase_name: str) -> str:
        return {
            "plan": "planning-agent",
            "design": "designing-agent",
            "develop": "developing-agent",
            "build_and_deploy": "building-and-deploying",
            "test_and_review": "testing-and-reviewing",
            "commit": "committing-agent",
        }[phase_name]

    def _write_fake_cli(self, root: Path) -> Path:
        script = root / "fake-agent"
        script.write_text(
            textwrap.dedent(
                f"""\
                #!{sys.executable}
                from pathlib import Path
                import sys

                def main() -> int:
                    args = sys.argv[1:]
                    if "--help" in args:
                        print("usage: fake-agent [--prompt-file PATH] [--phase NAME]")
                        return 0

                    prompt = ""
                    if "--prompt-file" in args:
                        index = args.index("--prompt-file")
                        prompt = Path(args[index + 1]).read_text(encoding="utf-8")
                    else:
                        prompt = sys.stdin.read()

                    phase = "unknown"
                    if "--phase" in args:
                        index = args.index("--phase")
                        phase = args[index + 1]

                    print(f"PHASE::{{phase}}")
                    print(f"PROMPT::{{prompt.strip()}}")
                    return 0

                raise SystemExit(main())
                """
            ),
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        return script
