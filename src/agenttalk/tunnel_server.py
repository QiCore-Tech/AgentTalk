from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
from typing import Any

import websockets
from websockets.server import WebSocketServerProtocol

from agenttalk.config import AgentTalkConfig

logger = logging.getLogger(__name__)


class TunnelSession:
    """Manages a single tmux tunnel session for a specific agent."""

    def __init__(self, websocket: WebSocketServerProtocol, tmux_target: str, token: str) -> None:
        self.websocket = websocket
        self.tmux_target = tmux_target
        self.token = token
        self._closed = False
        self._tmux_socket = os.environ.get("TMUX_SOCKET", "/tmp/tmux-1000/default")
        self._capture_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the tunnel session: begin capturing tmux output and forwarding."""
        logger.info("Tunnel session started for %s", self.tmux_target)
        self._capture_task = asyncio.create_task(self._capture_loop())

    async def _capture_loop(self) -> None:
        """Continuously capture tmux output and send to websocket."""
        last_output = ""
        while not self._closed:
            try:
                output = await self._capture_once()
                if output != last_output:
                    last_output = output
                    # Send output to websocket
                    await self.websocket.send(output)
            except Exception as exc:
                logger.warning("Tunnel capture error for %s: %s", self.tmux_target, exc)
                await asyncio.sleep(1)

    async def _capture_once(self) -> str:
        """Capture tmux output once."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_capture)

    def _sync_capture(self) -> str:
        """Synchronous tmux capture."""
        proc = subprocess.run(
            ["tmux", "-S", self._tmux_socket, "capture-pane", "-p", "-t", self.tmux_target, "-S", "-120"],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"tmux capture failed: {proc.stderr}")
        return proc.stdout

    async def handle_input(self, data: str) -> None:
        """Handle input from websocket and inject into tmux."""
        if self._closed:
            return
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._sync_input, data)

    def _sync_input(self, data: str) -> None:
        """Synchronous tmux input injection."""
        # Handle special resize command
        if data.startswith("\x01"):
            try:
                _, rows, cols = data.split(":")
                subprocess.run(
                    ["tmux", "-S", self._tmux_socket, "resize-pane", "-t", self.tmux_target, "-x", cols, "-y", rows],
                    capture_output=True,
                    check=False,
                )
                return
            except (ValueError, IndexError):
                pass

        # Regular input - use send-keys
        subprocess.run(
            ["tmux", "-S", self._tmux_socket, "send-keys", "-t", self.tmux_target, data],
            capture_output=True,
            check=False,
        )

    async def close(self) -> None:
        """Close the tunnel session."""
        self._closed = True
        if self._capture_task and not self._capture_task.done():
            self._capture_task.cancel()
        try:
            await self.websocket.close()
        except Exception:
            pass


class TunnelServer:
    """WebSocket tunnel server that runs on the relay machine.

    Provides remote access to local tmux sessions via WebSocket.
    """

    def __init__(self, config: AgentTalkConfig, host: str = "0.0.0.0", port: int = 8788) -> None:
        self.config = config
        self.host = host
        self.port = port
        self._server: Any = None
        self._sessions: dict[str, TunnelSession] = {}
        self._running = False

    async def start(self) -> None:
        """Start the tunnel server."""
        if self._running:
            return
        self._running = True
        logger.info("Starting tunnel server on %s:%d", self.host, self.port)
        self._server = await websockets.serve(
            self._handle_connection,
            self.host,
            self.port,
        )
        logger.info("Tunnel server started on %s:%d", self.host, self.port)

    async def stop(self) -> None:
        """Stop the tunnel server."""
        self._running = False
        for session in list(self._sessions.values()):
            await session.close()
        self._sessions.clear()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        logger.info("Tunnel server stopped")

    async def _handle_connection(self, websocket: WebSocketServerProtocol, path: str) -> None:
        """Handle a new WebSocket connection."""
        try:
            # Parse path to extract short_id
            # Expected path: /tunnel/{short_id}
            parts = path.strip("/").split("/")
            if len(parts) < 2 or parts[0] != "tunnel":
                await websocket.close(code=4000, reason="Invalid path. Expected /tunnel/{short_id}")
                return

            short_id = parts[1]

            # Wait for authentication message
            auth_msg = await asyncio.wait_for(websocket.recv(), timeout=5.0)
            auth_data = json.loads(auth_msg)
            token = auth_data.get("token", "")

            if token != self.config.token:
                await websocket.close(code=4001, reason="Invalid token")
                return

            # Find the agent binding
            binding = next(
                (agent for agent in self.config.agents if agent.short_id == short_id),
                None,
            )
            if binding is None:
                await websocket.close(code=4004, reason=f"Agent not found: {short_id}")
                return

            # Create tunnel session
            session = TunnelSession(websocket, binding.tmux_target, token)
            self._sessions[short_id] = session
            await session.start()

            # Handle incoming messages from websocket (browser input)
            try:
                async for message in websocket:
                    if isinstance(message, str):
                        await session.handle_input(message)
                    else:
                        await session.handle_input(message.decode("utf-8"))
            except websockets.exceptions.ConnectionClosed:
                pass
            finally:
                await session.close()
                self._sessions.pop(short_id, None)

        except asyncio.TimeoutError:
            await websocket.close(code=4001, reason="Authentication timeout")
        except json.JSONDecodeError:
            await websocket.close(code=4001, reason="Invalid authentication format")
        except Exception as exc:
            logger.exception("Tunnel connection error: %s", exc)
            await websocket.close(code=1011, reason="Internal error")


def start_tunnel_server(config: AgentTalkConfig) -> TunnelServer:
    """Create and start a tunnel server."""
    port = int(os.environ.get("AGENTTALK_TUNNEL_PORT", "8788"))
    server = TunnelServer(config, port=port)
    asyncio.create_task(server.start())
    return server
