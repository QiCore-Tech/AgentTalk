from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from agenttalk.config import AgentBinding, default_config_path, load_config, save_config, upsert_binding
from agenttalk.dlq import load_dead_letters, mark_dead_letter
from agenttalk.http_client import HubRequestError, request as hub_request
from agenttalk.hub.client import HubClient
from agenttalk.hub.app import create_app
from agenttalk.hub.models import MessageStatus, ReceiveMode
from agenttalk.hub.settings import HubSettings, default_database_path
from agenttalk.relay import AgentTalkRelay
from agenttalk.process_manager import get_process_manager


app = typer.Typer(help="AgentTalk CLI.")
hub_app = typer.Typer(help="Run and manage the AgentTalk Hub.")
daemon_app = typer.Typer(help="Run the local AgentTalk relay.")
config_app = typer.Typer(help="Manage Hub configuration.")
dlq_app = typer.Typer(help="Inspect and retry local dead-lettered deliveries.")
app.add_typer(hub_app, name="hub")
app.add_typer(daemon_app, name="daemon")
app.add_typer(config_app, name="config")
app.add_typer(dlq_app, name="dlq")


def default_daemon_pid_path() -> Path:
    return Path.home() / ".agenttalk" / "daemon.pid"


def default_daemon_log_path() -> Path:
    return Path.home() / ".agenttalk" / "relay.log"


def default_daemon_stop_path() -> Path:
    return Path.home() / ".agenttalk" / "daemon.stop"


def _read_pid(path: Path | None = None) -> int | None:
    resolved = path or default_daemon_pid_path()
    try:
        return int(resolved.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _find_daemon_pids() -> list[int]:
    patterns = [
        "agenttalk daemon start",
        "agenttalk daemon supervise",
        "uv run --no-sync agenttalk daemon start",
    ]
    current = os.getpid()
    found: set[int] = set()
    for pattern in patterns:
        proc = subprocess.run(["pgrep", "-f", pattern], text=True, capture_output=True, check=False)
        for raw in proc.stdout.splitlines():
            try:
                pid = int(raw.strip())
            except ValueError:
                continue
            if pid != current:
                found.add(pid)
    return sorted(pid for pid in found if _pid_alive(pid))


def _agenttalk_executable() -> str:
    return shutil.which("agenttalk") or sys.argv[0]


def _stop_daemon_process(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGTERM)
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if not _pid_alive(pid):
            return
        time.sleep(0.2)
    try:
        os.killpg(pid, signal.SIGKILL)
    except OSError:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def _start_daemon_supervisor(*, config_path: Path | None, interval: float) -> int:
    pid_path = default_daemon_pid_path()
    existing_pid = _read_pid(pid_path)
    if _pid_alive(existing_pid):
        return int(existing_pid)
    unmanaged = [pid for pid in _find_daemon_pids() if pid != existing_pid]
    if unmanaged:
        raise RuntimeError(
            "existing unmanaged AgentTalk daemon process found: "
            + ", ".join(str(pid) for pid in unmanaged)
            + ". Run `agenttalk daemon restart` to replace it."
        )
    default_daemon_stop_path().unlink(missing_ok=True)
    log_path = default_daemon_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        _agenttalk_executable(),
        "daemon",
        "supervise",
        "--interval",
        str(interval),
    ]
    if config_path is not None:
        cmd.extend(["--config-path", str(config_path)])
    with log_path.open("ab") as log_file:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(f"{proc.pid}\n", encoding="utf-8")
    return proc.pid


def resolve_token(token: str | None) -> str:
    resolved = token or os.environ.get("AGENTTALK_TOKEN")
    if not resolved:
        raise typer.BadParameter("Token is required via --token or AGENTTALK_TOKEN")
    return resolved


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _hub_request_or_exit(method: str, url: str, **kwargs) -> object:
    try:
        return hub_request(method, url, **kwargs)
    except HubRequestError as exc:
        typer.echo(_format_hub_request_error(exc), err=True)
        raise typer.Exit(1) from exc


def _format_hub_request_error(exc: HubRequestError) -> str:
    return (
        str(exc)
        + "\n"
        + "This is usually a transient Hub/TLS/proxy failure. "
        + "Retry the command, or use `agenttalk doctor` and the message "
        + "`status/response/context` commands to inspect existing work."
    )


