"""Server-side schedulers for WebUI automation."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from newtoken.webui.auto import run_auto_maintenance
from newtoken.webui.config import (
    AUTO_MAINTENANCE_TASK_LABEL,
    AUTO_POLICY_DEFAULT_INTERVAL_SECONDS,
    AUTO_POLICY_MAX_INTERVAL_SECONDS,
    AUTO_POLICY_MIN_INTERVAL_SECONDS,
    get_setup_missing_fields,
    has_effective_config_value,
    is_setup_complete,
)
from newtoken.webui.utils import parse_bool_text, parse_positive_int

if TYPE_CHECKING:
    from newtoken.webui.config import WebState


STARTUP_DELAY_SECONDS = 10
WAKE_CHECK_SECONDS = 5


@dataclass(frozen=True)
class PolicySchedulerConfig:
    enabled: bool
    interval_seconds: int
    run_on_start: bool


def read_policy_scheduler_config(values: dict[str, str]) -> PolicySchedulerConfig:
    """Read scheduler behavior from WebUI config values."""

    return PolicySchedulerConfig(
        enabled=parse_bool_text(values.get("SUB2API_AUTO_POLICY_ENABLED"), default=True),
        interval_seconds=parse_positive_int(
            values.get("SUB2API_AUTO_POLICY_INTERVAL_SECONDS"),
            AUTO_POLICY_DEFAULT_INTERVAL_SECONDS,
            minimum=AUTO_POLICY_MIN_INTERVAL_SECONDS,
            maximum=AUTO_POLICY_MAX_INTERVAL_SECONDS,
        ),
        run_on_start=parse_bool_text(
            values.get("SUB2API_AUTO_POLICY_RUN_ON_START"),
            default=True,
        ),
    )


def find_missing_policy_config(values: dict[str, str]) -> list[str]:
    """Return missing config keys that would make the policy task fail immediately."""

    if not is_setup_complete(values):
        return get_setup_missing_fields(values)
    missing: list[str] = []
    for key in ("SUB2API_BASE_URL", "SUB2API_ADMIN_API_KEY", "OPENAI_ACCOUNT_ID"):
        if not has_effective_config_value(key, values.get(key, "")):
            missing.append(key)
    if not has_effective_config_value("OPENAI_ACCESS_TOKEN", values.get("OPENAI_ACCESS_TOKEN", "")) and not has_effective_config_value(
        "OPENAI_SESSION_TOKEN", values.get("OPENAI_SESSION_TOKEN", "")
    ):
        missing.append("OPENAI_ACCESS_TOKEN/OPENAI_SESSION_TOKEN")
    return missing


class WebScheduler:
    """Runs WebUI automation from the server process, independent of the browser."""

    def __init__(self, state: WebState) -> None:
        self.state = state
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._status: dict[str, Any] = {
            "running": False,
            "enabled": True,
            "interval_seconds": AUTO_POLICY_DEFAULT_INTERVAL_SECONDS,
            "run_on_start": True,
            "next_run_at": None,
            "last_tick_at": None,
            "last_task_id": "",
            "last_error": "",
            "skipped_reason": "",
        }

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._wake_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="sub2api-web-scheduler",
                daemon=True,
            )
            self._status["running"] = True
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=5)
        with self._lock:
            self._status["running"] = False
            self._status["next_run_at"] = None

    def wake(self) -> None:
        """Ask the scheduler to re-read config soon."""

        self._wake_event.set()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def _run(self) -> None:
        values = self.state.load_config()
        config = read_policy_scheduler_config(values)
        next_run_at = time.time() + (
            STARTUP_DELAY_SECONDS if config.run_on_start else config.interval_seconds
        )
        self._set_config_status(config, next_run_at=next_run_at)

        while not self._stop_event.is_set():
            wait_seconds = max(0.0, next_run_at - time.time())
            if self._stop_event.wait(timeout=min(wait_seconds, WAKE_CHECK_SECONDS)):
                break
            if self._wake_event.is_set():
                self._wake_event.clear()
                values = self.state.load_config()
                config = read_policy_scheduler_config(values)
                next_run_at = time.time() + min(STARTUP_DELAY_SECONDS, config.interval_seconds)
                self._set_config_status(config, next_run_at=next_run_at)
                continue
            if time.time() < next_run_at:
                continue

            values = self.state.load_config()
            config = read_policy_scheduler_config(values)
            self._set_config_status(config, next_run_at=next_run_at)
            if config.enabled:
                self._schedule_policy(values)
            else:
                self._update_status(
                    last_tick_at=time.time(),
                    skipped_reason="自动策略已关闭",
                    last_error="",
                )
            next_run_at = time.time() + config.interval_seconds
            self._set_config_status(config, next_run_at=next_run_at)

    def _schedule_policy(self, values: dict[str, str]) -> None:
        now = time.time()
        missing = find_missing_policy_config(values)
        if missing:
            self._update_status(
                last_tick_at=now,
                skipped_reason="等待配置：" + ", ".join(missing),
                last_error="",
            )
            return
        try:
            task_id = self.state.tasks.create(
                AUTO_MAINTENANCE_TASK_LABEL,
                run_auto_maintenance,
                self.state,
            )
        except Exception as exc:  # noqa: BLE001
            self._update_status(
                last_tick_at=now,
                last_error=str(exc),
                skipped_reason="提交策略任务失败",
            )
            return
        self._update_status(
            last_tick_at=now,
            last_task_id=task_id,
            last_error="",
            skipped_reason="",
        )

    def _set_config_status(
        self,
        config: PolicySchedulerConfig,
        *,
        next_run_at: float | None,
    ) -> None:
        self._update_status(
            running=True,
            enabled=config.enabled,
            interval_seconds=config.interval_seconds,
            run_on_start=config.run_on_start,
            next_run_at=next_run_at,
        )

    def _update_status(self, **updates: Any) -> None:
        with self._lock:
            self._status.update(updates)
