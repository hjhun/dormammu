"""Scenario-based regression tests for Ralph-inspired improvements.

Covers four features introduced in the dormammu/ralph comparison work:
  1. Codebase Patterns accumulation (.dev/PATTERNS.md)
  2. <promise>COMPLETE</promise> self-completion signal
  3. PRD agent skill file existence and structure
  4. Dashboard Mermaid workflow diagram
"""
from __future__ import annotations

import stat
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from dormammu.agent import cli_adapter as cli_adapter_module
from dormammu.config import AppConfig
from dormammu.continuation import build_continuation_prompt
from dormammu.guidance import build_guidance_prompt
from dormammu.loop_runner import LoopRunRequest, LoopRunner
from dormammu.state import StateRepository
from dormammu.supervisor import SupervisorCheck, SupervisorReport
from unittest import mock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DASHBOARD_TMPL = "\n".join([
    "# DASHBOARD",
    "",
    "## Actual Progress",
    "",
    "- Goal: ${goal}",
    "- Prompt-driven scope: ${active_delivery_slice}",
    "- Active roadmap focus:",
    "${active_roadmap_focus}",
    "- Current workflow phase: ${active_phase}",
    "- Last completed workflow phase: ${last_completed_phase}",
    "- Supervisor verdict: `${supervisor_verdict}`",
    "- Escalation status: `${escalation_status}`",
    "- Resume point: ${resume_point}",
    "",
    "## In Progress",
    "",
    "${next_action}",
    "",
    "## Progress Notes",
    "",
    "${notes}",
    "",
    "## Risks And Watchpoints",
    "",
    "${risks_and_watchpoints}",
    "",
])

_PLAN_TMPL = "\n".join([
    "# PLAN",
    "",
    "## Prompt-Derived Implementation Plan",
    "",
    "${task_items}",
    "",
    "## Resume Checkpoint",
    "",
    "${resume_checkpoint}",
    "",
])

_PATTERNS_TMPL = "\n".join([
    "# Codebase Patterns",
    "",
    "This file accumulates reusable patterns discovered during agent runs.",
    "",
    "## Patterns",
    "",
    "(no patterns recorded yet — add entries as you discover them)",
    "",
])


def _seed_repo(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "AGENTS.md").write_text("bootstrap\n", encoding="utf-8")
    templates = root / "templates" / "dev"
    templates.mkdir(parents=True, exist_ok=True)
    (templates / "dashboard.md.tmpl").write_text(_DASHBOARD_TMPL, encoding="utf-8")
    (templates / "plan.md.tmpl").write_text(_PLAN_TMPL, encoding="utf-8")
    (templates / "patterns.md.tmpl").write_text(_PATTERNS_TMPL, encoding="utf-8")


def _make_supervisor_report(
    *,
    verdict: str = "rework_required",
    checks: tuple = (),
    recommended_next_phase: str | None = None,
) -> SupervisorReport:
    return SupervisorReport(
        generated_at="2026-04-12T00:00:00+09:00",
        verdict=verdict,
        escalation=verdict,
        summary="Test supervisor report.",
        checks=checks,
        latest_run_id="run-001",
        changed_files=(),
        required_paths=(),
        report_path=None,
        recommended_next_phase=recommended_next_phase,
    )


def _write_promise_cli(root: Path, *, exit_code: int = 0, emit_promise: bool = True) -> Path:
    """Fake agent CLI that optionally emits <promise>COMPLETE</promise>."""
    script = root / "fake-promise-cli"
    promise_line = 'print("<promise>COMPLETE</promise>")' if emit_promise else '# no promise'
    script.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import sys
            args = sys.argv[1:]
            if "--help" in args:
                print("usage: fake-promise-cli [--prompt-file PATH]")
                raise SystemExit(0)
            print("Working...")
            {promise_line}
            raise SystemExit({exit_code})
            """
        ),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def _write_fail_then_promise_cli(root: Path, *, promise_on_attempt: int = 2) -> Path:
    """Fake CLI that fails for the first N-1 attempts then emits <promise>COMPLETE</promise>."""
    script = root / "fake-delayed-promise-cli"
    counter = root / ".promise-attempt"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!{sys.executable}
            import sys
            from pathlib import Path

            COUNTER = Path({str(counter)!r})
            PROMISE_ON = {promise_on_attempt}

            args = sys.argv[1:]
            if "--help" in args:
                print("usage: fake-delayed-promise-cli [--prompt-file PATH]")
                raise SystemExit(0)

            attempt = int(COUNTER.read_text()) + 1 if COUNTER.exists() else 1
            COUNTER.write_text(str(attempt))

            if attempt >= PROMISE_ON:
                print("<promise>COMPLETE</promise>")
            else:
                print(f"Attempt {{attempt}}: not done yet")

            raise SystemExit(0)
            """
        ),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