@hub_app.command("serve")
def serve_hub(
    host: Annotated[str, typer.Option(help="Host to bind.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to bind.")] = 8787,
    token: Annotated[str | None, typer.Option(help="Shared LAN bearer token.")] = None,
    database: Annotated[Path, typer.Option(help="SQLite database path.")] = default_database_path(),
    heartbeat_ttl: Annotated[int, typer.Option(help="Heartbeat TTL in seconds.")] = 30,
    web_dist: Annotated[Path | None, typer.Option(help="Built Web UI dist path.")] = None,
    public_base_url: Annotated[str, typer.Option(help="Public Web base URL used in integrations.")] = "",
    feishu_enable: Annotated[bool, typer.Option(help="Enable Feishu long-connection bot.")] = False,
    feishu_app_id: Annotated[str, typer.Option(help="Feishu app id.")] = "",
    feishu_app_secret: Annotated[str, typer.Option(help="Feishu app secret.")] = "",
) -> None:
    env_feishu_enable = os.environ.get("FEISHU_ENABLE", "").lower() in {"1", "true", "yes", "on"}
    resolved_feishu_enable = feishu_enable or env_feishu_enable
    resolved_feishu_app_id = feishu_app_id or os.environ.get("FEISHU_APP_ID", "")
    resolved_feishu_app_secret = feishu_app_secret or os.environ.get("FEISHU_APP_SECRET", "")
    if resolved_feishu_enable and (not resolved_feishu_app_id or not resolved_feishu_app_secret):
        raise typer.BadParameter("--feishu-enable requires --feishu-app-id/--feishu-app-secret or FEISHU_APP_ID/FEISHU_APP_SECRET")
    settings = HubSettings(
        database_path=database,
        token=resolve_token(token),
        heartbeat_ttl_seconds=heartbeat_ttl,
        web_dist_path=web_dist,
        public_base_url=public_base_url or os.environ.get("AGENTTALK_PUBLIC_BASE_URL", ""),
        feishu_enable=resolved_feishu_enable,
        feishu_app_id=resolved_feishu_app_id,
        feishu_app_secret=resolved_feishu_app_secret,
        feishu_alert_chat_id=os.environ.get("FEISHU_ALERT_CHAT_ID", ""),
    )
    uvicorn.run(create_app(settings), host=host, port=port, loop="asyncio")


@app.command("list")
def list_agents(
    hub_url: Annotated[str, typer.Option(help="Hub base URL.")] = "http://127.0.0.1:8787",
    token: Annotated[str | None, typer.Option(help="Shared LAN bearer token.")] = None,
    owner: Annotated[str | None, typer.Option(help="Filter by owner.")] = None,
    machine_id: Annotated[str | None, typer.Option(help="Filter by machine id.")] = None,
    mine: Annotated[bool, typer.Option(help="List agents for the local machine from config.")] = False,
    config_path: Annotated[Path | None, typer.Option(help="AgentTalk config path.")] = None,
) -> None:
    config = load_config(config_path)
    resolved_token = token or config.token or os.environ.get("AGENTTALK_TOKEN")
    if not resolved_token:
        raise typer.BadParameter("Token is required via --token, config, or AGENTTALK_TOKEN")
    resolved_hub_url = hub_url if hub_url != "http://127.0.0.1:8787" else config.hub_url
    if mine:
        machine_id = config.machine_id
    params = {key: value for key, value in {"owner": owner, "machine_id": machine_id}.items() if value}
    response = _hub_request_or_exit(
        "GET",
        f"{resolved_hub_url.rstrip('/')}/api/agents",
        headers=auth_headers(resolved_token),
        params=params,
        timeout=10,
    )
    if response.status_code >= 400:
        typer.echo(response.text, err=True)
        raise typer.Exit(1)
    agents = response.json()["agents"]
    if not agents:
        typer.echo("No agents registered.")
        return
    typer.echo(f"{'short id':24} {'kind':10} {'owner':12} {'status':10} workspace")
    for agent in agents:
        typer.echo(
            f"{agent['short_id'][:24]:24} "
            f"{agent['kind'][:10]:10} "
            f"{agent['owner'][:12]:12} "
            f"{agent['status'][:10]:10} "
            f"{agent['workspace']}"
        )


@app.command("setup")
def setup(
    hub_url: Annotated[str, typer.Argument(help="Hub base URL.")],
    token: Annotated[str | None, typer.Option(help="Shared LAN bearer token.")] = None,
    config_path: Annotated[Path | None, typer.Option(help="AgentTalk config path.")] = None,
) -> None:
    config = load_config(config_path)
    resolved_token = resolve_token(token)
    config = config.model_copy(update={"hub_url": hub_url.rstrip("/"), "token": resolved_token})
    save_config(config, config_path)
    typer.echo(f"Saved AgentTalk config for Hub: {config.hub_url}")


@app.command("discover")
def discover() -> None:
    manager = get_process_manager()
    panes = manager.list_processes()
    if not panes:
        typer.echo("No managed processes found.")
        return
    typer.echo(f"{'#':3} {'kind':10} {'target':14} {'pane':8} workspace")
    for index, pane in enumerate(panes, start=1):
        typer.echo(f"{index:<3} {pane.kind[:10]:10} {pane.target[:14]:14} {pane.pane_id[:8]:8} {pane.current_path}")


