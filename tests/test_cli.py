from __future__ import annotations

from typer.testing import CliRunner

from agenttalk.config import load_config
from agenttalk import cli
from agenttalk.cli import app


def test_list_requires_token() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(app, ["list", "--config-path", "missing-config.json"])

        assert result.exit_code != 0
        assert "Token is required" in result.output


def test_setup_saves_config(tmp_path) -> None:
    runner = CliRunner()
    config_path = tmp_path / "config.json"

    result = runner.invoke(
        app,
        [
            "setup",
            "http://hub.local:8787",
            "--token",
            "test-token",
            "--config-path",
            str(config_path),
        ],
    )

    assert result.exit_code == 0
    config = load_config(config_path)
    assert config.hub_url == "http://hub.local:8787"
    assert config.token == "test-token"


def test_register_without_sync_saves_binding(tmp_path) -> None:
    runner = CliRunner()
    config_path = tmp_path / "config.json"
    runner.invoke(app, ["setup", "http://hub.local:8787", "--token", "test-token", "--config-path", str(config_path)])

    result = runner.invoke(
        app,
        [
            "register",
            "--short-id",
            "alice-codex-api",
            "--tmux-target",
            "dev:0.1",
            "--owner",
            "alice",
            "--kind",
            "codex",
            "--workspace",
            "/workspace/api",
            "--pane-id",
            "%1",
            "--no-sync",
            "--config-path",
            str(config_path),
        ],
    )

    assert result.exit_code == 0
    config = load_config(config_path)
    assert config.agents[0].short_id == "alice-codex-api"


def test_send_watch_calls_watcher_with_message_id_keyword(monkeypatch) -> None:
    runner = CliRunner()
    watched: dict[str, object] = {}

    class FakePostResponse:
        status_code = 200
        text = ""

        def json(self) -> dict[str, str]:
            return {
                "message_id": "msg-1",
                "target": "alice-codex-api",
                "status": "sent",
                "done_marker": "<<<AGENTTALK_DONE:msg-1>>>",
            }

    class FakeAgentLookupResponse:
        status_code = 200
        text = ""

        def json(self) -> dict[str, str]:
            return {
                "short_id": "alice-codex-api",
                "kind": "codex",
                "receive_mode": "auto_submit",
                "status": "idle",
            }

    def fake_hub_request(method, url, **_kwargs):
        if method == "GET":
            return FakeAgentLookupResponse()
        if method == "POST":
            return FakePostResponse()
        raise AssertionError(f"unexpected method: {method} {url}")

    def fake_watch_message(*, message_id: str, resolved_hub_url: str, resolved_token: str, timeout: int) -> None:
        watched.update(
            {
                "message_id": message_id,
                "resolved_hub_url": resolved_hub_url,
                "resolved_token": resolved_token,
                "timeout": timeout,
            }
        )

    monkeypatch.setattr(cli, "hub_request", fake_hub_request)
    monkeypatch.setattr(cli, "watch_message", fake_watch_message)

    result = runner.invoke(
        app,
        [
            "send",
            "--to",
            "alice-codex-api",
            "--message",
            "Please review.",
            "--hub-url",
            "http://hub.local:8787",
            "--token",
            "test-token",
            "--watch",
            "--timeout",
            "5",
        ],
    )

    assert result.exit_code == 0
    assert watched == {
        "message_id": "msg-1",
        "resolved_hub_url": "http://hub.local:8787",
        "resolved_token": "test-token",
        "timeout": 5,
    }


def test_send_surfaces_evidence_trail(monkeypatch) -> None:
    """Issue 6: send must surface message_id, target receive_mode, and explicit
    Verify-with hints so the caller does not rely on a verbal `I sent it` claim."""
    runner = CliRunner()

    class FakePostResponse:
        status_code = 200
        text = ""

        def json(self) -> dict[str, str]:
            return {
                "message_id": "msg-evidence",
                "target": "alice-codex-api",
                "status": "sent",
                "done_marker": "<<<AGENTTALK_DONE:msg-evidence>>>",
            }

    class FakeAgentLookupResponse:
        status_code = 200
        text = ""

        def json(self) -> dict[str, str]:
            return {
                "short_id": "alice-codex-api",
                "kind": "codex",
                "receive_mode": "paste_only",
                "status": "idle",
            }

    def fake_hub_request(method, url, **_kwargs):
        if method == "GET":
            return FakeAgentLookupResponse()
        if method == "POST":
            return FakePostResponse()
        raise AssertionError(f"unexpected method: {method} {url}")

    monkeypatch.setattr(cli, "hub_request", fake_hub_request)

    result = runner.invoke(
        app,
        [
            "send",
            "--to",
            "alice-codex-api",
            "--message",
            "Please review.",
            "--hub-url",
            "http://hub.local:8787",
            "--token",
            "test-token",
        ],
    )

    assert result.exit_code == 0
    assert "msg-evidence" in result.output
    assert "target receive_mode: paste_only" in result.output
    assert "paste_only" in result.output
    # Verification hints must reference the actual message_id and target.
    assert "agenttalk status msg-evidence" in result.output
    assert "agenttalk response msg-evidence" in result.output
    assert "agenttalk context alice-codex-api" in result.output


