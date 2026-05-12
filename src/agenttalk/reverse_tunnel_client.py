from __future__ import annotations

import asyncio
import json
import logging
import threading
from typing import Any

import websockets
from websockets.client import WebSocketClientProtocol

from agenttalk.config import AgentTalkConfig
from agenttalk.process_manager import ProcessManager

logger = logging.getLogger(__name__)


class ReverseTunnelClient:
    """Relay-side client that maintains a persistent WebSocket connection to Hub.

    This enables the Hub to access local tmux sessions without requiring
    routable IP addresses or port mappings.
    """

    def __init__(
        self,
        config: AgentTalkConfig,
        tmux_client: ProcessManager,
        hub_url: str = "",
    ) -> None:
        self.config = config
        self.tmux_client = tmux_client
        self.hub_url = hub_url or config.hub_url.rstrip("/").replace("https://", "wss://").replace("http://", "ws://")
        self.ws: WebSocketClientProtocol | None = None
        self._running = False
        self._sessions: dict[str, dict[str, Any]] = {}  # session_id -> {short_id, tmux_target, task}
        self._reconnect_delay = 1.0
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None

    async def start(self) -> None:
        """Start the reverse tunnel connection."""
        if self._running:
            return
        self._running = True
        asyncio.create_task(self._connect_loop())
        logger.info("Reverse tunnel client started for %s", self.config.machine_id)

    def start_background(self) -> None:
        """Start the reverse tunnel client on a dedicated event loop thread."""
        if self._thread and self._thread.is_alive():
            return

        started = threading.Event()
        errors: list[BaseException] = []

        def run() -> None:
            loop = asyncio.new_event_loop()
            self._loop = loop
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self.start())
            except BaseException as exc:
                errors.append(exc)
                started.set()
                return
            started.set()
            loop.run_forever()

        self._thread = threading.Thread(target=run, name="agenttalk-reverse-tunnel", daemon=True)
        self._thread.start()
        started.wait(timeout=5)
        if errors:
            raise RuntimeError(f"failed to start reverse tunnel client: {errors[0]}") from errors[0]

    async def stop(self) -> None:
        """Stop the reverse tunnel connection."""
        self._running = False
        for session in list(self._sessions.values()):
            task = session.get("task")
            if task:
                task.cancel()
        self._sessions.clear()
        if self.ws:
            await self.ws.close()
        logger.info("Reverse tunnel client stopped")

    async def _connect_loop(self) -> None:
        """Maintain persistent connection with automatic reconnection."""
        while self._running:
            try:
                await self._connect_once()
                self._reconnect_delay = 1.0  # Reset on success
            except Exception as exc:
                logger.warning("Reverse tunnel connection failed: %s. Retrying in %.1fs...", exc, self._reconnect_delay)
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 30.0)

    async def _connect_once(self) -> None:
        """Establish a single connection and handle messages."""
        url = f"{self.hub_url}/ws/relay-terminal/{self.config.machine_id}"
        logger.info("Connecting to Hub reverse tunnel: %s", url)

        async with websockets.connect(url) as ws:
            self.ws = ws
            try:
                # Send hello with auth
                await ws.send(json.dumps({
                    "type": "hello",
                    "machine_id": self.config.machine_id,
                    "token": self.config.token,
                    "version": "1.0",
                }))
                logger.info("Reverse tunnel hello sent for %s", self.config.machine_id)

                async for message in ws:
                    try:
                        await self._handle_message(json.loads(message))
                    except Exception as exc:
                        logger.exception("Error handling reverse tunnel message: %s", exc)
            finally:
                self.ws = None

    async def _handle_message(self, msg: dict[str, Any]) -> None:
        """Handle incoming message from Hub."""
        msg_type = msg.get("type", "")
        session_id = msg.get("session_id", "")

        if msg_type == "terminal_start":
            await self._handle_terminal_start(msg)
        elif msg_type == "terminal_input":
            await self._handle_terminal_input(session_id, msg.get("data", ""))
        elif msg_type == "terminal_resize":
            await self._handle_terminal_resize(session_id, msg.get("rows", 24), msg.get("cols", 80))
        elif msg_type == "terminal_close":
            await self._handle_terminal_close(session_id)
        elif msg_type == "hello_ok":
            logger.info("Hub accepted reverse tunnel connection")
            print("Hub accepted reverse tunnel connection", flush=True)

    async def _handle_terminal_start(self, msg: dict[str, Any]) -> None:
        """Start capturing tmux output for a new terminal session."""
        short_id = msg.get("short_id", "")
        session_id = msg.get("session_id", "")

        if not short_id or not session_id:
            await self._send({
                "type": "terminal_error",
                "session_id": session_id,
                "message": "Missing short_id or session_id",
            })
            return

        # Find the tmux target for this agent
        binding = next(
            (agent for agent in self.config.agents if agent.short_id == short_id),
            None,
        )
        if binding is None:
            await self._send({
                "type": "terminal_error",
                "session_id": session_id,
                "message": f"Agent {short_id} not found on this relay",
            })
            return

        # Start capture task
        task = asyncio.create_task(
            self._capture_loop(session_id, binding.tmux_target)
        )
        self._sessions[session_id] = {
            "short_id": short_id,
            "tmux_target": binding.tmux_target,
            "task": task,
        }

    async def _capture_loop(self, session_id: str, tmux_target: str) -> None:
        """Continuously capture tmux output and send to Hub."""
        last_output = ""
        while session_id in self._sessions:
            try:
                output = await self._capture_once(tmux_target)
                if output != last_output:
                    last_output = output
                    await self._send({
                        "type": "terminal_output",
                        "session_id": session_id,
                        "data": output,
                    })
            except Exception as exc:
                logger.warning("Terminal capture error for %s: %s", session_id, exc)
                await self._send({
                    "type": "terminal_error",
                    "session_id": session_id,
                    "message": str(exc),
                })
            await asyncio.sleep(0.5)

    async def _capture_once(self, tmux_target: str) -> str:
        """Capture tmux output once."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_capture, tmux_target)

    def _sync_capture(self, tmux_target: str) -> str:
        """Synchronous tmux capture."""
        return self.tmux_client.capture_output(tmux_target, lines=120)

    async def _handle_terminal_input(self, session_id: str, data: str) -> None:
        """Handle input data from browser (via Hub)."""
        session = self._sessions.get(session_id)
        if session is None:
            return

        tmux_target = session["tmux_target"]
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._sync_input, tmux_target, data)

    async def _handle_terminal_resize(self, session_id: str, rows: int, cols: int) -> None:
        """Handle resize command."""
        session = self._sessions.get(session_id)
        if session is None:
            return

        tmux_target = session["tmux_target"]
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._sync_resize, tmux_target, rows, cols)

    def _sync_input(self, tmux_target: str, data: str) -> None:
        """Synchronous tmux input injection."""
        import subprocess
        subprocess.run(
            ["tmux", "send-keys", "-l", "-t", tmux_target, data],
            capture_output=True,
            check=False,
        )

    def _sync_resize(self, tmux_target: str, rows: int, cols: int) -> None:
        """Synchronous tmux resize."""
        import subprocess
        subprocess.run(
            ["tmux", "resize-pane", "-t", tmux_target, "-y", str(rows), "-x", str(cols)],
            capture_output=True,
            check=False,
        )

    async def _handle_terminal_close(self, session_id: str) -> None:
        """Clean up a terminal session."""
        session = self._sessions.pop(session_id, None)
        if session:
            task = session.get("task")
            if task:
                task.cancel()

    async def _send(self, msg: dict[str, Any]) -> None:
        """Send message to Hub via websocket."""
        if self.ws and self.ws.open:
            try:
                await self.ws.send(json.dumps(msg))
            except Exception as exc:
                logger.warning("Failed to send to Hub: %s", exc)