WORKER_AGENT_KINDS = frozenset({"claude", "codex", "gemini", "opencode"})


def _discover_pane_id(tmux_target: str) -> tuple[str, str | None]:
    """Look up the actual pane_id and kind for a tmux target.

    Returns ``(pane_id, kind)``. ``pane_id`` is the empty string when the
    target is not currently visible to the process manager (the binding will
    still be saved, but registration drift becomes possible). ``kind`` may be
    None when discovery fails or returns no kind hint.
    """
    try:
        manager = get_process_manager()
        for pane in manager.list_processes():
            if pane.target == tmux_target:
                return pane.pane_id, pane.kind
    except Exception:
        return "", None
    return "", None


@app.command("register")
def register(
    short_id: Annotated[str, typer.Option(help="Globally unique agent short ID.")],
    tmux_target: Annotated[str, typer.Option(help="tmux target, for example dev:0.1.")],
    owner: Annotated[str | None, typer.Option(help="Agent owner. Defaults to config user.")] = None,
    kind: Annotated[str, typer.Option(help="Agent kind.")] = "unknown",
    workspace: Annotated[str, typer.Option(help="Agent workspace.")] = "",
    pane_id: Annotated[str, typer.Option(help="tmux pane id if known.")] = "",
    receive_mode: Annotated[ReceiveMode, typer.Option(help="Receive mode.")] = ReceiveMode.AUTO_SUBMIT,
    config_path: Annotated[Path | None, typer.Option(help="AgentTalk config path.")] = None,
    sync: Annotated[bool, typer.Option(help="Immediately upsert this binding to Hub.")] = True,
) -> None:
    config = load_config(config_path)
    discovered_pane_id = ""
    discovered_kind: str | None = None
    if not pane_id:
        # Issue 4: when pane_id is omitted, look up the live pane for the given
        # tmux target so the binding is anchored to a concrete pane and not
        # just a tmux address that may shift between window restarts.
        discovered_pane_id, discovered_kind = _discover_pane_id(tmux_target)
        if discovered_pane_id:
            typer.echo(
                f"Auto-discovered pane id for {tmux_target}: {discovered_pane_id}"
            )
        else:
            typer.echo(
                f"warning: pane_id not provided and tmux target {tmux_target} "
                "is not currently visible. Registration drift is possible — "
                "either pass --pane-id explicitly or re-run register once the "
                "pane is alive.",
                err=True,
            )
    effective_pane_id = pane_id or discovered_pane_id
    binding = AgentBinding(
        short_id=short_id,
        owner=owner or config.user_name,
        kind=kind,
        workspace=workspace,
        tmux_target=tmux_target,
        pane_id=effective_pane_id,
        receive_mode=receive_mode,
    )
    # Issue 5: worker-class agents (claude / codex / gemini / opencode) drive
    # the inter-agent message bus. They MUST be auto_submit; paste_only leaves
    # the message sitting in the prompt input and the agent never sees it.
    if kind in WORKER_AGENT_KINDS and receive_mode == ReceiveMode.PASTE_ONLY:
        typer.echo(
            f"warning: agent kind '{kind}' is a worker class and was registered "
            f"with receive_mode=paste_only. paste_only leaves the message in "
            f"the input box without pressing Enter — the agent will not see it "
            f"until a human resubmits. Recommend `--receive-mode auto_submit`.",
            err=True,
        )
    config = upsert_binding(config, binding)
    save_config(config, config_path)
    if sync and config.token:
        relay = AgentTalkRelay(
            config,
            hub_client=HubClient(config.hub_url, config.token),
            tmux_client=get_process_manager(),
        )
        try:
            relay.sync_once()
        except HubRequestError as exc:
            typer.echo(_format_hub_request_error(exc), err=True)
            typer.echo("Saved local binding, but Hub sync failed. Retry with `agenttalk daemon start --once`.", err=True)
    typer.echo(f"Registered local binding: {short_id}")
    if effective_pane_id:
        typer.echo(f"  pane_id: {effective_pane_id}")
    typer.echo(f"  tmux_target: {tmux_target}")
    typer.echo(f"  kind: {kind}")
    typer.echo(f"  receive_mode: {receive_mode.value}")


