from __future__ import annotations

# 重新导出，保持向后兼容
from agenttalk.process_manager import (
    ManagedProcess as TmuxPane,
    TmuxProcessManager as TmuxClient,
    get_process_manager,
    is_process_alive,
    output_fingerprint,
)

__all__ = ["TmuxClient", "TmuxPane", "get_process_manager", "is_process_alive", "output_fingerprint"]