# ---------------------------------------------------------------------------
# 1. Codebase Patterns accumulation
# ---------------------------------------------------------------------------

class PatternsBootstrapTests(unittest.TestCase):
    """Scenario: .dev/PATTERNS.md is created during bootstrap and persists."""

    def test_bootstrap_creates_patterns_file_at_dev_root(self) -> None:
        """First bootstrap creates .dev/PATTERNS.md from the template."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            config = AppConfig.load(repo_root=root)
            StateRepository(config).ensure_bootstrap_state(goal="Test goal")

            patterns_path = root / ".dev" / "PATTERNS.md"
            self.assertTrue(
                patterns_path.exists(),
                ".dev/PATTERNS.md must be created during bootstrap",
            )
            content = patterns_path.read_text(encoding="utf-8")
            self.assertIn("Codebase Patterns", content)

    def test_patterns_file_survives_prompt_change_reset(self) -> None:
        """When the prompt changes and bootstrap regenerates DASHBOARD/PLAN,
        PATTERNS.md is preserved (not reset or deleted)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            config = AppConfig.load(repo_root=root)
            repository = StateRepository(config)

            repository.ensure_bootstrap_state(
                goal="First goal",
                prompt_text="Implement alpha feature.",
            )
            patterns_path = root / ".dev" / "PATTERNS.md"
            # Simulate agent appending a real pattern
            patterns_path.write_text(
                "# Codebase Patterns\n\n## Patterns\n\n- Use dataclasses for models.\n",
                encoding="utf-8",
            )
            original_patterns = patterns_path.read_text(encoding="utf-8")

            # Second bootstrap with a different prompt should NOT clear PATTERNS.md
            repository.ensure_bootstrap_state(
                goal="Second goal",
                prompt_text="Implement beta feature.",
            )

            self.assertEqual(
                patterns_path.read_text(encoding="utf-8"),
                original_patterns,
                "PATTERNS.md must not be reset when bootstrap regenerates other state files",
            )

    def test_patterns_file_not_recreated_if_already_exists(self) -> None:
        """If PATTERNS.md already has content, bootstrap does not overwrite it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            config = AppConfig.load(repo_root=root)
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(goal="Init")

            patterns_path = root / ".dev" / "PATTERNS.md"
            custom_content = "# Codebase Patterns\n\n## Patterns\n\n- Always write tests first.\n"
            patterns_path.write_text(custom_content, encoding="utf-8")

            # Bootstrap again — PATTERNS.md must remain untouched
            repository.ensure_bootstrap_state(goal="Re-init")

            self.assertEqual(patterns_path.read_text(encoding="utf-8"), custom_content)

    def test_read_patterns_text_returns_content(self) -> None:
        """read_patterns_text() returns the content of .dev/PATTERNS.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            config = AppConfig.load(repo_root=root)
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(goal="Init")

            patterns_path = root / ".dev" / "PATTERNS.md"
            patterns_path.write_text(
                "# Codebase Patterns\n\n## Patterns\n\n- Prefer Path over str.\n",
                encoding="utf-8",
            )

            text = repository.read_patterns_text()
            self.assertIn("Prefer Path over str", text)

    def test_read_patterns_text_returns_empty_when_file_missing(self) -> None:
        """read_patterns_text() returns empty string when PATTERNS.md does not exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            config = AppConfig.load(repo_root=root)
            repository = StateRepository(config)
            # Do not bootstrap — PATTERNS.md should not exist
            self.assertEqual(repository.read_patterns_text(), "")


class PatternsGuidanceInjectionTests(unittest.TestCase):
    """Scenario: patterns_text is injected into guidance prompts correctly."""

    def test_non_default_patterns_appear_in_guidance_prompt(self) -> None:
        """Patterns with real content are included in the guidance prompt."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            patterns_text = "# Codebase Patterns\n\n## Patterns\n\n- Use frozen dataclasses.\n"
            result = build_guidance_prompt(
                "Implement the feature.",
                guidance_files=[],
                repo_root=root,
                patterns_text=patterns_text,
            )
            self.assertIn("frozen dataclasses", result)
            self.assertIn("PATTERNS.md", result)
            self.assertIn("Implement the feature.", result)

    def test_default_placeholder_patterns_are_not_injected(self) -> None:
        """The default placeholder text in a fresh PATTERNS.md is not injected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            placeholder = "(no patterns recorded yet — add entries as you discover them)"
            patterns_text = f"# Codebase Patterns\n\n## Patterns\n\n{placeholder}\n"
            result = build_guidance_prompt(
                "Implement the feature.",
                guidance_files=[],
                repo_root=root,
                patterns_text=patterns_text,
            )
            self.assertNotIn("PATTERNS.md", result)
            self.assertIn("Implement the feature.", result)

    def test_none_patterns_text_does_not_change_guidance_prompt(self) -> None:
        """When patterns_text is None and no guidance files exist, prompt is returned as-is."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            prompt = "Implement the feature."
            result = build_guidance_prompt(
                prompt,
                guidance_files=[],
                repo_root=root,
                patterns_text=None,
            )
            self.assertEqual(result, prompt)