@app.command("unregister")
def unregister(
    short_id: Annotated[str, typer.Option(help="Agent short ID to remove.")],
    hub_url: Annotated[str, typer.Option(help="Hub base URL.")] = "http://127.0.0.1:8787",
    token: Annotated[str | None, typer.Option(help="Shared LAN bearer token.")] = None,
    config_path: Annotated[Path | None, typer.Option(help="AgentTalk config path.")] = None,
) -> None:
    config = load_config(config_path)
    resolved_token = token or config.token or os.environ.get("AGENTTALK_TOKEN")
    if not resolved_token:
        raise typer.BadParameter("Token is required via --token, config, or AGENTTALK_TOKEN")
    resolved_hub_url = hub_url if hub_url != "http://127.0.0.1:8787" else config.hub_url
    
    # Remove from Hub
    response = _hub_request_or_exit(
        "DELETE",
        f"{resolved_hub_url.rstrip('/')}/api/agents/{short_id}",
        headers=auth_headers(resolved_token),
        timeout=10,
    )
    if response.status_code == 404:
        typer.echo(f"Agent not found on Hub: {short_id}")
    elif response.status_code >= 400:
        typer.echo(response.text, err=True)
        raise typer.Exit(1)
    else:
        typer.echo(f"Removed from Hub: {short_id}")
    
    # Remove from local config
    new_agents = [a for a in config.agents if a.short_id != short_id]
    if len(new_agents) != len(config.agents):
        config = config.model_copy(update={"agents": new_agents})
        save_config(config, config_path)
        typer.echo(f"Removed local binding: {short_id}")
    else:
        typer.echo(f"Local binding not found: {short_id}")


@app.command("rename")
def rename(
    old_id: str,
    new_id: str,
    config_path: Annotated[Path | None, typer.Option(help="AgentTalk config path.")] = None,
) -> None:
    config = load_config(config_path)
    for binding in config.agents:
        if binding.short_id == old_id:
            updated = binding.model_copy(update={"short_id": new_id})
            save_config(upsert_binding(config, updated), config_path)
            typer.echo(f"Renamed {old_id} to {new_id}")
            return
    typer.echo(f"Local binding not found: {old_id}", err=True)
    raise typer.Exit(1)


@app.command("mode")
def mode(
    short_id: str,
    receive_mode: ReceiveMode,
    config_path: Annotated[Path | None, typer.Option(help="AgentTalk config path.")] = None,
) -> None:
    config = load_config(config_path)
    for binding in config.agents:
        if binding.short_id == short_id:
            updated = binding.model_copy(update={"receive_mode": receive_mode})
            save_config(upsert_binding(config, updated), config_path)
            typer.echo(f"Updated {short_id} receive mode to {receive_mode.value}")
            return
    typer.echo(f"Local binding not found: {short_id}", err=True)
    raise typer.Exit(1)


@app.command("send")
def send_message(
    to: Annotated[str, typer.Option(help="Target agent short ID.")],
    message: Annotated[str, typer.Option(help="Message body.")],
    sender: Annotated[str, typer.Option(help="Sender label or agent short ID.")] = "cli",
    hub_url: Annotated[str, typer.Option(help="Hub base URL.")] = "http://127.0.0.1:8787",
    token: Annotated[str | None, typer.Option(help="Shared LAN bearer token.")] = None,
    config_path: Annotated[Path | None, typer.Option(help="AgentTalk config path.")] = None,
    watch: Annotated[bool, typer.Option(help="Watch status and response until completion.")] = False,
    timeout: Annotated[int, typer.Option(help="Watch timeout seconds.")] = 120,
) -> None:
    config = load_config(config_path)
    resolved_token = token or config.token or os.environ.get("AGENTTALK_TOKEN")
    if not resolved_token:
        raise typer.BadParameter("Token is required via --token, config, or AGENTTALK_TOKEN")
    resolved_hub_url = hub_url if hub_url != "http://127.0.0.1:8787" else config.hub_url
    # Issue 6: look up the target's receive_mode BEFORE creating the message so
    # the CLI surface tells the caller whether to expect auto_submit or
    # paste_only behaviour. This is best-effort; if the lookup fails we still
    # send the message but skip the receive-mode hint.
    target_receive_mode: str | None = None
    try:
        target_lookup = hub_request(
            "GET",
            f"{resolved_hub_url.rstrip('/')}/api/agents/{to}",
            headers=auth_headers(resolved_token),
            timeout=10,
        )
        if target_lookup.status_code == 200:
            target_receive_mode = target_lookup.json().get("receive_mode")
    except Exception:
        target_receive_mode = None

    response = _hub_request_or_exit(
        "POST",
        f"{resolved_hub_url.rstrip('/')}/api/messages",
        headers=auth_headers(resolved_token),
        json={"to": to, "body": message, "sender": sender},
        timeout=10,
    )
    if response.status_code >= 400:
        typer.echo(response.text, err=True)
        raise typer.Exit(1)
    payload = response.json()
    typer.echo(f"message: {payload['message_id']}")
    typer.echo(f"to: {payload['target']}")
    typer.echo(f"status: {payload['status']}")
    typer.echo(f"done marker: {payload['done_marker']}")
    if target_receive_mode:
        typer.echo(f"target receive_mode: {target_receive_mode}")
        if target_receive_mode == ReceiveMode.PASTE_ONLY.value:
            typer.echo(
                "  note: paste_only — text is pasted into the input box but "
                "Enter is NOT pressed. The agent has not seen the message "
                "yet; verify out-of-band before treating this as delivered."
            )
    typer.echo("Verify with:")
    typer.echo(f"  agenttalk status {payload['message_id']}")
    typer.echo(f"  agenttalk response {payload['message_id']}")
    typer.echo(f"  agenttalk context {payload['target']}")
    if watch:
        watch_message(
            message_id=payload["message_id"],
            resolved_hub_url=resolved_hub_url,
            resolved_token=resolved_token,
            timeout=timeout,
        )


