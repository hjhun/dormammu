"""Unit tests for dormammu.daemon.goals_config."""
from __future__ import annotations

from pathlib import Path

import pytest

from dormammu.daemon.goals_config import GoalsConfig, parse_goals_config


class TestGoalsConfig:
    def test_to_dict(self, tmp_path: Path) -> None:
        cfg = GoalsConfig(path=tmp_path / "goals", interval_minutes=30)
        d = cfg.to_dict()
        assert d["path"] == str(tmp_path / "goals")
        assert d["interval_minutes"] == 30


class TestParseGoalsConfig:
    def test_none_returns_none(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "daemonize.json"
        assert parse_goals_config(None, config_path=cfg_path) is None

    def test_minimal_config(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "daemonize.json"
        result = parse_goals_config(
            {"path": "./goals"}, config_path=cfg_path
        )
        assert result is not None
        assert result.path == (tmp_path / "goals").resolve()
        assert result.interval_minutes == 60  # default

    def test_explicit_interval(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "daemonize.json"
        result = parse_goals_config(
            {"path": "./goals", "interval_minutes": 15}, config_path=cfg_path
        )
        assert result is not None
        assert result.interval_minutes == 15

    def test_absolute_path(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "daemonize.json"
        abs_goals = str(tmp_path / "mygoals")
        result = parse_goals_config(
            {"path": abs_goals, "interval_minutes": 5}, config_path=cfg_path
        )
        assert result is not None
        assert result.path == Path(abs_goals)

    def test_relative_path_resolved_against_config_dir(
        self, tmp_path: Path
    ) -> None:
        subdir = tmp_path / "conf"
        subdir.mkdir()
        cfg_path = subdir / "daemonize.json"
        result = parse_goals_config(
            {"path": "../goals"}, config_path=cfg_path
        )
        assert result is not None
        assert result.path == (tmp_path / "goals").resolve()

    def test_not_a_mapping_raises(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "daemonize.json"
        with pytest.raises(RuntimeError, match="goals must be a JSON object"):
            parse_goals_config("bad", config_path=cfg_path)

    def test_missing_path_raises(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "daemonize.json"
        with pytest.raises(RuntimeError, match="goals.path must be a non-empty string"):
            parse_goals_config({}, config_path=cfg_path)

    def test_empty_path_raises(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "daemonize.json"
        with pytest.raises(RuntimeError, match="goals.path must be a non-empty string"):
            parse_goals_config({"path": "  "}, config_path=cfg_path)

    def test_interval_below_minimum_raises(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "daemonize.json"
        with pytest.raises(RuntimeError, match="goals.interval_minutes must be >= 1"):
            parse_goals_config(
                {"path": "./goals", "interval_minutes": 0}, config_path=cfg_path
            )

    def test_interval_not_integer_raises(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "daemonize.json"
        with pytest.raises(RuntimeError, match="goals.interval_minutes must be an integer"):
            parse_goals_config(
                {"path": "./goals", "interval_minutes": "bad"}, config_path=cfg_path
            )

    def test_interval_one_is_valid(self, tmp_path: Path) -> None:
        cfg_path = tmp_path / "daemonize.json"
        result = parse_goals_config(
            {"path": "./goals", "interval_minutes": 1}, config_path=cfg_path
        )
        assert result is not None
        assert result.interval_minutes == 1


class TestDaemonConfigGoals:
    """Integration: goals field wires through load_daemon_config."""

    def test_goals_absent_gives_none(self, tmp_path: Path) -> None:
        from dormammu.config import AppConfig
        from dormammu.daemon.config import load_daemon_config

        cfg_path = tmp_path / "daemonize.json"
        cfg_path.write_text(
            '{"schema_version": 1, "prompt_path": "./p", "result_path": "./r"}',
            encoding="utf-8",
        )
        app_config = AppConfig.load(repo_root=tmp_path)
        daemon_cfg = load_daemon_config(cfg_path, app_config=app_config)
        assert daemon_cfg.goals is None

    def test_goals_present_parsed(self, tmp_path: Path) -> None:
        from dormammu.config import AppConfig
        from dormammu.daemon.config import load_daemon_config

        cfg_path = tmp_path / "daemonize.json"
        cfg_path.write_text(
            '{"schema_version": 1, "prompt_path": "./p", "result_path": "./r",'
            ' "goals": {"path": "./goals", "interval_minutes": 30}}',
            encoding="utf-8",
        )
        app_config = AppConfig.load(repo_root=tmp_path)
        daemon_cfg = load_daemon_config(cfg_path, app_config=app_config)
        assert daemon_cfg.goals is not None
        assert daemon_cfg.goals.interval_minutes == 30
        assert daemon_cfg.goals.path == (tmp_path / "goals").resolve()