class PatternsContinuationInjectionTests(unittest.TestCase):
    """Scenario: patterns_text flows through continuation prompts."""

    def test_non_default_patterns_appear_in_continuation_prompt(self) -> None:
        """Real patterns content is included in continuation prompts."""
        report = _make_supervisor_report()
        patterns_text = "# Codebase Patterns\n\n## Patterns\n\n- Keep modules small.\n"

        continuation = build_continuation_prompt(
            latest_run={"run_id": "r1", "artifacts": {}},
            report=report,
            next_task="Continue",
            original_prompt_text="Do the work.",
            patterns_text=patterns_text,
        )

        self.assertIn("Keep modules small", continuation.text)
        self.assertIn(".dev/PATTERNS.md", continuation.text)
        self.assertIn("append any new patterns", continuation.text)

    def test_default_placeholder_not_injected_in_continuation(self) -> None:
        """Default placeholder patterns are silently skipped in continuation prompts."""
        report = _make_supervisor_report()
        placeholder = "(no patterns recorded yet — add entries as you discover them)"
        patterns_text = f"# Codebase Patterns\n\n## Patterns\n\n{placeholder}\n"

        continuation = build_continuation_prompt(
            latest_run={"run_id": "r2", "artifacts": {}},
            report=report,
            next_task="Continue",
            original_prompt_text="Do the work.",
            patterns_text=patterns_text,
        )

        self.assertNotIn(".dev/PATTERNS.md", continuation.text)

    def test_patterns_injected_in_continuation_loop(self) -> None:
        """End-to-end: when the loop retries, the continuation prompt includes patterns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)

            # Write real patterns before first run
            (root / ".dev").mkdir(parents=True, exist_ok=True)
            (root / ".dev" / "PATTERNS.md").write_text(
                "# Codebase Patterns\n\n## Patterns\n\n- Always use Path not str.\n",
                encoding="utf-8",
            )

            # Fake CLI that never creates done.txt (forces retry + continuation)
            never_done = root / "never-done-cli"
            never_done.write_text(
                textwrap.dedent(
                    f"""\
                    #!{sys.executable}
                    import sys
                    args = sys.argv[1:]
                    if "--help" in args:
                        print("usage: never-done-cli")
                        raise SystemExit(0)
                    print("I did not finish.")
                    raise SystemExit(0)
                    """
                ),
                encoding="utf-8",
            )
            never_done.chmod(never_done.stat().st_mode | stat.S_IEXEC)

            config = AppConfig.load(repo_root=root)
            repository = StateRepository(config)
            with mock.patch.object(cli_adapter_module.time, "sleep", return_value=None):
                LoopRunner(config, repository=repository).run(
                    LoopRunRequest(
                        cli_path=never_done,
                        prompt_text="Implement the feature.",
                        repo_root=root,
                        max_retries=1,
                        required_paths=("done.txt",),
                        expected_roadmap_phase_id="phase_4",
                    )
                )

            # Inspect the continuation prompt written by the runner
            import json
            session_id = json.loads(
                (root / ".dev" / "session.json").read_text(encoding="utf-8")
            )["active_session_id"]
            cont_path = root / ".dev" / "sessions" / session_id / "continuation_prompt.txt"
            self.assertTrue(cont_path.exists(), "continuation_prompt.txt must be written on retry")
            cont_text = cont_path.read_text(encoding="utf-8")
            self.assertIn("Always use Path not str", cont_text)
            self.assertIn(".dev/PATTERNS.md", cont_text)


# ---------------------------------------------------------------------------
# 2. <promise>COMPLETE</promise> self-completion signal
# ---------------------------------------------------------------------------

class PromiseCompleteSignalTests(unittest.TestCase):
    """Scenario: agent self-declares completion via stdout tag."""

    def setUp(self) -> None:
        self._sleep_patcher = mock.patch.object(
            cli_adapter_module.time, "sleep", return_value=None
        )
        self._sleep_patcher.start()

    def tearDown(self) -> None:
        self._sleep_patcher.stop()

    def test_promise_signal_stops_loop_immediately(self) -> None:
        """Agent emitting <promise>COMPLETE</promise> terminates the loop on first attempt."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            cli = _write_promise_cli(root, exit_code=0, emit_promise=True)

            config = AppConfig.load(repo_root=root)
            result = LoopRunner(config, repository=StateRepository(config)).run(
                LoopRunRequest(
                    cli_path=cli,
                    prompt_text="Implement the feature.",
                    repo_root=root,
                    max_retries=5,
                    expected_roadmap_phase_id="phase_4",
                )
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.supervisor_verdict, "promise_complete")
            self.assertEqual(result.attempts_completed, 1,
                             "Loop must stop after the first promise signal")

    def test_promise_signal_bypasses_required_paths_check(self) -> None:
        """Promise stops the loop even if required_paths files were not created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            cli = _write_promise_cli(root, exit_code=0, emit_promise=True)

            config = AppConfig.load(repo_root=root)
            result = LoopRunner(config, repository=StateRepository(config)).run(
                LoopRunRequest(
                    cli_path=cli,
                    prompt_text="Implement the feature.",
                    repo_root=root,
                    max_retries=5,
                    required_paths=("this_file_will_never_exist.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.supervisor_verdict, "promise_complete")

    def test_nonzero_exit_code_suppresses_promise_signal(self) -> None:
        """Promise tag is ignored when the agent exits with a non-zero code."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            cli = _write_promise_cli(root, exit_code=1, emit_promise=True)

            config = AppConfig.load(repo_root=root)
            result = LoopRunner(config, repository=StateRepository(config)).run(
                LoopRunRequest(
                    cli_path=cli,
                    prompt_text="Implement the feature.",
                    repo_root=root,
                    max_retries=0,
                    expected_roadmap_phase_id="phase_4",
                )
            )

            # Nonzero exit code → promise should not trigger completion
            self.assertNotEqual(result.supervisor_verdict, "promise_complete")

    def test_no_promise_signal_follows_normal_supervisor_flow(self) -> None:
        """Without the promise tag the loop uses the normal supervisor validation path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            cli = _write_promise_cli(root, exit_code=0, emit_promise=False)

            config = AppConfig.load(repo_root=root)
            result = LoopRunner(config, repository=StateRepository(config)).run(
                LoopRunRequest(
                    cli_path=cli,
                    prompt_text="Implement the feature.",
                    repo_root=root,
                    max_retries=0,
                    required_paths=("missing.txt",),
                    expected_roadmap_phase_id="phase_4",
                )
            )

            # Supervisor should reject because required path is missing
            self.assertNotEqual(result.status, "completed")
            self.assertNotEqual(result.supervisor_verdict, "promise_complete")

    def test_promise_on_second_attempt_stops_loop(self) -> None:
        """Agent fails on attempt 1 and emits promise on attempt 2 → completes at attempt 2."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            cli = _write_fail_then_promise_cli(root, promise_on_attempt=2)

            config = AppConfig.load(repo_root=root)
            result = LoopRunner(config, repository=StateRepository(config)).run(
                LoopRunRequest(
                    cli_path=cli,
                    prompt_text="Implement the feature.",
                    repo_root=root,
                    max_retries=3,
                    expected_roadmap_phase_id="phase_4",
                )
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.supervisor_verdict, "promise_complete")
            self.assertEqual(result.attempts_completed, 2)

    def test_stdout_has_promise_complete_detects_tag(self) -> None:
        """Unit test: _stdout_has_promise_complete() correctly identifies the tag."""
        with tempfile.TemporaryDirectory() as tmpdir:
            stdout_path = Path(tmpdir) / "stdout.log"

            # Tag present
            stdout_path.write_text(
                "Working on it...\n<promise>COMPLETE</promise>\nDone.\n",
                encoding="utf-8",
            )
            self.assertTrue(LoopRunner._stdout_has_promise_complete(stdout_path))

            # Tag absent
            stdout_path.write_text(
                "Working on it...\nDone, but no promise.\n",
                encoding="utf-8",
            )
            self.assertFalse(LoopRunner._stdout_has_promise_complete(stdout_path))

            # File missing
            missing = Path(tmpdir) / "nonexistent.log"
            self.assertFalse(LoopRunner._stdout_has_promise_complete(missing))