@app.command("status")
def message_status(
    message_id: str,
    hub_url: Annotated[str, typer.Option(help="Hub base URL.")] = "http://127.0.0.1:8787",
    token: Annotated[str | None, typer.Option(help="Shared LAN bearer token.")] = None,
    config_path: Annotated[Path | None, typer.Option(help="AgentTalk config path.")] = None,
) -> None:
    config = load_config(config_path)
    resolved_token = token or config.token or os.environ.get("AGENTTALK_TOKEN")
    if not resolved_token:
        raise typer.BadParameter("Token is required via --token, config, or AGENTTALK_TOKEN")
    resolved_hub_url = hub_url if hub_url != "http://127.0.0.1:8787" else config.hub_url
    response = _hub_request_or_exit(
        "GET",
        f"{resolved_hub_url.rstrip('/')}/api/messages/{message_id}",
        headers=auth_headers(resolved_token),
        timeout=10,
    )
    if response.status_code >= 400:
        typer.echo(response.text, err=True)
        raise typer.Exit(1)
    payload = response.json()
    typer.echo(f"message: {payload['message_id']}")
    typer.echo(f"to: {payload['target']}")
    typer.echo(f"status: {payload['status']}")
    if payload.get("error"):
        typer.echo(f"error: {payload['error']}")


@app.command("response")
def message_response(
    message_id: str,
    hub_url: Annotated[str, typer.Option(help="Hub base URL.")] = "http://127.0.0.1:8787",
    token: Annotated[str | None, typer.Option(help="Shared LAN bearer token.")] = None,
    config_path: Annotated[Path | None, typer.Option(help="AgentTalk config path.")] = None,
) -> None:
    config = load_config(config_path)
    resolved_token = token or config.token or os.environ.get("AGENTTALK_TOKEN")
    if not resolved_token:
        raise typer.BadParameter("Token is required via --token, config, or AGENTTALK_TOKEN")
    resolved_hub_url = hub_url if hub_url != "http://127.0.0.1:8787" else config.hub_url
    response = _hub_request_or_exit(
        "GET",
        f"{resolved_hub_url.rstrip('/')}/api/messages/{message_id}/response",
        headers=auth_headers(resolved_token),
        timeout=10,
    )
    if response.status_code >= 400:
        typer.echo(response.text, err=True)
        raise typer.Exit(1)
    typer.echo(response.json()["response_text"])


@app.command("context")
def agent_context(
    agent_id: str,
    lines: Annotated[int, typer.Option(help="Requested recent line count.")] = 120,
    hub_url: Annotated[str, typer.Option(help="Hub base URL.")] = "http://127.0.0.1:8787",
    token: Annotated[str | None, typer.Option(help="Shared LAN bearer token.")] = None,
    config_path: Annotated[Path | None, typer.Option(help="AgentTalk config path.")] = None,
) -> None:
    config = load_config(config_path)
    resolved_token = token or config.token or os.environ.get("AGENTTALK_TOKEN")
    if not resolved_token:
        raise typer.BadParameter("Token is required via --token, config, or AGENTTALK_TOKEN")
    resolved_hub_url = hub_url if hub_url != "http://127.0.0.1:8787" else config.hub_url
    response = _hub_request_or_exit(
        "GET",
        f"{resolved_hub_url.rstrip('/')}/api/agents/{agent_id}/context",
        headers=auth_headers(resolved_token),
        timeout=10,
    )
    if response.status_code >= 400:
        typer.echo(response.text, err=True)
        raise typer.Exit(1)
    context = response.json()["context"]
    if lines > 0:
        context = "\n".join(context.splitlines()[-lines:])
    typer.echo(context)


