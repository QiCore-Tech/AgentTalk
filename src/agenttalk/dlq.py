from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def default_dlq_path() -> Path:
    return Path.home() / ".agenttalk" / "dlq.json"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def load_dead_letters(path: Path | None = None) -> list[dict[str, Any]]:
    resolved = path or default_dlq_path()
    if not resolved.exists():
        return []
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def save_dead_letters(records: list[dict[str, Any]], path: Path | None = None) -> None:
    resolved = path or default_dlq_path()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(json.dumps(records, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def record_dead_letter(
    *,
    message: dict[str, Any],
    reason: str,
    error: str = "",
    path: Path | None = None,
) -> dict[str, Any]:
    message_id = str(message.get("message_id", ""))
    records = [item for item in load_dead_letters(path) if item.get("message_id") != message_id]
    record = {
        "message_id": message_id,
        "sender": str(message.get("sender", "")),
        "target": str(message.get("target", "")),
        "reason": reason,
        "error": error,
        "status": "open",
        "created_at": _now(),
        "updated_at": _now(),
        "body_preview": " ".join(str(message.get("body", "")).split())[:500],
    }
    records.append(record)
    save_dead_letters(records, path)
    return record


def mark_dead_letter(
    message_id: str,
    *,
    status: str,
    note: str = "",
    path: Path | None = None,
) -> dict[str, Any] | None:
    records = load_dead_letters(path)
    updated: dict[str, Any] | None = None
    for record in records:
        if record.get("message_id") != message_id:
            continue
        record["status"] = status
        record["note"] = note
        record["updated_at"] = _now()
        updated = record
        break
    if updated is not None:
        save_dead_letters(records, path)
    return updated


def open_dead_letters(path: Path | None = None) -> list[dict[str, Any]]:
    return [record for record in load_dead_letters(path) if record.get("status") == "open"]
