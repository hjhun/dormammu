from __future__ import annotations

import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time
from typing import Callable, Sequence, TextIO

from dormammu.config import AppConfig, set_config_value
from dormammu.daemon.config import load_daemon_config
from dormammu.daemon.queue import is_prompt_candidate, prompt_sort_key


def _default_daemon_config_path(config: AppConfig) -> Path:
    return (config.home_dir / ".dormammu" / "daemonize.json").expanduser().resolve()


def _nested_get(payload: dict[str, object], dotted_key: str) -> object | None:
    current: object = payload
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


class InteractiveShellRunner:
    def __init__(
        self,
        *,
        repo_root: Path | None = None,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
        command_runner: Callable[[Sequence[str]], int] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.stdin = stdin or sys.stdin
        self.stdout = stdout or sys.stdout
        self.stderr = stderr or sys.stderr
        self.env = env or dict(os.environ)
        self.command_runner = command_runner or self._default_command_runner
        self._config = AppConfig.load(env=self.env, repo_root=repo_root, discover=repo_root is not None)

    def run(self) -> int:
        self._write_line("=== dormammu interactive shell ===")
        self._write_line(f"repo root: {self._config.repo_root}")
        self._write_line("type /help for commands")
        while True:
            self._write("dormammu> ")
            line = self.stdin.readline()
            if line == "":
                self._write_line("")
                self._write_line("interactive shell: EOF received, exiting")
                return 0
            raw = line.rstrip("\n")
            if not raw.strip():
                continue
            try:
                should_exit = self._handle_line(raw)
            except KeyboardInterrupt:
                self._write_line("interactive shell: interrupted")
                should_exit = False
            except Exception as exc:  # pragma: no cover - defensive shell guard
                self._write_line(f"interactive shell error: {exc}")
                should_exit = False
            if should_exit:
                return 0

    def _handle_line(self, raw: str) -> bool:
        if raw.startswith("//"):
            self._run_prompt(raw[1:])
            return False
        if raw.startswith("/"):
            return self._handle_command(raw)
        self._run_prompt(raw)
        return False

    def _handle_command(self, raw: str) -> bool:
        parts = shlex.split(raw)
        command = parts[0]
        args = parts[1:]
        if command in {"/exit", "/quit"}:
            self._write_line("interactive shell: exiting")
            return True
        if command == "/help":
            self._print_help()
            return False
        if command == "/clear":
            self._write_line("\n" * 3)
            return False
        if command == "/status":
            self._write_line(f"repo root: {self._config.repo_root}")
            self._write_line(f"config file: {self._config.config_file or '(project default unresolved)'}")
            self._write_line(f"active agent cli: {self._config.active_agent_cli or '(unset)'}")
            return False
        if command == "/show-config":
            self._run_command(["show-config", "--repo-root", str(self._config.repo_root)])
            self._reload_config()
            return False
        if command == "/sessions":
            self._run_command(["sessions", "--repo-root", str(self._config.repo_root)])
            return False
        if command == "/resume":
            self._run_command(["resume", "--repo-root", str(self._config.repo_root)])
            return False
        if command == "/run":
            if not args:
                self._write_line("usage: /run <prompt>")
                return False
            self._run_prompt(" ".join(args))
            return False
        if command == "/run-once":
            if not args:
                self._write_line("usage: /run-once <prompt>")
                return False
            self._run_command(
                ["run-once", "--repo-root", str(self._config.repo_root), "--prompt", " ".join(args)]
            )
            return False
        if command == "/config":
            self._handle_config_command(args)
            return False
        if command == "/daemon":
            self._handle_daemon_command(args)
            return False
        self._write_line(f"unknown command: {command}")
        return False

    def _handle_config_command(self, args: list[str]) -> None:
        if not args:
            payload = self._config.to_dict()
            self._write_line(json.dumps(payload, indent=2, ensure_ascii=True))
            return
        action = args[0]
        if action == "get":
            if len(args) != 2:
                self._write_line("usage: /config get <key>")
                return
            value = _nested_get(self._config.to_dict(), args[1])
            self._write_line(json.dumps(value, ensure_ascii=True))
            return
        if action not in {"set", "add", "remove", "unset"}:
            self._write_line("usage: /config [get|set|add|remove|unset] ...")
            return
        try:
            if action == "set":
                if len(args) < 3:
                    self._write_line("usage: /config set <key> <value>")
                    return
                path = set_config_value(self._config, args[1], value=" ".join(args[2:]))
            elif action == "add":
                if len(args) < 3:
                    self._write_line("usage: /config add <key> <value>")
                    return
                path = set_config_value(self._config, args[1], add=" ".join(args[2:]))
            elif action == "remove":
                if len(args) < 3:
                    self._write_line("usage: /config remove <key> <value>")
                    return
                path = set_config_value(self._config, args[1], remove=" ".join(args[2:]))
            else:
                if len(args) != 2:
                    self._write_line("usage: /config unset <key>")
                    return
                path = set_config_value(self._config, args[1], unset=True)
        except ValueError as exc:
            self._write_line(str(exc))
            return
        self._reload_config()
        self._write_line(f"config updated: {path}")

    def _handle_daemon_command(self, args: list[str]) -> None:
        if not args:
            self._write_line("usage: /daemon [start|stop|status|logs|enqueue|queue]")
            return
        action = args[0]
        if action == "start":
            self._daemon_start()
            return
        if action == "stop":
            self._daemon_stop()
            return
        if action == "status":
            self._daemon_status()
            return
        if action == "logs":
            self._daemon_logs()
            return
        if action == "enqueue":
            if len(args) < 2:
                self._write_line("usage: /daemon enqueue <prompt>")
                return
            self._daemon_enqueue(" ".join(args[1:]))
            return
        if action == "queue":
            self._daemon_queue()
            return
        self._write_line(f"unknown /daemon action: {action}")

    def _run_prompt(self, prompt: str) -> None:
        self._run_command(["run", "--repo-root", str(self._config.repo_root), "--prompt", prompt])

    def _run_command(self, argv: Sequence[str]) -> int:
        return self.command_runner(list(argv))

    def _reload_config(self) -> None:
        self._config = AppConfig.load(env=self.env, repo_root=self._config.repo_root, discover=False)

    def _load_daemon_config(self):
        path = _default_daemon_config_path(self._config)
        return load_daemon_config(path, app_config=self._config)

    def _daemon_start(self) -> None:
        try:
            daemon_config = self._load_daemon_config()
        except (RuntimeError, ValueError, OSError) as exc:
            self._write_line(str(exc))
            return
        pid_path = daemon_config.result_path.parent / "daemon.pid"
        if pid_path.exists():
            self._write_line(f"daemon appears to be running already: {pid_path}")
            return
        daemon_log = daemon_config.result_path.parent / "daemon.shell.log"
        daemon_log.parent.mkdir(parents=True, exist_ok=True)
        log_stream = daemon_log.open("a", encoding="utf-8")
        env = dict(self.env)
        python_path = os.pathsep.join(path for path in sys.path if path)
        if python_path:
            env["PYTHONPATH"] = python_path + (
                os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else ""
            )
        try:
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    "from dormammu.cli import main; raise SystemExit(main())",
                    "daemonize",
                    "--repo-root",
                    str(self._config.repo_root),
                    "--config",
                    str(daemon_config.config_path),
                ],
                stdout=log_stream,
                stderr=log_stream,
                stdin=subprocess.DEVNULL,
                env=env,
                start_new_session=True,
                close_fds=True,
            )
        finally:
            log_stream.close()
        self._write_line(f"daemon started: pid={proc.pid} log={daemon_log}")

    def _daemon_stop(self) -> None:
        try:
            daemon_config = self._load_daemon_config()
        except (RuntimeError, ValueError, OSError) as exc:
            self._write_line(str(exc))
            return
        pid_path = daemon_config.result_path.parent / "daemon.pid"
        if not pid_path.exists():
            self._write_line("daemon is not running")
            return
        try:
            pid = int(pid_path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError) as exc:
            self._write_line(f"failed to read daemon pid: {exc}")
            return
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as exc:
            self._write_line(f"failed to stop daemon pid {pid}: {exc}")
            return
        self._write_line(f"daemon stop requested: pid={pid}")

    def _daemon_status(self) -> None:
        try:
            daemon_config = self._load_daemon_config()
        except (RuntimeError, ValueError, OSError) as exc:
            self._write_line(str(exc))
            return
        base = daemon_config.result_path.parent
        pid_path = base / "daemon.pid"
        heartbeat_path = base / "daemon_heartbeat.json"
        self._write_line(f"daemon config: {daemon_config.config_path}")
        self._write_line(f"prompt path: {daemon_config.prompt_path}")
        self._write_line(f"result path: {daemon_config.result_path}")
        self._write_line(f"pid file: {pid_path} ({'present' if pid_path.exists() else 'missing'})")
        self._write_line(f"heartbeat: {heartbeat_path} ({'present' if heartbeat_path.exists() else 'missing'})")
        if heartbeat_path.exists():
            try:
                payload = json.loads(heartbeat_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                self._write_line(f"heartbeat read failed: {exc}")
            else:
                self._write_line(json.dumps(payload, indent=2, ensure_ascii=True))
        queued = sorted(
            (
                path
                for path in daemon_config.prompt_path.iterdir()
                if is_prompt_candidate(path, daemon_config.queue)
            ),
            key=lambda item: prompt_sort_key(item.name),
        ) if daemon_config.prompt_path.exists() else []
        self._write_line(f"queue depth: {len(queued)}")

    def _daemon_logs(self) -> None:
        try:
            daemon_config = self._load_daemon_config()
        except (RuntimeError, ValueError, OSError) as exc:
            self._write_line(str(exc))
            return
        base = daemon_config.result_path.parent
        progress_dir = base / "progress"
        candidates: list[Path] = []
        if progress_dir.exists():
            candidates.extend(sorted(progress_dir.glob("*.log"), key=lambda path: path.stat().st_mtime))
        daemon_log = base / "daemon.shell.log"
        if daemon_log.exists():
            candidates.append(daemon_log)
        if not candidates:
            self._write_line("no daemon logs found")
            return
        target = candidates[-1]
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        tail = lines[-40:] if len(lines) > 40 else lines
        self._write_line(f"daemon log: {target}")
        for line in tail:
            self._write_line(line)

    def _daemon_enqueue(self, prompt: str) -> None:
        try:
            daemon_config = self._load_daemon_config()
        except (RuntimeError, ValueError, OSError) as exc:
            self._write_line(str(exc))
            return
        daemon_config.prompt_path.mkdir(parents=True, exist_ok=True)
        stem = f"shell-{os.getpid()}-{len(prompt)}-{int(time.time())}"
        prompt_path = daemon_config.prompt_path / f"{stem}.md"
        prompt_path.write_text(prompt.rstrip() + "\n", encoding="utf-8")
        self._write_line(f"daemon prompt queued: {prompt_path}")

    def _daemon_queue(self) -> None:
        try:
            daemon_config = self._load_daemon_config()
        except (RuntimeError, ValueError, OSError) as exc:
            self._write_line(str(exc))
            return
        if not daemon_config.prompt_path.exists():
            self._write_line("daemon queue is empty")
            return
        queued = sorted(
            (
                path
                for path in daemon_config.prompt_path.iterdir()
                if is_prompt_candidate(path, daemon_config.queue)
            ),
            key=lambda item: prompt_sort_key(item.name),
        )
        if not queued:
            self._write_line("daemon queue is empty")
            return
        for path in queued:
            self._write_line(path.name)

    def _print_help(self) -> None:
        self._write_line("free text submits a supervised /run prompt")
        self._write_line("/run <prompt>")
        self._write_line("/run-once <prompt>")
        self._write_line("/resume")
        self._write_line("/sessions")
        self._write_line("/show-config")
        self._write_line("/config [get|set|add|remove|unset] ...")
        self._write_line("/daemon [start|stop|status|logs|enqueue|queue]")
        self._write_line("/status")
        self._write_line("/clear")
        self._write_line("/exit")

    def _default_command_runner(self, argv: Sequence[str]) -> int:
        from dormammu.cli import main

        return main(list(argv))

    def _write(self, text: str) -> None:
        self.stdout.write(text)
        self.stdout.flush()

    def _write_line(self, text: str) -> None:
        self.stdout.write(text + "\n")
        self.stdout.flush()
