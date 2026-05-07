"""Tests for Windows compatibility and SubprocessProcessManager."""

import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

# Mock Windows platform for testing
if sys.platform != "win32":
    sys.modules["ctypes"] = Mock()
    sys.modules["ctypes.windll"] = Mock()


from agenttalk.process_manager import (
    ManagedProcess,
    SubprocessProcessManager,
    TmuxProcessManager,
    _detect_agent_kind,
    get_process_manager,
    is_process_alive,
    output_fingerprint,
)


class TestDetectAgentKind:
    def test_claude(self):
        assert _detect_agent_kind(command="claude-code", title="") == "claude"

    def test_codex(self):
        assert _detect_agent_kind(command="codex-cli", title="") == "codex"

    def test_gemini(self):
        assert _detect_agent_kind(command="gemini-agent", title="") == "gemini"

    def test_unknown(self):
        assert _detect_agent_kind(command="python script.py", title="") == "unknown"


class TestIsProcessAlive:
    def test_nonexistent_pid(self):
        # PID 99999 should not exist
        assert is_process_alive(99999) is False

    def test_current_process(self):
        # Current process should be alive
        import os
        assert is_process_alive(os.getpid()) is True


class TestOutputFingerprint:
    def test_consistency(self):
        text = "hello world"
        assert output_fingerprint(text) == output_fingerprint(text)

    def test_different_inputs(self):
        assert output_fingerprint("a") != output_fingerprint("b")


class TestSubprocessProcessManager:
    def test_registry_save_load(self, tmp_path: Path):
        registry = tmp_path / "registry.json"
        mgr = SubprocessProcessManager(registry_path=registry)

        # Initially empty
        assert mgr.list_processes() == []

        # Simulate saving a process
        data = {"test-agent": {"pid": 12345, "updated_at": 0}}
        registry.write_text(json.dumps(data))

        # Mock is_process_alive to return True
        with patch("agenttalk.process_manager.is_process_alive", return_value=True):
            processes = mgr.list_processes()
            assert len(processes) == 1
            assert processes[0].target == "test-agent"
            assert processes[0].pane_pid == 12345

    def test_log_path(self, tmp_path: Path):
        registry = tmp_path / "registry.json"
        mgr = SubprocessProcessManager(registry_path=registry)

        log = mgr._log_path("session:window.pane")
        assert "session_window_pane.log" in str(log)

    def test_capture_empty_log(self, tmp_path: Path):
        registry = tmp_path / "registry.json"
        mgr = SubprocessProcessManager(registry_path=registry)

        assert mgr.capture_output("nonexistent", lines=10) == ""


class TestGetProcessManager:
    def test_returns_manager(self):
        mgr = get_process_manager()
        assert mgr is not None
        # Should be TmuxProcessManager on Unix if tmux available,
        # or SubprocessProcessManager otherwise
        assert isinstance(mgr, (TmuxProcessManager, SubprocessProcessManager))


class TestTmuxProcessManager:
    def test_parse_panes_empty(self):
        mgr = TmuxProcessManager()
        assert mgr._parse_panes("") == []

    def test_parse_panes_valid(self):
        mgr = TmuxProcessManager()
        output = "dev:0.0|%0|python|/tmp|claude|1234\n"
        panes = mgr._parse_panes(output)
        assert len(panes) == 1
        assert panes[0].target == "dev:0.0"
        assert panes[0].pane_pid == 1234
        assert panes[0].kind == "claude"

    def test_parse_panes_invalid_pid(self):
        mgr = TmuxProcessManager()
        output = "dev:0.0|%0|python|/tmp|claude|invalid\n"
        panes = mgr._parse_panes(output)
        assert len(panes) == 1
        assert panes[0].pane_pid is None


class TestCrossPlatformCompat:
    """Ensure no Unix-only APIs are used on Windows path."""

    def test_no_hardcoded_unix_paths(self):
        """Config paths should use Path.home(), not /tmp or ~."""
        from agenttalk.config import default_config_path
        path = default_config_path()
        # Should work on any platform
        assert isinstance(path, Path)
        assert ".agenttalk" in str(path)

    def test_config_save_load_roundtrip(self, tmp_path: Path):
        from agenttalk.config import AgentBinding, AgentTalkConfig, save_config, load_config

        config_path = tmp_path / "test_config.json"
        config = AgentTalkConfig(
            hub_url="http://test:8787",
            token="test-token",
            agents=[
                AgentBinding(
                    short_id="test",
                    owner="tester",
                    kind="codex",
                    tmux_target="test:0.0",
                )
            ],
        )
        save_config(config, config_path)
        loaded = load_config(config_path)
        assert loaded.hub_url == config.hub_url
        assert loaded.token == config.token
        assert len(loaded.agents) == 1
        assert loaded.agents[0].short_id == "test"