def watch_message(*, message_id: str, resolved_hub_url: str, resolved_token: str, timeout: int) -> None:
    deadline = time.monotonic() + timeout
    last_status = ""
    last_response = ""
    while time.monotonic() < deadline:
        try:
            message_payload = hub_request(
                "GET",
                f"{resolved_hub_url.rstrip('/')}/api/messages/{message_id}",
                headers=auth_headers(resolved_token),
                timeout=10,
            )
            message_payload.raise_for_status()
        except HubRequestError as exc:
            typer.echo(f"[hub connection retry failed] {exc}")
            time.sleep(1)
            continue
        message = message_payload.json()
        if message["status"] != last_status:
            typer.echo(f"[{message['status']}]")
            last_status = message["status"]
        try:
            response_payload = hub_request(
                "GET",
                f"{resolved_hub_url.rstrip('/')}/api/messages/{message_id}/response",
                headers=auth_headers(resolved_token),
                timeout=10,
            )
        except HubRequestError:
            time.sleep(1)
            continue
        if response_payload.status_code == 200:
            response_text = response_payload.json()["response_text"]
            if response_text != last_response:
                delta = response_text[len(last_response) :] if response_text.startswith(last_response) else response_text
                if delta.strip():
                    typer.echo(delta.rstrip())
                last_response = response_text
        if message["status"] in {"completed", "failed", "timeout"}:
            return
        time.sleep(1)
    typer.echo("[timeout]")
    typer.echo("Trace later with:")
    typer.echo(f"  agenttalk status {message_id}")
    typer.echo(f"  agenttalk response {message_id}")


@dlq_app.command("list")
def dlq_list(
    all_records: Annotated[bool, typer.Option("--all", help="Show resolved records too.")] = False,
    path: Annotated[Path | None, typer.Option(help="Dead-letter JSON path.")] = None,
) -> None:
    records = load_dead_letters(path)
    if not all_records:
        records = [record for record in records if record.get("status") == "open"]
    if not records:
        typer.echo("No dead-lettered messages.")
        return
    typer.echo(f"{'message id':28} {'status':10} {'reason':20} target")
    for record in records:
        typer.echo(
            f"{str(record.get('message_id', ''))[:28]:28} "
            f"{str(record.get('status', ''))[:10]:10} "
            f"{str(record.get('reason', ''))[:20]:20} "
            f"{record.get('target', '')}"
        )


@dlq_app.command("retry")
def dlq_retry(
    message_id: str,
    hub_url: Annotated[str, typer.Option(help="Hub base URL.")] = "http://127.0.0.1:8787",
    token: Annotated[str | None, typer.Option(help="Shared LAN bearer token.")] = None,
    config_path: Annotated[Path | None, typer.Option(help="AgentTalk config path.")] = None,
    path: Annotated[Path | None, typer.Option(help="Dead-letter JSON path.")] = None,
) -> None:
    config = load_config(config_path)
    resolved_token = token or config.token or os.environ.get("AGENTTALK_TOKEN")
    if not resolved_token:
        raise typer.BadParameter("Token is required via --token, config, or AGENTTALK_TOKEN")
    resolved_hub_url = hub_url if hub_url != "http://127.0.0.1:8787" else config.hub_url
    response = _hub_request_or_exit(
        "POST",
        f"{resolved_hub_url.rstrip('/')}/api/messages/{message_id}/status",
        headers=auth_headers(resolved_token),
        json={"status": MessageStatus.SENT.value, "error": ""},
        timeout=10,
    )
    if response.status_code >= 400:
        typer.echo(response.text, err=True)
        raise typer.Exit(1)
    mark_dead_letter(message_id, status="retried", note="requeued via agenttalk dlq retry", path=path)
    typer.echo(f"Requeued message: {message_id}")


@dlq_app.command("fail")
def dlq_fail(
    message_id: str,
    reason: Annotated[str, typer.Option(help="Failure note.")] = "manually failed from DLQ",
    hub_url: Annotated[str, typer.Option(help="Hub base URL.")] = "http://127.0.0.1:8787",
    token: Annotated[str | None, typer.Option(help="Shared LAN bearer token.")] = None,
    config_path: Annotated[Path | None, typer.Option(help="AgentTalk config path.")] = None,
    path: Annotated[Path | None, typer.Option(help="Dead-letter JSON path.")] = None,
) -> None:
    config = load_config(config_path)
    resolved_token = token or config.token or os.environ.get("AGENTTALK_TOKEN")
    if not resolved_token:
        raise typer.BadParameter("Token is required via --token, config, or AGENTTALK_TOKEN")
    resolved_hub_url = hub_url if hub_url != "http://127.0.0.1:8787" else config.hub_url
    response = _hub_request_or_exit(
        "POST",
        f"{resolved_hub_url.rstrip('/')}/api/messages/{message_id}/status",
        headers=auth_headers(resolved_token),
        json={"status": MessageStatus.FAILED.value, "error": reason},
        timeout=10,
    )
    if response.status_code >= 400:
        typer.echo(response.text, err=True)
        raise typer.Exit(1)
    mark_dead_letter(message_id, status="failed", note=reason, path=path)
    typer.echo(f"Marked failed: {message_id}")


