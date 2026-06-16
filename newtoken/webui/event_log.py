"""Persistent policy event log for the WebUI."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

MAX_POLICY_EVENTS = 300


class PolicyEventStore:
    """Thread-safe JSON event store retaining the newest policy events."""

    def __init__(self, path: Path, max_items: int = MAX_POLICY_EVENTS) -> None:
        self.path = path
        self.max_items = max(1, int(max_items))
        self._lock = threading.Lock()

    def append(
        self,
        *,
        action: str,
        email: str = "",
        account_id: int | None = None,
        reason: str = "",
        result: str = "",
        details: dict[str, Any] | None = None,
        created_at: float | None = None,
    ) -> dict[str, Any]:
        event = {
            "created_at": float(created_at if created_at is not None else time.time()),
            "action": str(action or "").strip(),
            "email": str(email or "").strip().lower(),
            "account_id": int(account_id) if account_id is not None else None,
            "reason": str(reason or "").strip(),
            "result": str(result or "").strip(),
            "details": dict(details or {}),
        }
        with self._lock:
            events = self._read_locked()
            events.append(event)
            events = events[-self.max_items :]
            self._write_locked(events)
        return dict(event)

    def list_recent(self, limit: int = MAX_POLICY_EVENTS) -> list[dict[str, Any]]:
        normalized_limit = max(1, min(int(limit), self.max_items))
        with self._lock:
            events = self._read_locked()
        return [
            dict(item)
            for item in reversed(events[-normalized_limit:])
            if isinstance(item, dict)
        ]

    def _read_locked(self) -> list[dict[str, Any]]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return []
        if not isinstance(payload, list):
            return []
        return [item for item in payload if isinstance(item, dict)]

    def _write_locked(self, events: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(events, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(self.path)

