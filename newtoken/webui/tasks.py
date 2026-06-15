"""Background task registry for the dependency-light WebUI."""

from __future__ import annotations

import concurrent.futures
import secrets
import threading
import time
from typing import Any

MAX_WEB_TASK_WORKERS = 4


class WebTaskStore:
    """Small bounded task registry for background WebUI actions."""

    def __init__(self, max_items: int = 80, max_workers: int = MAX_WEB_TASK_WORKERS) -> None:
        self.max_items = max(10, int(max_items))
        self._lock = threading.Lock()
        self._tasks: dict[str, dict[str, Any]] = {}
        self._active_by_label: dict[str, str] = {}
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, int(max_workers)),
            thread_name_prefix="sub2api-web-task",
        )

    def create(self, label: str, target, *args, **kwargs) -> str:
        normalized_label = str(label or "").strip()
        if not normalized_label:
            raise ValueError("任务名称为空")
        task_id = secrets.token_urlsafe(10)
        task = {
            "id": task_id,
            "label": normalized_label,
            "status": "queued",
            "created_at": time.time(),
            "started_at": None,
            "finished_at": None,
            "result": None,
            "error": "",
            "reused": False,
        }
        with self._lock:
            active_task_id = self._active_by_label.get(normalized_label)
            if active_task_id and active_task_id in self._tasks:
                self._tasks[active_task_id]["reused"] = True
                return active_task_id
            self._tasks[task_id] = task
            self._active_by_label[normalized_label] = task_id
            self._trim_locked()

        def runner() -> None:
            with self._lock:
                task["status"] = "running"
                task["started_at"] = time.time()
            try:
                result = target(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    task["status"] = "error"
                    task["error"] = str(exc)
                    task["finished_at"] = time.time()
                    self._active_by_label.pop(normalized_label, None)
                    self._trim_locked()
                return
            with self._lock:
                task["status"] = "done"
                task["result"] = result
                task["finished_at"] = time.time()
                self._active_by_label.pop(normalized_label, None)
                self._trim_locked()

        self._executor.submit(runner)
        return task_id

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            task = self._tasks.get(str(task_id or ""))
            return dict(task) if task else None

    def list_recent(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                self._summarize_task(item)
                for item in sorted(
                    self._tasks.values(),
                    key=lambda value: float(value.get("created_at") or 0),
                    reverse=True,
                )
            ]

    def shutdown(self, *, wait: bool = False) -> None:
        try:
            self._executor.shutdown(wait=wait, cancel_futures=False)
        except TypeError:
            self._executor.shutdown(wait=wait)

    def _trim_locked(self) -> None:
        while len(self._tasks) > self.max_items:
            completed_keys = [
                key
                for key, task in self._tasks.items()
                if task.get("status") not in {"queued", "running"}
            ]
            if completed_keys:
                oldest_key = min(
                    completed_keys,
                    key=lambda key: float(self._tasks[key].get("created_at") or 0),
                )
            else:
                break
            self._tasks.pop(oldest_key, None)

    @staticmethod
    def _summarize_task(task: dict[str, Any]) -> dict[str, Any]:
        result = task.get("result") if isinstance(task.get("result"), dict) else {}
        summary_keys = (
            "total_count",
            "alive_count",
            "dead_count",
            "no_quota_count",
            "usable_count",
            "total_candidates",
            "low_quota_count",
            "chatgpt_count",
            "chatgpt_limit",
            "deleted",
            "failed",
            "account_created",
            "account_failed",
        )
        result_summary = {
            key: result.get(key)
            for key in summary_keys
            if key in result
        }
        return {
            "id": task.get("id"),
            "label": task.get("label"),
            "status": task.get("status"),
            "created_at": task.get("created_at"),
            "started_at": task.get("started_at"),
            "finished_at": task.get("finished_at"),
            "error": task.get("error"),
            "reused": bool(task.get("reused")),
            "result_summary": result_summary,
        }