@app.command("auto-resume")
def config_auto_resume(
    short_id: str,
    enabled: Annotated[bool | None, typer.Option(help="Enable or disable auto resume.")] = None,
    message: Annotated[str | None, typer.Option(help="Resume message to send.")] = None,
    hub_url: Annotated[str, typer.Option(help="Hub base URL.")] = "http://127.0.0.1:8787",
    token: Annotated[str | None, typer.Option(help="Shared LAN bearer token.")] = None,
    config_path: Annotated[Path | None, typer.Option(help="AgentTalk config path.")] = None,
) -> None:
    config = load_config(config_path)
    resolved_token = token or config.token or os.environ.get("AGENTTALK_TOKEN")
    if not resolved_token:
        raise typer.BadParameter("Token is required via --token, config, or AGENTTALK_TOKEN")
    resolved_hub_url = hub_url if hub_url != "http://127.0.0.1:8787" else config.hub_url
    
    # Get current config for this agent
    response = _hub_request_or_exit(
        "GET",
        f"{resolved_hub_url.rstrip('/')}/api/agents/{short_id}/auto_resume",
        headers=auth_headers(resolved_token),
        timeout=10,
    )
    if response.status_code >= 400:
        typer.echo(response.text, err=True)
        raise typer.Exit(1)
    current = response.json()
    
    # Update if options provided
    if enabled is not None or message is not None:
        new_config = {
            "enabled": enabled if enabled is not None else current["enabled"],
            "message": message if message is not None else current["message"],
        }
        response = _hub_request_or_exit(
            "POST",
            f"{resolved_hub_url.rstrip('/')}/api/agents/{short_id}/auto_resume",
            headers=auth_headers(resolved_token),
            json=new_config,
            timeout=10,
        )
        if response.status_code >= 400:
            typer.echo(response.text, err=True)
            raise typer.Exit(1)
        typer.echo(f"Agent {short_id} auto resume: {'enabled' if new_config['enabled'] else 'disabled'}")
        typer.echo(f"Resume message: {new_config['message']}")
    else:
        typer.echo(f"Agent {short_id} auto resume: {'enabled' if current['enabled'] else 'disabled'}")
        typer.echo(f"Resume message: {current['message']}")


@daemon_app.command("start")
def daemon_start(
    config_path: Annotated[Path | None, typer.Option(help="AgentTalk config path.")] = None,
    interval: Annotated[float, typer.Option(help="Heartbeat interval seconds.")] = 5.0,
    once: Annotated[bool, typer.Option(help="Run one sync and exit.")] = False,
) -> None:
    config = load_config(config_path)
    if not config.token:
        raise typer.BadParameter("Config token is required. Run agenttalk setup first.")

    # Always refresh lan_ip on startup to handle network changes
    from agenttalk.config import default_lan_ip

    config.lan_ip = default_lan_ip()
    if config.lan_ip:
        typer.echo(f"Detected LAN IP: {config.lan_ip}")
    else:
        typer.echo("Warning: Could not detect LAN IP. Remote Live Terminal may not work.")
        typer.echo("Set AGENTTALK_LAN_IP environment variable to override.")

    relay = AgentTalkRelay(
        config,
        hub_client=HubClient(config.hub_url, config.token),
        tmux_client=get_process_manager(),
    )
    if once:
        try:
            result = relay.sync_once()
        except HubRequestError as exc:
            typer.echo(_format_hub_request_error(exc), err=True)
            raise typer.Exit(1) from exc
        typer.echo(f"Synced {result.upserted} agents ({result.online} online, {result.offline} offline).")
        return

    # Start reverse tunnel client for Live Terminal (relay -> Hub)
    from agenttalk.reverse_tunnel_client import ReverseTunnelClient

    reverse_tunnel = ReverseTunnelClient(
        config,
        tmux_client=get_process_manager(),
    )
    asyncio.get_event_loop().run_until_complete(reverse_tunnel.start())
    typer.echo("Reverse tunnel client started")

    relay.run_forever(interval_seconds=interval, config_path=config_path or default_config_path())