def test_send_reads_message_from_stdin(monkeypatch) -> None:
    runner = CliRunner()
    calls: list[dict] = []

    class FakePostResponse:
        status_code = 200
        text = ""

        def json(self) -> dict[str, str]:
            return {
                "message_id": "msg-stdin",
                "target": "alice-codex-api",
                "status": "sent",
                "done_marker": "<<<AGENTTALK_DONE:msg-stdin>>>",
            }

    class FakeAgentLookupResponse:
        status_code = 200
        text = ""

        def json(self) -> dict[str, str]:
            return {
                "short_id": "alice-codex-api",
                "kind": "codex",
                "receive_mode": "auto_submit",
                "status": "idle",
            }

    def fake_hub_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, "json": kwargs.get("json")})
        if method == "GET":
            return FakeAgentLookupResponse()
        if method == "POST":
            return FakePostResponse()
        raise AssertionError(f"unexpected method: {method} {url}")

    monkeypatch.setattr(cli, "hub_request", fake_hub_request)

    result = runner.invoke(
        app,
        [
            "send",
            "--to",
            "alice-codex-api",
            "--message",
            "-",
            "--hub-url",
            "http://hub.local:8787",
            "--token",
            "test-token",
        ],
        input="line 1\nline 2\n",
    )

    assert result.exit_code == 0
    post_call = next(call for call in calls if call["method"] == "POST")
    assert post_call["json"] == {
        "to": "alice-codex-api",
        "body": "line 1\nline 2",
        "sender": "cli",
    }
    assert "msg-stdin" in result.output
    assert "message preview: line 1 line 2" in result.output


def test_send_rejects_blank_message_before_hub_request(monkeypatch) -> None:
    runner = CliRunner()
    calls: list[dict] = []

    def fake_hub_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, "json": kwargs.get("json")})
        raise AssertionError("send should validate blank body before Hub request")

    monkeypatch.setattr(cli, "hub_request", fake_hub_request)

    result = runner.invoke(
        app,
        [
            "send",
            "--to",
            "alice-codex-api",
            "--message",
            "-",
            "--hub-url",
            "http://hub.local:8787",
            "--token",
            "test-token",
        ],
        input="   \n\t\n",
    )

    assert result.exit_code != 0
    assert "Message body cannot be empty" in result.output
    assert calls == []


def test_alert_posts_agent_warning_to_hub(monkeypatch) -> None:
    runner = CliRunner()
    calls: list[dict] = []

    class FakeAlertResponse:
        status_code = 200
        text = ""

        def json(self) -> dict:
            return {
                "alert": {
                    "short_id": "alice-codex-api",
                    "alert_type": "warning",
                    "message": "Need human review.",
                    "created_at": "2026-05-15T00:00:00Z",
                    "acknowledged": False,
                },
                "feishu_status": "sent",
                "feishu_error": "",
            }

    def fake_hub_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, "json": kwargs["json"]})
        return FakeAlertResponse()

    monkeypatch.setattr(cli, "hub_request", fake_hub_request)

    result = runner.invoke(
        app,
        [
            "alert",
            "--from",
            "alice-codex-api",
            "--type",
            "warning",
            "--message",
            "Need human review.",
            "--hub-url",
            "http://hub.local:8787",
            "--token",
            "test-token",
        ],
    )

    assert result.exit_code == 0
    assert calls == [
        {
            "method": "POST",
            "url": "http://hub.local:8787/api/alerts",
            "json": {
                "source": "alice-codex-api",
                "alert_type": "warning",
                "message": "Need human review.",
            },
        }
    ]
    assert "alert created" in result.output
    assert "feishu: sent" in result.output


def test_alert_reads_message_from_stdin(monkeypatch) -> None:
    runner = CliRunner()
    calls: list[dict] = []

    class FakeAlertResponse:
        status_code = 200
        text = ""

        def json(self) -> dict:
            return {
                "alert": {
                    "short_id": "alice-codex-api",
                    "alert_type": "warning",
                    "message": "line 1\nline 2",
                    "created_at": "2026-05-15T00:00:00Z",
                    "acknowledged": False,
                },
                "feishu_status": "sent",
                "feishu_error": "",
            }

    def fake_hub_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, "json": kwargs["json"]})
        return FakeAlertResponse()

    monkeypatch.setattr(cli, "hub_request", fake_hub_request)

    result = runner.invoke(
        app,
        [
            "alert",
            "--from",
            "alice-codex-api",
            "--type",
            "warning",
            "--message",
            "-",
            "--hub-url",
            "http://hub.local:8787",
            "--token",
            "test-token",
        ],
        input="line 1\nline 2\n",
    )

    assert result.exit_code == 0
    assert calls[0]["json"] == {
        "source": "alice-codex-api",
        "alert_type": "warning",
        "message": "line 1\nline 2",
    }