# ---------------------------------------------------------------------------
# 3. PRD agent skill file existence and structure
# ---------------------------------------------------------------------------

class PrdAgentSkillTests(unittest.TestCase):
    """Scenario: prd-agent/SKILL.md exists and contains expected structural elements."""

    _SKILL_PATH = ROOT / "agents" / "skills" / "prd-agent" / "SKILL.md"

    def test_prd_agent_skill_file_exists(self) -> None:
        self.assertTrue(
            self._SKILL_PATH.exists(),
            f"agents/skills/prd-agent/SKILL.md must exist at {self._SKILL_PATH}",
        )

    def test_prd_skill_has_frontmatter_name(self) -> None:
        content = self._SKILL_PATH.read_text(encoding="utf-8")
        self.assertIn("name: prd-agent", content)

    def test_prd_skill_has_user_story_format(self) -> None:
        content = self._SKILL_PATH.read_text(encoding="utf-8")
        self.assertIn("Acceptance Criteria", content)

    def test_prd_skill_has_sizing_rules(self) -> None:
        content = self._SKILL_PATH.read_text(encoding="utf-8")
        self.assertIn("Sizing", content.replace("sizing", "Sizing"))

    def test_prd_skill_has_done_criteria(self) -> None:
        content = self._SKILL_PATH.read_text(encoding="utf-8")
        self.assertIn("Done Criteria", content)

    def test_prd_skill_references_planning_agent_handoff(self) -> None:
        content = self._SKILL_PATH.read_text(encoding="utf-8")
        self.assertIn("planning-agent", content)


