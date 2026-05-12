from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from fastapi.websockets import WebSocket

logger = logging.getLogger(__name__)


class RelayConnection:
    """Represents a single relay's persistent websocket connection to Hub."""

    def __init__(self, machine_id: str, websocket: WebSocket) -> None:
        self.machine_id = machine_id
        self.ws = websocket
        self.sessions: set[str] = set()  # active session_ids
        self._lock = asyncio.Lock()
        self.last_seen = asyncio.get_event_loop().time()
        self._closed = False

    async def send(self, msg: dict[str, Any]) -> bool:
        """Send message to relay. Returns False if failed."""
        if self._closed:
            return False
        try:
            async with self._lock:
                await self.ws.send_json(msg)
            self.last_seen = asyncio.get_event_loop().time()
            return True
        except Exception as exc:
            logger.warning("Failed to send to relay %s: %s", self.machine_id, exc)
            return False

    async def close(self) -> None:
        """Close connection and clean up."""
        self._closed = True
        try:
            await self.ws.close()
        except Exception:
            pass


class RelayConnectionManager:
    """Manages all reverse tunnel connections from relays to Hub."""

    def __init__(self) -> None:
        self._connections: dict[str, RelayConnection] = {}  # machine_id -> RelayConnection
        self._browser_sessions: dict[str, dict[str, Any]] = {}  # session_id -> {machine_id, short_id, browser_ws}

    def register(self, machine_id: str, connection: RelayConnection) -> None:
        """Register a new relay connection."""
        # Close old connection if exists
        old = self._connections.get(machine_id)
        if old:
            asyncio.create_task(old.close())
        self._connections[machine_id] = connection
        logger.info("Relay registered: %s", machine_id)

    def unregister(self, machine_id: str) -> None:
        """Remove a relay connection."""
        conn = self._connections.pop(machine_id, None)
        if conn:
            # Close all browser sessions using this relay
            for session_id, session in list(self._browser_sessions.items()):
                if session.get("machine_id") == machine_id:
                    asyncio.create_task(self._close_browser_session(session_id, "relay disconnected"))
            logger.info("Relay unregistered: %s", machine_id)

    def get_connection(self, machine_id: str) -> RelayConnection | None:
        """Get relay connection by machine_id."""
        return self._connections.get(machine_id)

    def is_connected(self, machine_id: str) -> bool:
        """Check if relay is connected."""
        conn = self._connections.get(machine_id)
        return conn is not None and not conn._closed

    async def open_terminal(
        self,
        machine_id: str,
        short_id: str,
        browser_ws: WebSocket,
    ) -> str | None:
        """Open a terminal session via reverse relay.

        Returns session_id if successful, None if relay not connected.
        """
        conn = self._connections.get(machine_id)
        if not conn or conn._closed:
            return None

        session_id = str(uuid.uuid4())
        self._browser_sessions[session_id] = {
            "machine_id": machine_id,
            "short_id": short_id,
            "browser_ws": browser_ws,
        }
        conn.sessions.add(session_id)

        # Send terminal_start to relay
        success = await conn.send({
            "type": "terminal_start",
            "session_id": session_id,
            "short_id": short_id,
        })

        if not success:
            self._browser_sessions.pop(session_id, None)
            conn.sessions.discard(session_id)
            return None

        return session_id

    async def send_input(self, session_id: str, data: str) -> bool:
        """Send input to relay for a terminal session."""
        session = self._browser_sessions.get(session_id)
        if not session:
            return False

        conn = self._connections.get(session["machine_id"])
        if not conn or conn._closed:
            return False

        return await conn.send({
            "type": "terminal_input",
            "session_id": session_id,
            "data": data,
        })

    async def send_resize(self, session_id: str, rows: int, cols: int) -> bool:
        """Send resize to relay for a terminal session."""
        session = self._browser_sessions.get(session_id)
        if not session:
            return False

        conn = self._connections.get(session["machine_id"])
        if not conn or conn._closed:
            return False

        return await conn.send({
            "type": "terminal_resize",
            "session_id": session_id,
            "rows": rows,
            "cols": cols,
        })

    async def close_terminal(self, session_id: str) -> None:
        """Close a terminal session."""
        session = self._browser_sessions.pop(session_id, None)
        if session:
            conn = self._connections.get(session["machine_id"])
            if conn:
                conn.sessions.discard(session_id)
                await conn.send({
                    "type": "terminal_close",
                    "session_id": session_id,
                })

    async def handle_relay_output(self, session_id: str, data: str) -> None:
        """Handle output from relay and forward to browser."""
        session = self._browser_sessions.get(session_id)
        if not session:
            return

        browser_ws = session.get("browser_ws")
        if not browser_ws:
            return

        try:
            await browser_ws.send_text(data)
        except Exception as exc:
            logger.warning("Failed to send to browser for session %s: %s", session_id, exc)

    async def handle_relay_error(self, session_id: str, message: str) -> None:
        """Handle error from relay and forward to browser."""
        session = self._browser_sessions.get(session_id)
        if not session:
            return

        browser_ws = session.get("browser_ws")
        if not browser_ws:
            return

        try:
            await browser_ws.send_text(f"\x1b[31m[Relay error: {message}]\x1b[0m\r\n")
        except Exception:
            pass

    async def _close_browser_session(self, session_id: str, reason: str) -> None:
        """Close browser session with reason."""
        session = self._browser_sessions.pop(session_id, None)
        if session:
            browser_ws = session.get("browser_ws")
            if browser_ws:
                try:
                    await browser_ws.send_text(f"\x1b[31m[{reason}]\x1b[0m\r\n")
                except Exception:
                    pass

    def get_stats(self) -> dict[str, Any]:
        """Get connection statistics."""
        return {
            "connected_relays": list(self._connections.keys()),
            "active_sessions": len(self._browser_sessions),
            "sessions_per_relay": {
                machine_id: len(conn.sessions)
                for machine_id, conn in self._connections.items()
            },
        }


# Global singleton
relay_manager = RelayConnectionManager()