def test_register_warns_when_worker_kind_uses_paste_only(tmp_path) -> None:
    """Issue 5: worker-class kinds (claude/codex/gemini) MUST be auto_submit;
    register must surface a clear warning when paste_only is used."""
    runner = CliRunner()
    config_path = tmp_path / "config.json"
    runner.invoke(
        app,
        [
            "setup",
            "http://hub.local:8787",
            "--token",
            "test-token",
            "--config-path",
            str(config_path),
        ],
    )

    result = runner.invoke(
        app,
        [
            "register",
            "--short-id",
            "alice-codex-api",
            "--tmux-target",
            "dev:0.1",
            "--owner",
            "alice",
            "--kind",
            "codex",
            "--workspace",
            "/workspace/api",
            "--pane-id",
            "%1",
            "--receive-mode",
            "paste_only",
            "--no-sync",
            "--config-path",
            str(config_path),
        ],
    )

    assert result.exit_code == 0
    # CliRunner merges stderr into output for typer.echo(err=True) calls.
    combined = result.output
    assert "paste_only" in combined
    assert "worker class" in combined or "worker-class" in combined.lower() or "worker " in combined
    config = load_config(config_path)
    saved = next(b for b in config.agents if b.short_id == "alice-codex-api")
    # The warning is advisory; the binding is still saved with the requested
    # mode. The user must explicitly switch it.
    assert saved.receive_mode.value == "paste_only"


def test_register_auto_discovers_pane_id_when_visible(monkeypatch, tmp_path) -> None:
    """Issue 4: when --pane-id is omitted but the tmux target is visible,
    register must auto-discover and store the actual pane id."""
    from agenttalk.process_manager import ManagedProcess
    from agenttalk import cli as cli_module

    runner = CliRunner()
    config_path = tmp_path / "config.json"
    runner.invoke(
        app,
        [
            "setup",
            "http://hub.local:8787",
            "--token",
            "test-token",
            "--config-path",
            str(config_path),
        ],
    )

    fake_pane = ManagedProcess(
        target="dev:0.1",
        pane_id="%42",
        command="codex",
        current_path="/workspace/api",
        title="codex",
        kind="codex",
        pane_pid=None,
    )

    class FakeManager:
        def list_processes(self):
            return [fake_pane]

    monkeypatch.setattr(cli_module, "get_process_manager", lambda: FakeManager())

    result = runner.invoke(
        app,
        [
            "register",
            "--short-id",
            "alice-codex-api",
            "--tmux-target",
            "dev:0.1",
            "--owner",
            "alice",
            "--kind",
            "codex",
            "--workspace",
            "/workspace/api",
            "--no-sync",
            "--config-path",
            str(config_path),
        ],
    )

    assert result.exit_code == 0
    assert "Auto-discovered pane id" in result.output
    assert "%42" in result.output
    config = load_config(config_path)
    saved = next(b for b in config.agents if b.short_id == "alice-codex-api")
    assert saved.pane_id == "%42"


def test_register_warns_when_pane_not_visible(monkeypatch, tmp_path) -> None:
    """Issue 4: when --pane-id is omitted and the target is not currently
    visible, register must warn about drift risk and still save the binding."""
    from agenttalk import cli as cli_module

    runner = CliRunner()
    config_path = tmp_path / "config.json"
    runner.invoke(
        app,
        [
            "setup",
            "http://hub.local:8787",
            "--token",
            "test-token",
            "--config-path",
            str(config_path),
        ],
    )

    class FakeEmptyManager:
        def list_processes(self):
            return []

    monkeypatch.setattr(cli_module, "get_process_manager", lambda: FakeEmptyManager())

    result = runner.invoke(
        app,
        [
            "register",
            "--short-id",
            "alice-codex-api",
            "--tmux-target",
            "dev:0.1",
            "--kind",
            "codex",
            "--no-sync",
            "--config-path",
            str(config_path),
        ],
    )

    assert result.exit_code == 0
    combined = result.output
    assert "Registration drift" in combined or "not currently visible" in combined
    config = load_config(config_path)
    saved = next(b for b in config.agents if b.short_id == "alice-codex-api")
    assert saved.pane_id == ""
