from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
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
from dormammu.daemon.evaluator import EvaluatorRequest, EvaluatorStage
from dormammu.daemon.models import DaemonConfig, DaemonPromptResult, QueueConfig, WatchConfig
from dormammu.daemon.reports import ResultReportAuthor, render_result_markdown
from dormammu.daemon.runner import DaemonRunner
from dormammu.results import RunResult, StageResult
from dormammu.state import StateRepository
from dormammu.workspace import resolve_workspace_project_root


def _seed_repo(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, capture_output=True, text=True, check=True)
    (root / "AGENTS.md").write_text("bootstrap\n", encoding="utf-8")
    templates = root / "templates" / "dev"
    templates.mkdir(parents=True, exist_ok=True)
    (templates / "dashboard.md.tmpl").write_text("# DASHBOARD\n\n- Goal: ${goal}\n", encoding="utf-8")
    (templates / "plan.md.tmpl").write_text("# PLAN\n\n${task_items}\n", encoding="utf-8")
    (templates / "tasks.md.tmpl").write_text("# TASKS\n\n${task_items}\n", encoding="utf-8")
    (templates / "patterns.md.tmpl").write_text("# PATTERNS\n", encoding="utf-8")


def _app_config(repo_root: Path, home_dir: Path, *, active_agent_cli: Path | None = None) -> AppConfig:
    env = {key: value for key, value in os.environ.items() if key != "DORMAMMU_SESSIONS_DIR"}
    env["HOME"] = str(home_dir)
    config = AppConfig.load(repo_root=repo_root, env=env)
    if active_agent_cli is not None:
        config_path = repo_root / "dormammu.json"
        config_path.write_text(
            json.dumps({"active_agent_cli": str(active_agent_cli)}, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        config = AppConfig.load(repo_root=repo_root, env=env)
    return config


def _write_workspace_cli(root: Path, name: str) -> Path:
    script = root / name
    script.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import json
            import os
            import re
            import sys
            from pathlib import Path

            ROOT = Path({str(root)!r})

            def read_prompt() -> str:
                args = sys.argv[1:]
                if "--help" in args:
                    print("usage: {name} [--print] [--message-file FILE]")
                    sys.exit(0)
                if "--message-file" in args:
                    path = Path(args[args.index("--message-file") + 1])
                    return path.read_text(encoding="utf-8")
                if "--prompt-file" in args:
                    path = Path(args[args.index("--prompt-file") + 1])
                    return path.read_text(encoding="utf-8")
                for arg in reversed(args):
                    if not arg.startswith("-"):
                        candidate = Path(arg)
                        if candidate.exists():
                            return candidate.read_text(encoding="utf-8")
                        return arg
                return sys.stdin.read()

            def mark_complete(path: Path) -> None:
                if not path.exists():
                    return
                rewritten = []
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.startswith("- [ ] "):
                        rewritten.append(line.replace("- [ ] ", "- [O] ", 1))
                    else:
                        rewritten.append(line)
                path.write_text("\\n".join(rewritten) + "\\n", encoding="utf-8")

            prompt = read_prompt()

            if "Write a deterministic operator-facing Markdown result report." in prompt:
                match = re.search(r"Generated at: `([^`]+)`", prompt)
                generated_at = match.group(1) if match else "missing"
                print("# CLI Authored Result\\n")
                print("## Summary\\n")
                print(f"- Generated at: `{{generated_at}}`")
                print("- Status: `completed`")
                print("- Author: `configured-cli`")
                sys.exit(0)

            if "VERDICT:" in prompt and "Expected Output Path" in prompt:
                print("VERDICT: goal_achieved")
                sys.exit(0)

            if (
                "You are a requirement refiner." in prompt
                or "You are the requirement refiner." in prompt
                or "You are a planning agent." in prompt
                or "You are the planning agent." in prompt
                or "mandatory post-plan evaluator checkpoint" in prompt
            ):
                print("PRELUDE::ok")
                sys.exit(0)

            base_dev_dir = Path(os.environ["DORMAMMU_BASE_DEV_DIR"])
            sessions_dir = Path(os.environ["DORMAMMU_SESSIONS_DIR"])
            active_session_id = json.loads((base_dev_dir / "session.json").read_text(encoding="utf-8"))["active_session_id"]
            session_dir = sessions_dir / active_session_id
            for target in (
                session_dir / "PLAN.md",
                session_dir / "TASKS.md",
                base_dev_dir / "PLAN.md",
                base_dev_dir / "TASKS.md",
            ):
                mark_complete(target)
            (ROOT / "done.txt").write_text("done\\n", encoding="utf-8")
            print("DONE::ok")
            sys.exit(0)
            """
        ),
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _write_invalid_result_report_cli(root: Path, name: str) -> Path:
    script = root / name
    script.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import sys
            from pathlib import Path

            def read_prompt() -> str:
                args = sys.argv[1:]
                if "--prompt-file" in args:
                    path = Path(args[args.index("--prompt-file") + 1])
                    return path.read_text(encoding="utf-8")
                return sys.stdin.read()

            prompt = read_prompt()
            if "Write a deterministic operator-facing Markdown result report." in prompt:
                print("# Invalid Result")
                print("")
                print("## Summary")
                print("")
                print("- Status: `completed`")
                sys.exit(0)

            print("DONE::ok")
            sys.exit(0)
            """
        ),
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


class WorkspacePathResolverTests(unittest.TestCase):
    def test_home_relative_project_maps_under_workspace_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            repo_root = home_dir / "samba" / "github" / "dormammu"
            repo_root.mkdir(parents=True, exist_ok=True)

            result = resolve_workspace_project_root(
                repo_root=repo_root,
                home_dir=home_dir,
                global_home_dir=home_dir / ".dormammu",
            )

            self.assertEqual(
                result,
                home_dir / ".dormammu" / "workspace" / "samba" / "github" / "dormammu",
            )

    def test_outside_home_project_uses_deterministic_external_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            home_dir = root / "home"
            repo_root = root / "repo"
            home_dir.mkdir(parents=True, exist_ok=True)
            repo_root.mkdir(parents=True, exist_ok=True)

            first = resolve_workspace_project_root(
                repo_root=repo_root,
                home_dir=home_dir,
                global_home_dir=home_dir / ".dormammu",
            )
            second = resolve_workspace_project_root(
                repo_root=repo_root,
                home_dir=home_dir,
                global_home_dir=home_dir / ".dormammu",
            )

            self.assertEqual(first, second)
            self.assertEqual(first.parent.name, "_external")
            self.assertTrue(first.name.startswith("repo-"))


class WorkspaceBootstrapTests(unittest.TestCase):
    def test_bootstrap_writes_runtime_state_under_workspace_shadow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            home_dir = root / "home"
            repo_root = home_dir / "projects" / "demo"
            repo_root.mkdir(parents=True, exist_ok=True)
            _seed_repo(repo_root)

            config = _app_config(repo_root, home_dir)
            repository = StateRepository(config)
            artifacts = repository.ensure_bootstrap_state(goal="Workspace shadow test")

            self.assertTrue(config.base_dev_dir.exists())
            self.assertTrue(config.workspace_tmp_dir.exists())
            self.assertTrue(str(artifacts.session).startswith(str(config.workspace_project_root)))
            self.assertFalse((repo_root / ".dev" / "session.json").exists())

    def test_bootstrap_migrates_legacy_repo_dev_state_into_workspace_shadow(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            home_dir = root / "home"
            repo_root = home_dir / "projects" / "demo"
            repo_root.mkdir(parents=True, exist_ok=True)
            _seed_repo(repo_root)
            legacy_dev_dir = repo_root / ".dev"
            legacy_dev_dir.mkdir(parents=True, exist_ok=True)
            (legacy_dev_dir / "session.json").write_text(
                json.dumps({"session_id": "legacy-session", "custom": {"answer": 42}}),
                encoding="utf-8",
            )
            (legacy_dev_dir / "TASKS.md").write_text(
                "# TASKS\n\n- [O] Phase 1. Imported item\n",
                encoding="utf-8",
            )

            config = _app_config(repo_root, home_dir)
            repository = StateRepository(config)
            artifacts = repository.ensure_bootstrap_state(goal="Workspace shadow test")

            self.assertTrue(artifacts.session.exists())
            migrated = json.loads(artifacts.session.read_text(encoding="utf-8"))
            self.assertEqual(migrated["custom"]["answer"], 42)
            self.assertIn("Imported item", artifacts.plan.read_text(encoding="utf-8"))
            self.assertEqual(
                json.loads((config.base_dev_dir / "session.json").read_text(encoding="utf-8"))[
                    "active_session_id"
                ],
                "legacy-session",
            )

    def test_bootstrap_respects_sessions_dir_override_without_reverting_to_repo_local_dev(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            home_dir = root / "home"
            repo_root = home_dir / "projects" / "demo"
            repo_root.mkdir(parents=True, exist_ok=True)
            _seed_repo(repo_root)
            sessions_dir = root / "custom-sessions"

            env = dict(os.environ)
            env["HOME"] = str(home_dir)
            env["DORMAMMU_SESSIONS_DIR"] = str(sessions_dir)
            config = AppConfig.load(repo_root=repo_root, env=env)
            repository = StateRepository(config)
            artifacts = repository.ensure_bootstrap_state(goal="Workspace shadow test")

            self.assertTrue(str(artifacts.session).startswith(str(sessions_dir.resolve())))
            self.assertTrue((config.base_dev_dir / "session.json").exists())
            self.assertFalse((repo_root / ".dev" / "session.json").exists())


class DaemonWorkspaceTests(unittest.TestCase):
    def test_load_daemon_config_uses_global_results_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            home_dir = root / "home"
            repo_root = root / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            _seed_repo(repo_root)
            config = _app_config(repo_root, home_dir)
            config_path = repo_root / "daemonize.json"
            config_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "prompt_path": "./queue/prompts",
                        "result_path": "./queue/results",
                    }
                ),
                encoding="utf-8",
            )

            daemon_config = load_daemon_config(config_path, app_config=config)

            self.assertEqual(daemon_config.result_path, config.results_dir)

    def test_daemon_writes_cli_authored_result_under_global_results_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            home_dir = root / "home"
            repo_root = root / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            _seed_repo(repo_root)
            cli_path = _write_workspace_cli(repo_root, "claude")
            config = _app_config(repo_root, home_dir, active_agent_cli=cli_path)
            prompt_dir = repo_root / "queue" / "prompts"
            prompt_dir.mkdir(parents=True, exist_ok=True)
            prompt_file = prompt_dir / "001-shadow.md"
            prompt_file.write_text("Create done.txt and finish.\n", encoding="utf-8")

            daemon_config = DaemonConfig(
                schema_version=1,
                config_path=repo_root / "daemonize.json",
                prompt_path=prompt_dir,
                result_path=config.results_dir,
                watch=WatchConfig(backend="polling", poll_interval_seconds=1, settle_seconds=0),
                queue=QueueConfig(allowed_extensions=(".md",), ignore_hidden_files=True),
            )

            processed = DaemonRunner(config, daemon_config).run_pending_once(watcher_backend="polling")

            result_path = config.results_dir / "001-shadow_RESULT.md"
            self.assertEqual(processed, 1)
            self.assertTrue(result_path.exists())
            result_text = result_path.read_text(encoding="utf-8")
            self.assertIn("# CLI Authored Result", result_text)
            self.assertIn("Generated at:", result_text)
            self.assertFalse((repo_root / ".dev" / "session.json").exists())


