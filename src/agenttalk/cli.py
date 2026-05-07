from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Annotated

import httpx
import typer
import uvicorn

from agenttalk.config import AgentBinding, AgentTalkConfig, load_config, save_config, upsert_binding
from agenttalk.hub.client import HubClient
from agenttalk.hub.app import create_app
from agenttalk.hub.models import ReceiveMode
from agenttalk.hub.settings import HubSettings, default_database_path
from agenttalk.relay import AgentTalkRelay
from agenttalk.process_manager import get_process_manager


app = typer.Typer(help="AgentTalk CLI.")
hub_app = typer.Typer(help="Run and manage the AgentTalk Hub.")
daemon_app = typer.Typer(help="Run the local AgentTalk relay.")
config_app = typer.Typer(help="Manage Hub configuration.")
app.add_typer(hub_app, name="hub")
app.add_typer(daemon_app, name="daemon")
app.add_typer(config_app, name="config")


def resolve_token(token: str | None) -> str:
    resolved = token or os.environ.get("AGENTTALK_TOKEN")
    if not resolved:
        raise typer.BadParameter("Token is required via --token or AGENTTALK_TOKEN")
    return resolved


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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
    response = httpx.get(
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
    binding = AgentBinding(
        short_id=short_id,
        owner=owner or config.user_name,
        kind=kind,
        workspace=workspace,
        tmux_target=tmux_target,
        pane_id=pane_id,
        receive_mode=receive_mode,
    )
    config = upsert_binding(config, binding)
    save_config(config, config_path)
    if sync and config.token:
        relay = AgentTalkRelay(
            config,
            hub_client=HubClient(config.hub_url, config.token),
            tmux_client=get_process_manager(),
        )
        relay.sync_once()
    typer.echo(f"Registered local binding: {short_id}")


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
    response = httpx.delete(
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
    response = httpx.post(
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
    if watch:
        watch_message(
            payload["message_id"],
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
    response = httpx.get(
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
    response = httpx.get(
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
    response = httpx.get(
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
        message_payload = httpx.get(
            f"{resolved_hub_url.rstrip('/')}/api/messages/{message_id}",
            headers=auth_headers(resolved_token),
            timeout=10,
        )
        message_payload.raise_for_status()
        message = message_payload.json()
        if message["status"] != last_status:
            typer.echo(f"[{message['status']}]")
            last_status = message["status"]
        response_payload = httpx.get(
            f"{resolved_hub_url.rstrip('/')}/api/messages/{message_id}/response",
            headers=auth_headers(resolved_token),
            timeout=10,
        )
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
    response = httpx.get(
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
        response = httpx.post(
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
    relay = AgentTalkRelay(
        config,
        hub_client=HubClient(config.hub_url, config.token),
        tmux_client=get_process_manager(),
    )
    if once:
        result = relay.sync_once()
        typer.echo(f"Synced {result.upserted} agents ({result.online} online, {result.offline} offline).")
        return
    relay.run_forever(interval_seconds=interval)
