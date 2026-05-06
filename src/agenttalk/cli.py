from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import httpx
import typer
import uvicorn

from agenttalk.hub.app import create_app
from agenttalk.hub.settings import HubSettings, default_database_path


app = typer.Typer(help="AgentTalk CLI.")
hub_app = typer.Typer(help="Run and manage the AgentTalk Hub.")
app.add_typer(hub_app, name="hub")


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
) -> None:
    settings = HubSettings(
        database_path=database,
        token=resolve_token(token),
        heartbeat_ttl_seconds=heartbeat_ttl,
    )
    uvicorn.run(create_app(settings), host=host, port=port)


@app.command("list")
def list_agents(
    hub_url: Annotated[str, typer.Option(help="Hub base URL.")] = "http://127.0.0.1:8787",
    token: Annotated[str | None, typer.Option(help="Shared LAN bearer token.")] = None,
    owner: Annotated[str | None, typer.Option(help="Filter by owner.")] = None,
    machine_id: Annotated[str | None, typer.Option(help="Filter by machine id.")] = None,
) -> None:
    resolved_token = resolve_token(token)
    params = {key: value for key, value in {"owner": owner, "machine_id": machine_id}.items() if value}
    response = httpx.get(
        f"{hub_url.rstrip('/')}/api/agents",
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