class WorkspaceTempCleanupTests(unittest.TestCase):
    def test_evaluator_uses_workspace_tmp_and_cleans_up_successfully(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            home_dir = root / "home"
            repo_root = root / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            _seed_repo(repo_root)
            cli_path = _write_workspace_cli(repo_root, "aider")
            config = _app_config(repo_root, home_dir, active_agent_cli=cli_path)

            dev_dir = config.base_dev_dir
            dev_dir.mkdir(parents=True, exist_ok=True)
            (dev_dir / "logs").mkdir(parents=True, exist_ok=True)
            (dev_dir / "PLAN.md").write_text("# PLAN\n", encoding="utf-8")
            (dev_dir / "DASHBOARD.md").write_text("# DASHBOARD\n", encoding="utf-8")
            (dev_dir / "WORKFLOWS.md").write_text("# WORKFLOWS\n", encoding="utf-8")
            goal_file = repo_root / "goals" / "shadow.md"
            goal_file.parent.mkdir(parents=True, exist_ok=True)
            goal_file.write_text("Shadow goal\n", encoding="utf-8")

            request = EvaluatorRequest(
                cli=cli_path,
                model=None,
                goal_file_path=goal_file,
                goal_text="Shadow goal",
                repo_root=repo_root,
                dev_dir=dev_dir,
                tmp_dir=config.workspace_tmp_dir,
                agents_dir=config.agents_dir,
                runtime_paths_text=config.runtime_path_prompt(),
                next_goal_strategy="none",
                stem="shadow",
                date_str="20260419",
            )

            result = EvaluatorStage().run(request)

            self.assertEqual(result.status, "completed")
            self.assertTrue(config.workspace_tmp_dir.exists())
            self.assertEqual(list(config.workspace_tmp_dir.iterdir()), [])


class ResultReportAuthorTests(unittest.TestCase):
    def test_daemon_prompt_result_exposes_canonical_run_result_fields(self) -> None:
        run_result = RunResult(
            status="completed",
            attempts_completed=2,
            retries_used=1,
            max_retries=3,
            max_iterations=4,
            latest_run_id="run-shadow",
            supervisor_verdict="needs_work",
            report_path=Path("/tmp/supervisor.md"),
            continuation_prompt_path=Path("/tmp/continue.txt"),
            summary="Stage 'reviewer' concluded with verdict 'needs_work'.",
            stage_results=(
                StageResult(
                    role="reviewer",
                    stage_name="reviewer",
                    status="completed",
                    verdict="needs_work",
                    output="VERDICT: NEEDS_WORK",
                ),
            ),
        )
        result = DaemonPromptResult(
            prompt_path=Path("/tmp/queue/001-shadow.md"),
            result_path=Path("/tmp/results/001-shadow_RESULT.md"),
            status="completed",
            started_at="2026-04-19T00:00:00+00:00",
            completed_at="2026-04-19T00:01:00+00:00",
            watcher_backend="polling",
            sort_key=(0, 1, "001-shadow.md"),
            session_id="shadow-session",
            run_result=run_result,
        )

        payload = result.to_dict()

        self.assertEqual(payload["attempts_completed"], 2)
        self.assertEqual(payload["supervisor_verdict"], "needs_work")
        self.assertEqual(payload["summary"], "Stage 'reviewer' concluded with verdict 'needs_work'.")
        self.assertEqual(payload["stage_results"][0]["role"], "reviewer")
        self.assertEqual(payload["retry"]["attempt"], 2)
        self.assertEqual(payload["run_result"]["status"], "completed")

    def test_result_report_author_uses_configured_cli_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            home_dir = root / "home"
            repo_root = root / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            _seed_repo(repo_root)
            cli_path = _write_workspace_cli(repo_root, "claude")
            config = _app_config(repo_root, home_dir, active_agent_cli=cli_path)
            config.logs_dir.mkdir(parents=True, exist_ok=True)

            result = DaemonPromptResult(
                prompt_path=repo_root / "queue" / "001-shadow.md",
                result_path=config.results_dir / "001-shadow_RESULT.md",
                status="completed",
                started_at="2026-04-19T00:00:00+00:00",
                completed_at="2026-04-19T00:01:00+00:00",
                watcher_backend="polling",
                sort_key=(0, 1, "001-shadow.md"),
                session_id="shadow-session",
            )

            authored = ResultReportAuthor(config).render(result)

            self.assertIn("# CLI Authored Result", authored)
            self.assertIn("Generated at:", authored)

    def test_result_report_author_raises_when_cli_output_omits_generated_at(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            home_dir = root / "home"
            repo_root = root / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            _seed_repo(repo_root)
            cli_path = _write_invalid_result_report_cli(repo_root, "broken-cli")
            config = _app_config(repo_root, home_dir, active_agent_cli=cli_path)

            result = DaemonPromptResult(
                prompt_path=repo_root / "queue" / "001-shadow.md",
                result_path=config.results_dir / "001-shadow_RESULT.md",
                status="completed",
                started_at="2026-04-19T00:00:00+00:00",
                completed_at="2026-04-19T00:01:00+00:00",
                watcher_backend="polling",
                sort_key=(0, 1, "001-shadow.md"),
                session_id="shadow-session",
            )

            with self.assertRaises(RuntimeError):
                ResultReportAuthor(config).render(result)

    def test_fallback_result_report_renders_stage_results_from_run_result(self) -> None:
        result = DaemonPromptResult(
            prompt_path=Path("/tmp/queue/001-shadow.md"),
            result_path=Path("/tmp/results/001-shadow_RESULT.md"),
            status="completed",
            started_at="2026-04-19T00:00:00+00:00",
            completed_at="2026-04-19T00:01:00+00:00",
            watcher_backend="polling",
            sort_key=(0, 1, "001-shadow.md"),
            session_id="shadow-session",
            run_result=RunResult(
                status="completed",
                attempts_completed=1,
                retries_used=0,
                max_retries=0,
                max_iterations=1,
                latest_run_id="run-shadow",
                supervisor_verdict="needs_work",
                report_path=Path("/tmp/supervisor.md"),
                continuation_prompt_path=None,
                summary="Stage 'reviewer' concluded with verdict 'needs_work'.",
                stage_results=(
                    StageResult(
                        role="reviewer",
                        stage_name="reviewer",
                        status="completed",
                        verdict="needs_work",
                        output="VERDICT: NEEDS_WORK",
                    ),
                ),
            ),
        )

        rendered = render_result_markdown(result)

        self.assertIn("## Stage Results", rendered)
        self.assertIn("### reviewer", rendered)
        self.assertIn("- Verdict: `needs_work`", rendered)
        self.assertIn("## Artifacts", rendered)


if __name__ == "__main__":
    unittest.main()