# ---------------------------------------------------------------------------
# 4. Dashboard Mermaid workflow diagram
# ---------------------------------------------------------------------------

class DashboardMermaidTests(unittest.TestCase):
    """Scenario: the dashboard template and bootstrapped DASHBOARD.md include Mermaid."""

    def test_dashboard_template_contains_mermaid_block(self) -> None:
        """The production dashboard.md.tmpl contains a Mermaid flowchart."""
        tmpl_path = ROOT / "templates" / "dev" / "dashboard.md.tmpl"
        self.assertTrue(tmpl_path.exists(), "dashboard.md.tmpl must exist")
        content = tmpl_path.read_text(encoding="utf-8")
        self.assertIn("```mermaid", content)
        self.assertIn("flowchart", content)

    def test_bootstrapped_dashboard_contains_mermaid_diagram(self) -> None:
        """A freshly bootstrapped DASHBOARD.md includes the Mermaid diagram section."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)
            # Use production template so this test validates the real template
            prod_tmpl = ROOT / "templates" / "dev" / "dashboard.md.tmpl"
            (root / "templates" / "dev" / "dashboard.md.tmpl").write_text(
                prod_tmpl.read_text(encoding="utf-8"),
                encoding="utf-8",
            )

            config = AppConfig.load(repo_root=root)
            artifacts = StateRepository(config).ensure_bootstrap_state(goal="Mermaid test")

            dashboard_text = artifacts.dashboard.read_text(encoding="utf-8")
            self.assertIn("```mermaid", dashboard_text)
            self.assertIn("flowchart", dashboard_text)
            self.assertIn("commit", dashboard_text.lower())

    def test_mermaid_diagram_covers_all_workflow_phases(self) -> None:
        """The Mermaid diagram in the production template references every workflow phase."""
        tmpl_path = ROOT / "templates" / "dev" / "dashboard.md.tmpl"
        content = tmpl_path.read_text(encoding="utf-8")
        for phase in ("plan", "design", "develop", "test", "commit"):
            self.assertIn(phase, content.lower(),
                          f"Mermaid diagram must reference phase '{phase}'")


# ---------------------------------------------------------------------------
# 5. Cross-feature scenario: full loop with patterns + promise
# ---------------------------------------------------------------------------

class FullIntegrationScenarioTests(unittest.TestCase):
    """End-to-end scenario combining patterns injection and promise completion."""

    def setUp(self) -> None:
        self._sleep_patcher = mock.patch.object(
            cli_adapter_module.time, "sleep", return_value=None
        )
        self._sleep_patcher.start()

    def tearDown(self) -> None:
        self._sleep_patcher.stop()

    def test_loop_with_patterns_and_promise_completes_in_one_attempt(self) -> None:
        """Agent receives patterns in prompt, does the work, then emits the promise tag.

        Validates end-to-end that:
        - PATTERNS.md is created during bootstrap
        - Its content reaches the agent via the prompt
        - <promise>COMPLETE</promise> in stdout terminates the loop
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _seed_repo(root)

            config = AppConfig.load(repo_root=root)
            # Bootstrap so PATTERNS.md is created, then add real patterns
            StateRepository(config).ensure_bootstrap_state(goal="Integration test")
            (root / ".dev" / "PATTERNS.md").write_text(
                "# Codebase Patterns\n\n## Patterns\n\n- Use typed dicts for config.\n",
                encoding="utf-8",
            )

            # Fake CLI: prints the prompt it receives, then emits promise
            capturing_cli = root / "capturing-cli"
            captured_file = root / "captured_prompt.txt"
            capturing_cli.write_text(
                textwrap.dedent(
                    f"""\
                    #!{sys.executable}
                    import sys
                    from pathlib import Path

                    args = sys.argv[1:]
                    if "--help" in args:
                        print("usage: capturing-cli [--prompt-file PATH]")
                        raise SystemExit(0)

                    prompt = ""
                    if "--prompt-file" in args:
                        idx = args.index("--prompt-file")
                        prompt = Path(args[idx + 1]).read_text(encoding="utf-8")
                    else:
                        prompt = sys.stdin.read()

                    Path({str(captured_file)!r}).write_text(prompt, encoding="utf-8")
                    print("<promise>COMPLETE</promise>")
                    raise SystemExit(0)
                    """
                ),
                encoding="utf-8",
            )
            capturing_cli.chmod(capturing_cli.stat().st_mode | stat.S_IEXEC)

            # Simulate what _cli_handlers.py does: build the guidance prompt with patterns.
            repository = StateRepository(config)
            repository.ensure_bootstrap_state(goal="Integration test (second pass)")
            assembled_prompt = build_guidance_prompt(
                "Implement the feature.",
                guidance_files=config.guidance_files,
                repo_root=root,
                patterns_text=repository.read_patterns_text(),
            )

            result = LoopRunner(config, repository=repository).run(
                LoopRunRequest(
                    cli_path=capturing_cli,
                    prompt_text=assembled_prompt,
                    repo_root=root,
                    max_retries=3,
                    expected_roadmap_phase_id="phase_4",
                )
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.supervisor_verdict, "promise_complete")

            # Verify the patterns were injected into the prompt the agent received
            self.assertTrue(captured_file.exists())
            received_prompt = captured_file.read_text(encoding="utf-8")
            self.assertIn("typed dicts for config", received_prompt,
                          "PATTERNS.md content must be injected into the agent prompt")


if __name__ == "__main__":
    unittest.main()
