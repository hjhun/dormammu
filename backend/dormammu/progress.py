from __future__ import annotations

import re
import threading
from typing import TextIO


_PIPELINE_CLI_RE = re.compile(r"^=== pipeline (\w+) cli ===$")

_ROLE_SKILL_LABELS = {
    "refiner": "refining-agent",
    "planner": "planning-agent",
    "evaluator": "evaluating-agent",
    "plan_evaluator": "evaluating-agent",
    "designer": "designing-agent",
    "developer": "developing-agent",
    "tester": "tester",
    "reviewer": "testing-and-reviewing",
    "committer": "committing-agent",
    "supervisor": "supervising-agent",
}


def skill_label_for_role(role: str) -> str:
    return _ROLE_SKILL_LABELS.get(role, role)


class ConciseProgressFilter:
    """Reduce live operator output to prompt/stage summaries."""

    def __init__(self) -> None:
        self._section: str | None = None

    def feed_line(self, line: str) -> list[str]:
        stripped = line.rstrip("\n")
        text = stripped.strip()
        if not text:
            return []
        if text.startswith("stage: ") or text.startswith("prompt: ") or text.startswith("prompt summary: "):
            return [text]

        pipeline_cli = _PIPELINE_CLI_RE.match(text)
        if pipeline_cli is not None:
            role = pipeline_cli.group(1)
            self._section = f"pipeline:{role}"
            return [f"stage: {role} [{skill_label_for_role(role)}]"]

        if text.startswith("=== pipeline ") and text.endswith(" ==="):
            self._section = "pipeline-output"
            return []

        if text == "=== dormammu run ===":
            self._section = "run"
            return [text]
        if text == "=== dormammu daemonize ===":
            self._section = "daemon"
            return [text]
        if text == "=== dormammu resume state ===":
            self._section = "resume"
            return [text]
        if text == "=== dormammu loop attempt ===":
            self._section = "loop"
            return ["stage: develop (supervised loop)"]
        if text == "=== dormammu supervisor ===":
            self._section = "supervisor"
            return ["stage: supervisor verification"]
        if text == "=== dormammu promise ===":
            self._section = "promise"
            return ["stage: completion"]
        if text == "=== dormammu escalation ===":
            self._section = "escalation"
            return ["stage: escalation"]
        if text == "=== dormammu stagnation ===":
            self._section = "stagnation"
            return ["stage: stagnation"]
        if text == "=== dormammu command ===":
            self._section = "command"
            return []
        if text in {"=== DASHBOARD.md ===", "=== PLAN.md ==="}:
            self._section = "state-dump"
            return []
        if text.startswith("===") and text.endswith("==="):
            self._section = "other"
            return []

        if text.startswith("daemon prompt detected: "):
            return [f"prompt: {text[len('daemon prompt detected: '):].split(' (', 1)[0]}"]
        if text.startswith("daemon prompt summary: "):
            return [f"prompt summary: {text[len('daemon prompt summary: '):]}"]
        if text.startswith("daemon prompt ") and " -> " in text:
            return [text]
        if text.startswith("goals scheduler: ") or text.startswith("autonomous scheduler: "):
            return [text]
        if text.startswith("daemon queue scan: waiting for prompt settle window"):
            return [text]

        if self._section == "run":
            return self._pass_prefixed(text, "command:", "session:")
        if self._section == "daemon":
            return self._pass_prefixed(text, "watcher:", "goals:", "autonomous:")
        if self._section == "resume":
            return self._pass_prefixed(
                text,
                "last status:",
                "attempts completed:",
                "retries used:",
                "last supervisor verdict:",
                "next action:",
            )
        if self._section == "loop":
            return self._pass_prefixed(text, "attempt:", "agent role:")
        if self._section == "supervisor":
            return self._pass_prefixed(text, "attempt:", "verdict:", "summary:")
        if self._section == "promise":
            return self._pass_prefixed(text, "attempt:")
        if self._section in {"escalation", "stagnation"}:
            return self._pass_non_verbose(text)
        if self._section in {"pipeline-output", "command", "state-dump"}:
            return []
        if text.startswith("Taking a short break"):
            return []
        if text.startswith("pipeline: runtime skills "):
            return []
        if text.startswith(
            (
                "repo root:",
                "daemon config:",
                "prompt path:",
                "result path:",
                "prompt detection:",
                "prompt lifecycle:",
                "progress log:",
            )
        ):
            return []
        if text.startswith(
            (
                "workdir:",
                "cli path:",
                "cli:",
                "prompt mode:",
                "command:",
                "stdout log:",
                "stderr log:",
                "target project:",
                "max iterations:",
                "runtime skills:",
            )
        ):
            return []
        return [text]

    @staticmethod
    def _pass_prefixed(text: str, *prefixes: str) -> list[str]:
        return [text] if text.startswith(prefixes) else []

    @staticmethod
    def _pass_non_verbose(text: str) -> list[str]:
        noisy_prefixes = (
            "workdir:",
            "cli path:",
            "cli:",
            "prompt mode:",
            "command:",
            "stdout log:",
            "stderr log:",
            "target project:",
            "max iterations:",
            "runtime skills:",
        )
        if text.startswith(noisy_prefixes):
            return []
        return [text]


class ConciseProgressStream:
    """TextIO-compatible wrapper that emits concise operator progress only."""

    encoding: str

    def __init__(self, base_stream: TextIO) -> None:
        self._base = base_stream
        self._filter = ConciseProgressFilter()
        self._line_buf = ""
        self._lock = threading.Lock()
        self.encoding = getattr(base_stream, "encoding", "utf-8")
        if hasattr(base_stream, "reset_session_log"):
            self.reset_session_log = base_stream.reset_session_log  # type: ignore[attr-defined]
        if hasattr(base_stream, "close_log"):
            self.close_log = base_stream.close_log  # type: ignore[attr-defined]

    def write(self, data: str) -> int:
        with self._lock:
            self._line_buf += data
            while "\n" in self._line_buf:
                line, self._line_buf = self._line_buf.split("\n", 1)
                for output in self._filter.feed_line(line + "\n"):
                    self._base.write(output + "\n")
        return len(data)

    def flush(self) -> None:
        with self._lock:
            if self._line_buf:
                for output in self._filter.feed_line(self._line_buf + "\n"):
                    self._base.write(output + "\n")
                self._line_buf = ""
            self._base.flush()

    def isatty(self) -> bool:
        return bool(getattr(self._base, "isatty", lambda: False)())
