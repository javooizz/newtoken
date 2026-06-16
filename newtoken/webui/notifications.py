"""PushPlus delivery and deduplicated ACC credential alerts."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

from newtoken.common.http_client import http_request_text

PUSHPLUS_SEND_URL = "https://www.pushplus.plus/send"
PUSHPLUS_TIMEOUT_SECONDS = 10


def is_acc_credential_error(error: BaseException | str) -> bool:
    """Return whether an error indicates expired or missing ACC credentials."""

    text = str(error or "").strip().lower()
    markers = (
        "token_invalidated",
        "token_expired",
        "authentication token has been invalidated",
        "could not validate your token",
        "please try signing in again",
        "缺少 acc access token",
        "缺少 access token 或 session token",
        "缺少 acc account_id",
    )
    return any(marker in text for marker in markers)


def send_pushplus(
    token: str,
    title: str,
    content: str,
) -> dict[str, Any]:
    """Send one PushPlus message and validate its HTTP and business status."""

    normalized_token = str(token or "").strip()
    if not normalized_token:
        raise ValueError("PushPlus Token 未配置")
    status_code, reason, body_text, _headers = http_request_text(
        PUSHPLUS_SEND_URL,
        method="POST",
        json_body={
            "token": normalized_token,
            "title": str(title or "").strip(),
            "content": str(content or "").strip(),
            "template": "txt",
        },
        timeout=PUSHPLUS_TIMEOUT_SECONDS,
    )
    if status_code < 200 or status_code >= 300:
        raise RuntimeError(f"PushPlus HTTP {status_code} {reason}")
    try:
        payload = json.loads(body_text) if body_text else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError("PushPlus 返回的不是合法 JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("PushPlus 返回格式异常")
    if int(payload.get("code", -1) or -1) != 200:
        raise RuntimeError(str(payload.get("msg") or payload.get("message") or "PushPlus 推送失败"))
    return payload


class AccCredentialAlertManager:
    """Persist ACC alert state so repeated scheduler failures send only once."""

    def __init__(
        self,
        state_path: Path,
        *,
        sender: Callable[[str, str, str], Any] = send_pushplus,
    ) -> None:
        self.state_path = state_path
        self.sender = sender
        self._lock = threading.Lock()

    def notify_failure(
        self,
        token: str,
        error_text: str,
        *,
        now: float | None = None,
    ) -> dict[str, Any]:
        timestamp = float(now if now is not None else time.time())
        with self._lock:
            state = self._read_locked()
            if bool(state.get("active")):
                return {"sent": False, "deduplicated": True, "error": ""}
        if not str(token or "").strip():
            return {
                "sent": False,
                "deduplicated": False,
                "error": "PushPlus Token 未配置",
            }
        try:
            self.sender(
                token,
                "ACC 凭证已失效",
                (
                    "Sub2API ACC 自动策略无法继续运行。\n"
                    f"时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))}\n"
                    f"错误：{str(error_text or '').strip()}\n"
                    "请重新保存 ACC JSON / HAR / Session。"
                ),
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "sent": False,
                "deduplicated": False,
                "error": str(exc),
            }
        with self._lock:
            self._write_locked(
                {
                    "active": True,
                    "alerted_at": timestamp,
                    "last_error": str(error_text or "").strip(),
                }
            )
        return {"sent": True, "deduplicated": False, "error": ""}

    def mark_recovered(self, *, now: float | None = None) -> bool:
        timestamp = float(now if now is not None else time.time())
        with self._lock:
            state = self._read_locked()
            if not bool(state.get("active")):
                return False
            state.update(
                {
                    "active": False,
                    "recovered_at": timestamp,
                    "last_error": "",
                }
            )
            self._write_locked(state)
        return True

    def _read_locked(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _write_locked(self, payload: dict[str, Any]) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.state_path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(self.state_path)