@daemon_app.command("supervise", hidden=True)
def daemon_supervise(
    config_path: Annotated[Path | None, typer.Option(help="AgentTalk config path.")] = None,
    interval: Annotated[float, typer.Option(help="Heartbeat interval seconds.")] = 5.0,
    restart_delay: Annotated[float, typer.Option(help="Restart delay seconds.")] = 2.0,
) -> None:
    stop_path = default_daemon_stop_path()
    log_path = default_daemon_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [_agenttalk_executable(), "daemon", "start", "--interval", str(interval)]
    if config_path is not None:
        cmd.extend(["--config-path", str(config_path)])
    while not stop_path.exists():
        with log_path.open("ab") as log_file:
            child = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
            )
            child.wait()
            if stop_path.exists():
                break
            log_file.write(
                f"\n[agenttalk-supervisor] child exited {child.returncode}; restarting in {restart_delay}s\n".encode()
            )
            log_file.flush()
        time.sleep(restart_delay)
    stop_path.unlink(missing_ok=True)


@daemon_app.command("status")
def daemon_status() -> None:
    pid = _read_pid()
    if _pid_alive(pid):
        typer.echo(f"AgentTalk daemon supervisor running: pid={pid}")
        typer.echo(f"log: {default_daemon_log_path()}")
        return
    unmanaged = _find_daemon_pids()
    if unmanaged:
        typer.echo("AgentTalk daemon running without supervisor pidfile: " + ", ".join(str(pid) for pid in unmanaged))
        typer.echo("Run `agenttalk daemon restart` to replace it with the managed supervisor.")
        return
    typer.echo("AgentTalk daemon supervisor is not running.")
    raise typer.Exit(1)


@daemon_app.command("stop")
def daemon_stop() -> None:
    pid = _read_pid()
    stopped: list[int] = []
    if not _pid_alive(pid):
        for unmanaged_pid in _find_daemon_pids():
            _stop_daemon_process(unmanaged_pid)
            stopped.append(unmanaged_pid)
        if not stopped:
            typer.echo("AgentTalk daemon supervisor is not running.")
        else:
            typer.echo("Stopped unmanaged AgentTalk daemon process(es): " + ", ".join(str(item) for item in stopped))
        default_daemon_pid_path().unlink(missing_ok=True)
        return
    default_daemon_stop_path().parent.mkdir(parents=True, exist_ok=True)
    default_daemon_stop_path().write_text("stop\n", encoding="utf-8")
    _stop_daemon_process(int(pid))
    default_daemon_pid_path().unlink(missing_ok=True)
    typer.echo(f"Stopped AgentTalk daemon supervisor: pid={pid}")


@daemon_app.command("restart")
def daemon_restart(
    config_path: Annotated[Path | None, typer.Option(help="AgentTalk config path.")] = None,
    interval: Annotated[float, typer.Option(help="Heartbeat interval seconds.")] = 5.0,
) -> None:
    pid = _read_pid()
    if _pid_alive(pid):
        default_daemon_stop_path().write_text("stop\n", encoding="utf-8")
        _stop_daemon_process(int(pid))
    for unmanaged_pid in _find_daemon_pids():
        if unmanaged_pid != pid:
            _stop_daemon_process(unmanaged_pid)
    default_daemon_pid_path().unlink(missing_ok=True)
    new_pid = _start_daemon_supervisor(config_path=config_path, interval=interval)
    typer.echo(f"Started AgentTalk daemon supervisor: pid={new_pid}")
    typer.echo(f"log: {default_daemon_log_path()}")


@daemon_app.command("install")
def daemon_install(
    config_path: Annotated[Path | None, typer.Option(help="AgentTalk config path.")] = None,
    interval: Annotated[float, typer.Option(help="Heartbeat interval seconds.")] = 5.0,
) -> None:
    pid = _start_daemon_supervisor(config_path=config_path, interval=interval)
    typer.echo(f"AgentTalk daemon supervisor installed/running: pid={pid}")
    typer.echo(f"log: {default_daemon_log_path()}")


@app.command("doctor")
def doctor(
    config_path: Annotated[Path | None, typer.Option(help="AgentTalk config path.")] = None,
) -> None:
    config = load_config(config_path)
    typer.echo(f"config: {config_path or Path.home() / '.agenttalk' / 'config.json'}")
    typer.echo(f"hub: {config.hub_url or '(unset)'}")
    if not config.token:
        typer.echo("token: missing")
    else:
        typer.echo("token: present")
    pid = _read_pid()
    typer.echo(f"daemon: {'running' if _pid_alive(pid) else 'not running'}" + (f" pid={pid}" if _pid_alive(pid) else ""))
    if config.token:
        try:
            response = hub_request("GET", f"{config.hub_url.rstrip('/')}/health", timeout=5)
            typer.echo(f"hub health: {response.status_code}")
        except Exception as exc:
            typer.echo(f"hub health: failed ({exc})")
    typer.echo(f"local bindings: {len(config.agents)}")
    for binding in config.agents:
        typer.echo(f"  {binding.short_id}: {binding.kind} {binding.tmux_target} {binding.receive_mode.value}")
