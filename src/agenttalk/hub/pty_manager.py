from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import select
import struct
import termios
from dataclasses import dataclass, field


@dataclass
class PTYSession:
    """Manages a single PTY session for an agent."""

    master_fd: int
    slave_fd: int
    pid: int
    short_id: str
    shell: str = "/bin/bash"
    _read_task: asyncio.Task | None = None
    _write_queue: asyncio.Queue[bytes] = field(default_factory=asyncio.Queue)
    _closed: bool = False

    @classmethod
    def create(cls, short_id: str, shell: str = "/bin/bash") -> "PTYSession":
        """Create a new PTY session."""
        master_fd, slave_fd = pty.openpty()

        pid = os.fork()
        if pid == 0:
            # Child process
            os.setsid()
            os.dup2(slave_fd, 0)
            os.dup2(slave_fd, 1)
            os.dup2(slave_fd, 2)

            # Close master in child
            os.close(master_fd)

            # Set terminal size
            # Use default 80x24
            struct.pack("HHHH", 24, 80, 0, 0)

            os.execv(shell, [shell, "-l"])
            os._exit(1)

        # Parent process
        os.close(slave_fd)

        # Set non-blocking
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        return cls(
            master_fd=master_fd,
            slave_fd=-1,  # Closed in parent
            pid=pid,
            short_id=short_id,
            shell=shell,
        )

    def set_size(self, rows: int, cols: int) -> None:
        """Resize the PTY."""
        size = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, size)

    async def start_reader(self, websocket) -> None:
        """Start reading from PTY and sending to websocket."""
        loop = asyncio.get_event_loop()

        while not self._closed:
            try:
                # Use asyncio to read non-blocking
                data = await loop.run_in_executor(
                    None, self._read_from_pty, 0.1
                )
                if data:
                    await websocket.send_bytes(data)
            except Exception:
                break

    def _read_from_pty(self, timeout: float) -> bytes | None:
        """Read available data from PTY."""
        readable, _, _ = select.select([self.master_fd], [], [], timeout)
        if self.master_fd in readable:
            try:
                return os.read(self.master_fd, 4096)
            except OSError:
                return None
        return b""

    async def start_writer(self) -> None:
        """Start writing to PTY from queue."""
        while not self._closed:
            try:
                data = await asyncio.wait_for(
                    self._write_queue.get(), timeout=0.5
                )
                os.write(self.master_fd, data)
            except asyncio.TimeoutError:
                continue
            except Exception:
                break

    def write(self, data: bytes | str) -> None:
        """Queue data to write to PTY."""
        if isinstance(data, str):
            data = data.encode("utf-8")
        self._write_queue.put_nowait(data)

    def close(self) -> None:
        """Close the PTY session."""
        self._closed = True
        try:
            os.close(self.master_fd)
        except OSError:
            pass
        try:
            os.kill(self.pid, 9)
        except ProcessLookupError:
            pass


class PTYManager:
    """Manages PTY sessions for all agents."""

    def __init__(self):
        self._sessions: dict[str, PTYSession] = {}

    def get_or_create(self, short_id: str) -> PTYSession:
        """Get existing session or create new one."""
        if short_id not in self._sessions:
            self._sessions[short_id] = PTYSession.create(short_id)
        return self._sessions[short_id]

    def get(self, short_id: str) -> PTYSession | None:
        """Get existing session."""
        return self._sessions.get(short_id)

    def remove(self, short_id: str) -> None:
        """Remove and close a session."""
        session = self._sessions.pop(short_id, None)
        if session:
            session.close()

    def write_to_agent(self, short_id: str, data: bytes | str) -> bool:
        """Write data to agent's PTY."""
        session = self.get(short_id)
        if session is None:
            return False
        session.write(data)
        return True

    def list_sessions(self) -> list[str]:
        """List all active session IDs."""
        return list(self._sessions.keys())

    def cleanup(self) -> None:
        """Close all sessions."""
        for session in self._sessions.values():
            session.close()
        self._sessions.clear()


# Global singleton
pty_manager = PTYManager()
