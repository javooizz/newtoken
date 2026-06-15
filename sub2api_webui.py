"""Dependency-light WebUI for Linux deployment."""

from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import secrets
import threading
import time
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import standalone_acc_change_seat_cli as seat_core
from standalone_sub2api_usage_bridge import (
    Sub2APIUsageSnapshot,
    load_sub2api_usage_lookup,
    normalize_email,
    set_remote_accounts_inactive,
)
from sub2api_converter_core import (
    CAP_OUTPUT_MODE,
    DEFAULT_OUTPUT_MODE,
    MAX_CONCURRENT_CHECKS,
    build_cap_result,
    build_export_result,
    calculate_average_remaining_quota,
    collect_account_candidates,
    resolve_input_sources,
    validate_account_candidate,
)
from sub2api_converter_remote import (
    build_remote_config,
    delete_dead_remote_accounts,
    import_to_sub2api_codex_session,
    load_remote_import_defaults,
    mask_secret_value,
    scan_remote_accounts,
    select_remote_accounts_with_auth_error,
    select_remote_accounts_without_quota,
    set_all_remote_openai_account_privacy,
    test_sub2api_connection,
)
from sub2api_converter_remote_openai_oauth import (
    complete_openai_oauth_account_creation,
    create_openai_oauth_pending_session,
    load_openai_oauth_defaults,
    normalize_oauth_concurrency,
)
from sub2api_http_client import (
    apply_proxy_env,
    mask_proxy_url,
    parse_socks5_proxy_url,
)
from sub2api_runtime import get_app_dir

APP_DIR = get_app_dir(__file__)
ENV_PATH = APP_DIR / ".env"
WEB_DEFAULT_PORT = 28463
WEB_DEFAULT_HOST = "0.0.0.0"
MAX_REQUEST_BODY_BYTES = 4 * 1024 * 1024
MAX_WEB_TASK_WORKERS = 4
SESSION_COOKIE_NAME = "sub2api_web_session"
SEAT_ACTIONS = {
    "ChatGPT": "default",
    "Codex": "usage_based",
}
LOW_QUOTA_THRESHOLD_PERCENT = 10.0
WEB_ENV_FIELD_ORDER = [
    "SUB2API_BASE_URL",
    "SUB2API_ADMIN_API_KEY",
    "SUB2API_GROUP_IDS",
    "SUB2API_PROXY_ID",
    "SUB2API_OUTBOUND_PROXY_URL",
    "SUB2API_IMPORT_CONCURRENCY",
    "SUB2API_VALIDATE_CONCURRENCY",
    "SUB2API_IMPORT_PRIORITY",
    "SUB2API_UPDATE_EXISTING",
    "SUB2API_SKIP_DEFAULT_GROUP_BIND",
    "SUB2API_CONFIRM_MIXED_CHANNEL_RISK",
    "SUB2API_OAUTH_REDIRECT_URI",
    "SUB2API_OAUTH_PROXY_ID",
    "SUB2API_OAUTH_PROXY_URL",
    "SUB2API_OAUTH_PROXY_NAME",
    "SUB2API_OAUTH_GROUP_IDS",
    "SUB2API_OAUTH_GROUP_NAME",
    "SUB2API_OAUTH_ACCOUNT_CONCURRENCY",
    "SUB2API_WEB_PORT",
    "SUB2API_WEB_HOST",
    "SUB2API_WEB_SECRET",
    "ACC_MOTHER_ACCOUNT_EMAIL",
    "CHATGPT_RANDOM_EMAIL_DOMAIN",
    "OPENAI_ACCESS_TOKEN",
    "OPENAI_ACCOUNT_ID",
    "OPENAI_DEVICE_ID",
    "OPENAI_SESSION_TOKEN",
    "OPENAI_CLIENT_BUILD_NUMBER",
    "OPENAI_CLIENT_VERSION",
    "OPENAI_BASE_URL",
]
WEB_DEFAULT_ENV_VALUES: dict[str, str] = {
    "SUB2API_BASE_URL": "",
    "SUB2API_ADMIN_API_KEY": "",
    "SUB2API_GROUP_IDS": "",
    "SUB2API_PROXY_ID": "",
    "SUB2API_OUTBOUND_PROXY_URL": "",
    "SUB2API_IMPORT_CONCURRENCY": "50",
    "SUB2API_VALIDATE_CONCURRENCY": "24",
    "SUB2API_IMPORT_PRIORITY": "",
    "SUB2API_UPDATE_EXISTING": "true",
    "SUB2API_SKIP_DEFAULT_GROUP_BIND": "false",
    "SUB2API_CONFIRM_MIXED_CHANNEL_RISK": "false",
    "SUB2API_OAUTH_REDIRECT_URI": "http://localhost:1455/auth/callback",
    "SUB2API_OAUTH_PROXY_ID": "",
    "SUB2API_OAUTH_PROXY_URL": "",
    "SUB2API_OAUTH_PROXY_NAME": "default",
    "SUB2API_OAUTH_GROUP_IDS": "",
    "SUB2API_OAUTH_GROUP_NAME": "cc",
    "SUB2API_OAUTH_ACCOUNT_CONCURRENCY": "10",
    "SUB2API_WEB_PORT": str(WEB_DEFAULT_PORT),
    "SUB2API_WEB_HOST": WEB_DEFAULT_HOST,
    "SUB2API_WEB_SECRET": "",
    "ACC_MOTHER_ACCOUNT_EMAIL": "",
    "CHATGPT_RANDOM_EMAIL_DOMAIN": "example.com",
    "OPENAI_ACCESS_TOKEN": "",
    "OPENAI_ACCOUNT_ID": "",
    "OPENAI_DEVICE_ID": "",
    "OPENAI_SESSION_TOKEN": "",
    "OPENAI_CLIENT_BUILD_NUMBER": seat_core.CLIENT_BUILD_NUMBER,
    "OPENAI_CLIENT_VERSION": seat_core.CLIENT_VERSION,
    "OPENAI_BASE_URL": seat_core.DEFAULT_BASE_URL,
}


def parse_env_value(raw_value: str) -> str:
    """Parse a simple .env value."""

    value = raw_value.strip()
    if not value:
        return ""
    if value.startswith('"') and value.endswith('"'):
        try:
            return str(json.loads(value))
        except json.JSONDecodeError:
            return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    return value


def read_env_file(path: Path) -> dict[str, str]:
    """Read a simple KEY=VALUE .env file without GUI dependencies."""

    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = parse_env_value(value)
    return values


def write_env_file(path: Path, values: dict[str, str]) -> None:
    """Write .env while preserving unknown keys."""

    merged = dict(WEB_DEFAULT_ENV_VALUES)
    merged.update(read_env_file(path))
    merged.update({key: str(value or "") for key, value in values.items()})
    lines = ["# Sub2API WebUI local configuration"]
    written: set[str] = set()
    for key in WEB_ENV_FIELD_ORDER:
        lines.append(f"{key}={json.dumps(merged.get(key, ''), ensure_ascii=False)}")
        written.add(key)
    for key in sorted(merged):
        if key not in written:
            lines.append(f"{key}={json.dumps(merged.get(key, ''), ensure_ascii=False)}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


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
                return
            with self._lock:
                task["status"] = "done"
                task["result"] = result
                task["finished_at"] = time.time()
                self._active_by_label.pop(normalized_label, None)

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


class WebState:
    """Shared runtime state for the WebUI server."""

    def __init__(self, env_path: Path) -> None:
        self.env_path = env_path
        self.tasks = WebTaskStore()
        self.csrf_token = secrets.token_urlsafe(24)
        self.sessions: set[str] = set()
        self.auth_secret = ""
        self.acc_credentials: dict[str, str] = {
            "access_token": "",
            "account_id": "",
            "device_id": "",
            "session_token": "",
            "client_build_number": seat_core.CLIENT_BUILD_NUMBER,
            "client_version": seat_core.CLIENT_VERSION,
            "base_url": seat_core.DEFAULT_BASE_URL,
        }
        self.last_remote_scan: dict[str, Any] | None = None
        self.last_conversion_payload = ""
        self.last_conversion_summary: dict[str, Any] | None = None
        self.last_oauth_session: dict[str, Any] | None = None
        self.last_acc_members: list[dict[str, Any]] = []
        self.last_usage_lookup: dict[str, Any] = {}
        self.load_config()

    def load_config(self) -> dict[str, str]:
        if not self.env_path.exists():
            write_env_file(self.env_path, WEB_DEFAULT_ENV_VALUES)
        values = dict(WEB_DEFAULT_ENV_VALUES)
        values.update(read_env_file(self.env_path))
        self.auth_secret = str(values.get("SUB2API_WEB_SECRET") or "").strip()
        apply_proxy_env(values.get("SUB2API_OUTBOUND_PROXY_URL", ""))
        self._load_acc_credentials(values)
        return values

    def save_config(self, updates: dict[str, str]) -> dict[str, str]:
        values = self.load_config()
        values.update({key: str(value or "") for key, value in updates.items()})
        write_env_file(self.env_path, values)
        return self.load_config()

    def _load_acc_credentials(self, values: dict[str, str]) -> None:
        self.acc_credentials = {
            "access_token": str(values.get("OPENAI_ACCESS_TOKEN") or "").strip(),
            "account_id": str(values.get("OPENAI_ACCOUNT_ID") or "").strip(),
            "device_id": str(values.get("OPENAI_DEVICE_ID") or "").strip(),
            "session_token": str(values.get("OPENAI_SESSION_TOKEN") or "").strip(),
            "client_build_number": (
                str(values.get("OPENAI_CLIENT_BUILD_NUMBER") or "").strip()
                or seat_core.CLIENT_BUILD_NUMBER
            ),
            "client_version": (
                str(values.get("OPENAI_CLIENT_VERSION") or "").strip()
                or seat_core.CLIENT_VERSION
            ),
            "base_url": (
                str(values.get("OPENAI_BASE_URL") or "").strip()
                or seat_core.DEFAULT_BASE_URL
            ),
        }

    def build_remote_config(self):
        defaults = load_remote_import_defaults(str(self.env_path))
        return build_remote_config(
            defaults.get("base_url", ""),
            defaults.get("admin_api_key", ""),
            group_ids_text=defaults.get("group_ids", ""),
            proxy_id_text=defaults.get("proxy_id", ""),
            concurrency_text=defaults.get("concurrency", ""),
            priority_text=defaults.get("priority", ""),
            update_existing=defaults.get("update_existing", True),
            skip_default_group_bind=defaults.get("skip_default_group_bind", False),
            confirm_mixed_channel_risk=defaults.get(
                "confirm_mixed_channel_risk",
                False,
            ),
        )

    def build_seat_client(self) -> seat_core.SeatClient:
        creds = self.acc_credentials
        config = seat_core.Config(
            access_token=creds["access_token"],
            account_id=creds["account_id"],
            device_id=creds["device_id"],
            session_token=creds["session_token"],
            client_build_number=creds["client_build_number"] or seat_core.CLIENT_BUILD_NUMBER,
            client_version=creds["client_version"] or seat_core.CLIENT_VERSION,
            base_url=seat_core.normalize_base_url(
                creds["base_url"] or seat_core.DEFAULT_BASE_URL
            ),
        )
        if not config.access_token and not config.session_token:
            raise SeatApiWebError("缺少 ACC access token 或 session token")
        if not config.account_id:
            raise SeatApiWebError("缺少 ACC account_id")
        return seat_core.SeatClient(config)


class SeatApiWebError(RuntimeError):
    """WebUI-facing ACC error."""


def build_acc_env_values(
    access_token: str,
    account_id: str,
    device_id: str,
    session_token: str,
    client_build_number: str,
    client_version: str,
    base_url: str,
) -> dict[str, str]:
    """Build .env values for the ACC seat client without importing Tk UI."""

    return {
        "OPENAI_ACCESS_TOKEN": access_token.strip(),
        "OPENAI_ACCOUNT_ID": account_id.strip(),
        "OPENAI_DEVICE_ID": device_id.strip(),
        "OPENAI_SESSION_TOKEN": session_token.strip(),
        "OPENAI_CLIENT_BUILD_NUMBER": (
            client_build_number.strip() or seat_core.CLIENT_BUILD_NUMBER
        ),
        "OPENAI_CLIENT_VERSION": (
            client_version.strip() or seat_core.CLIENT_VERSION
        ),
        "OPENAI_BASE_URL": seat_core.normalize_base_url(
            base_url.strip() or seat_core.DEFAULT_BASE_URL
        ),
    }


def parse_acc_import_payload(raw_text: str) -> dict[str, str]:
    """Parse ACC JSON/HAR/token input without importing the Tkinter module."""

    text = raw_text.strip()
    if not text:
        raise SeatApiWebError("导入内容为空")

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None

    if isinstance(data, dict):
        if isinstance(data.get("log"), dict):
            return seat_core.parse_har_session_bundle(text)
        account_data = data.get("account") if isinstance(data.get("account"), dict) else {}
        payload = {
            "warningBanner": str(data.get("WARNING_BANNER") or "").strip(),
            "accountId": str(account_data.get("id") or data.get("account_id") or "").strip(),
            "deviceId": str(
                data.get("deviceId")
                or data.get("device_id")
                or data.get("oai-did")
                or data.get("oaiDid")
                or data.get("did")
                or ""
            ).strip(),
            "accessToken": str(data.get("accessToken") or "").strip(),
            "sessionToken": str(data.get("sessionToken") or "").strip(),
            "authProvider": str(data.get("authProvider") or "").strip(),
            "clientBuildNumber": str(data.get("clientBuildNumber") or "").strip(),
            "clientVersion": str(data.get("clientVersion") or "").strip(),
        }
        if payload["accessToken"] or payload["sessionToken"]:
            return payload

    split_marker = '\",\"authProvider\"'
    split_index = text.find(split_marker)
    if split_index != -1:
        access_token = text[:split_index].strip().strip('"').strip()
        suffix = "{" + text[split_index + 2 :]
        try:
            suffix_data = json.loads(suffix)
        except json.JSONDecodeError as exc:
            raise SeatApiWebError("导入数据尾部 JSON 不完整") from exc
        payload = {
            "warningBanner": "",
            "accountId": "",
            "deviceId": "",
            "accessToken": access_token,
            "sessionToken": str(suffix_data.get("sessionToken") or "").strip(),
            "authProvider": str(suffix_data.get("authProvider") or "").strip(),
            "clientBuildNumber": "",
            "clientVersion": "",
        }
        if payload["accessToken"] or payload["sessionToken"]:
            return payload

    if text.count(".") >= 2 and '"sessionToken"' not in text:
        return {
            "warningBanner": "",
            "accountId": "",
            "deviceId": "",
            "accessToken": text,
            "sessionToken": "",
            "authProvider": "",
            "clientBuildNumber": "",
            "clientVersion": "",
        }

    raise SeatApiWebError("无法识别导入格式")


def redact_config(values: dict[str, str]) -> dict[str, str]:
    """Return config values safe enough for display."""

    result = dict(values)
    for key in (
        "SUB2API_ADMIN_API_KEY",
        "OPENAI_ACCESS_TOKEN",
        "OPENAI_SESSION_TOKEN",
        "OPENAI_DEVICE_ID",
        "SUB2API_WEB_SECRET",
    ):
        if result.get(key):
            result[f"{key}_MASKED"] = mask_secret_value(result[key])
    proxy_url = result.get("SUB2API_OUTBOUND_PROXY_URL", "")
    result["SUB2API_OUTBOUND_PROXY_URL_MASKED"] = mask_proxy_url(proxy_url)
    return result


def html_escape(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def json_safe(value: Any) -> Any:
    """Convert common dataclass-ish values into JSON serializable objects."""

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return json_safe(asdict(value))
    return str(value)


def parse_positive_int(value: Any, default: int, *, minimum: int = 1, maximum: int = 200) -> int:
    """Parse bounded positive int values from config or form text."""

    try:
        parsed = int(str(value or "").strip())
    except (TypeError, ValueError):
        return int(default)
    return max(int(minimum), min(int(maximum), parsed))


def build_remote_summary(state: WebState) -> dict[str, Any]:
    config = state.build_remote_config()
    result = scan_remote_accounts(config)
    state.last_remote_scan = result
    return result


def delete_selected_remote_items(state: WebState, selector: str) -> dict[str, Any]:
    if not state.last_remote_scan:
        raise RuntimeError("请先刷新远程账号状态")
    if selector == "no_quota":
        items = select_remote_accounts_without_quota(
            state.last_remote_scan.get("no_quota_items")
            or state.last_remote_scan.get("dead_items")
            or []
        )
    elif selector == "auth_error":
        items = select_remote_accounts_with_auth_error(
            state.last_remote_scan.get("dead_items") or []
        )
    else:
        items = state.last_remote_scan.get("dead_items") or []
    if not items:
        return {"deleted": 0, "failed": 0, "items": []}
    return delete_dead_remote_accounts(state.build_remote_config(), items)


def run_conversion(input_path: str, output_mode: str, state: WebState) -> dict[str, Any]:
    values = state.load_config()
    input_sources = resolve_input_sources(input_path)
    candidates, skipped_duplicates = collect_account_candidates(input_sources)
    counts = {"auth_error": 0, "quota_error": 0, "other_error": 0}
    usable_results = []
    validate_concurrency = parse_positive_int(
        values.get("SUB2API_VALIDATE_CONCURRENCY"),
        default=min(MAX_CONCURRENT_CHECKS, 24),
        maximum=MAX_CONCURRENT_CHECKS,
    )

    if candidates:
        worker_count = min(validate_concurrency, len(candidates))
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [
                executor.submit(validate_account_candidate, candidate)
                for candidate in candidates
            ]
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result.status == "ok":
                    usable_results.append(result)
                elif result.status in counts:
                    counts[result.status] += 1
                else:
                    counts["other_error"] += 1

    usable_accounts = [
        result.account
        for result in sorted(usable_results, key=lambda item: item.order)
        if result.account is not None
    ]
    payload = (
        build_cap_result(usable_accounts)
        if output_mode == CAP_OUTPUT_MODE
        else build_export_result(usable_accounts)
    )
    payload_text = json.dumps(payload, ensure_ascii=False, indent=2)
    summary = {
        "source_count": len(input_sources),
        "total_candidates": len(candidates),
        "skipped_duplicates": skipped_duplicates,
        "usable_count": len(usable_accounts),
        "average_remaining_quota": calculate_average_remaining_quota(usable_results),
        "auth_error_count": counts["auth_error"],
        "quota_error_count": counts["quota_error"],
        "other_error_count": counts["other_error"],
        "output_mode": output_mode,
        "validate_concurrency": validate_concurrency,
    }
    state.last_conversion_payload = payload_text
    state.last_conversion_summary = summary
    return summary


def import_cached_conversion(state: WebState, payload_text: str | None = None) -> dict[str, Any]:
    payload = payload_text if payload_text is not None else state.last_conversion_payload
    if not payload:
        raise RuntimeError("没有可导入的缓存结果，请先转换或粘贴 JSON")
    return import_to_sub2api_codex_session(state.build_remote_config(), payload)


def load_acc_members(state: WebState, query: str = "") -> dict[str, Any]:
    client = state.build_seat_client()
    normalized_query = str(query or "").strip()
    all_users = seat_core.list_all_users(client, query="")
    limit_result = seat_core.enforce_chatgpt_seat_limit(
        client,
        users=all_users,
        limit=seat_core.CHATGPT_SEAT_LIMIT,
    )
    all_users = list(limit_result.get("users") or all_users)
    if normalized_query:
        users = seat_core.list_all_users(client, query=normalized_query)
    else:
        users = all_users
    state.last_acc_members = users
    return {
        "items": users,
        "total": len(users),
        "chatgpt_count": seat_core.count_chatgpt_seats(all_users),
        "chatgpt_limit": seat_core.CHATGPT_SEAT_LIMIT,
        "limit_changed_members": limit_result.get("changed_users") or [],
    }


def is_low_quota_snapshot(
    snapshot: Sub2APIUsageSnapshot,
    *,
    threshold_percent: float = LOW_QUOTA_THRESHOLD_PERCENT,
) -> bool:
    """Return True when any tracked quota window is below threshold."""

    values = [
        snapshot.quota_5h_remaining_percent,
        snapshot.quota_7d_remaining_percent,
    ]
    known_values = [float(value) for value in values if value is not None]
    if not known_values:
        return False
    return any(value < threshold_percent for value in known_values)


def enforce_acc_low_quota_policy(state: WebState) -> dict[str, Any]:
    """Disable low-quota calls, force matched users to Codex, and cap ChatGPT seats."""

    usage_result = load_sub2api_usage_lookup(state.env_path)
    state.last_usage_lookup = dict(usage_result.lookup)
    client = state.build_seat_client()
    users = seat_core.list_all_users(client)
    users_by_email = {
        normalize_email(user.get("email")): user
        for user in users
        if normalize_email(user.get("email"))
    }
    low_items = [
        snapshot
        for snapshot in usage_result.lookup.values()
        if is_low_quota_snapshot(snapshot)
    ]
    low_remote_ids = sorted(
        {
            int(snapshot.account_id)
            for snapshot in low_items
            if int(snapshot.account_id or 0) > 0
            and str(snapshot.account_status or "").lower() != "inactive"
        }
    )
    disabled_result = set_remote_accounts_inactive(low_remote_ids, env_path=state.env_path)
    changed_members: list[dict[str, Any]] = []
    skipped_members: list[dict[str, Any]] = []
    for snapshot in low_items:
        user = users_by_email.get(normalize_email(snapshot.email))
        if not user:
            skipped_members.append(
                {
                    "email": snapshot.email,
                    "reason": "ACC 成员未匹配",
                    "account_id": snapshot.account_id,
                }
            )
            continue
        if seat_core.is_codex_seat_type(user.get("seat_type")):
            skipped_members.append(
                {
                    "email": snapshot.email,
                    "reason": "已是 Codex",
                    "account_id": snapshot.account_id,
                }
            )
            continue
        result = seat_core.ensure_user_seat(
            client,
            user_id=str(user.get("id", "")),
            email=None,
            target_seat_type=seat_core.CODEX_SEAT_TYPE,
        )
        changed_members.append(
            {
                "email": snapshot.email,
                "account_id": snapshot.account_id,
                "quota_5h": snapshot.quota_5h_text,
                "quota_7d": snapshot.quota_7d_text,
                "seat_result": result,
            }
        )
    after_low_quota_users = seat_core.list_all_users(client)
    limit_result = seat_core.enforce_chatgpt_seat_limit(
        client,
        users=after_low_quota_users,
        limit=seat_core.CHATGPT_SEAT_LIMIT,
    )
    refreshed_users = limit_result["users"]
    state.last_acc_members = refreshed_users
    return {
        "threshold_percent": LOW_QUOTA_THRESHOLD_PERCENT,
        "remote_total": usage_result.remote_total,
        "low_quota_count": len(low_items),
        "disabled_remote_ids": low_remote_ids,
        "disabled_result": disabled_result,
        "changed_members": changed_members,
        "skipped_members": skipped_members,
        "limit_changed_members": limit_result.get("changed_users") or [],
        "limit_overflow_count": limit_result.get("overflow_count", 0),
        "members": refreshed_users,
        "chatgpt_count": seat_core.count_chatgpt_seats(refreshed_users),
        "chatgpt_limit": seat_core.CHATGPT_SEAT_LIMIT,
    }


def refresh_acc_usage(state: WebState) -> dict[str, Any]:
    result = load_sub2api_usage_lookup(state.env_path)
    state.last_usage_lookup = dict(result.lookup)
    matched = 0
    for user in state.last_acc_members:
        email = str(user.get("email") or "").strip().lower()
        if email and email in state.last_usage_lookup:
            matched += 1
    return {
        "config_path": result.config_path,
        "remote_total": result.remote_total,
        "matched": matched,
        "member_total": len(state.last_acc_members),
        "items": [
            {
                "email": item.email,
                "quota_5h": item.quota_5h_text,
                "quota_7d": item.quota_7d_text,
                "status": item.account_status,
                "account_id": item.account_id,
            }
            for item in result.lookup.values()
        ],
    }


def change_acc_user_seat(state: WebState, user_id: str, email: str, seat_type: str) -> dict[str, Any]:
    client = state.build_seat_client()
    result = seat_core.ensure_user_seat(
        client,
        user_id=user_id or None,
        email=email or None,
        target_seat_type=seat_type,
    )
    users = load_acc_members(state).get("items", [])
    return {"seat_result": result, "members": users}


def apply_acc_payload(state: WebState, raw_text: str) -> dict[str, Any]:
    payload = parse_acc_import_payload(raw_text)
    current_values = state.load_config()
    base_url = (
        str(current_values.get("OPENAI_BASE_URL") or "").strip()
        or seat_core.DEFAULT_BASE_URL
    )
    credentials = build_acc_env_values(
        payload.get("accessToken", ""),
        payload.get("accountId", ""),
        payload.get("deviceId", ""),
        payload.get("sessionToken", ""),
        payload.get("clientBuildNumber", ""),
        payload.get("clientVersion", ""),
        base_url,
    )
    if payload.get("sessionToken"):
        session_data = seat_core.fetch_session_info(
            base_url,
            payload["sessionToken"],
        )
        access_token, account_id = seat_core.extract_session_credentials(session_data)
        credentials["OPENAI_ACCESS_TOKEN"] = access_token
        credentials["OPENAI_ACCOUNT_ID"] = account_id
    state.save_config(credentials)
    return {"saved": True, "account_id": credentials.get("OPENAI_ACCOUNT_ID", "")}


def create_oauth_session(state: WebState, form: dict[str, str]) -> dict[str, Any]:
    defaults = load_openai_oauth_defaults(str(state.env_path))
    group_ids_text = form.get("group_ids") or defaults.get("group_ids", "")
    group_ids = []
    for part in group_ids_text.split(","):
        text = part.strip()
        if text:
            group_ids.append(int(text))
    result = create_openai_oauth_pending_session(
        base_url=form.get("base_url") or defaults.get("base_url", ""),
        admin_api_key=form.get("admin_api_key") or defaults.get("admin_api_key", ""),
        proxy_id=form.get("proxy_id") or defaults.get("proxy_id", ""),
        proxy_url=form.get("proxy_url") or defaults.get("proxy_url", ""),
        proxy_name=form.get("proxy_name") or defaults.get("proxy_name", "default"),
        redirect_uri=form.get("redirect_uri") or defaults.get("redirect_uri", ""),
        account_name=form.get("account_name") or "",
        group_ids=group_ids,
        group_name=form.get("group_name") or defaults.get("group_name", "cc"),
        concurrency=normalize_oauth_concurrency(
            form.get("concurrency") or defaults.get("concurrency", "")
        ),
    )
    pending = result["pending_session"]
    state.last_oauth_session = {
        "remote_config": result["remote_config"],
        "pending_session": pending,
    }
    return {
        "auth_url": pending.auth_url,
        "session_id": pending.session_id,
        "state": pending.state,
        "account_name": pending.account_name,
        "proxy_name": pending.proxy_name,
        "proxy_id": pending.proxy_id,
        "group_ids": pending.group_ids,
    }


def complete_oauth_session(state: WebState, auth_input: str) -> dict[str, Any]:
    if not state.last_oauth_session:
        raise RuntimeError("请先生成 OAuth 授权链接")
    return complete_openai_oauth_account_creation(
        remote_config=state.last_oauth_session["remote_config"],
        pending_session=state.last_oauth_session["pending_session"],
        auth_input=auth_input,
    )


def build_index_html(values: dict[str, str], state: WebState) -> str:
    config = redact_config(values)
    proxy_status = "未配置"
    proxy_url = values.get("SUB2API_OUTBOUND_PROXY_URL", "")
    if proxy_url:
        try:
            parse_socks5_proxy_url(proxy_url)
            proxy_status = f"已配置 {mask_proxy_url(proxy_url)}"
        except Exception as exc:  # noqa: BLE001
            proxy_status = f"配置错误：{exc}"
    port = html_escape(values.get("SUB2API_WEB_PORT") or WEB_DEFAULT_PORT)
    csrf = html_escape(state.csrf_token)
    remote_base = html_escape(values.get("SUB2API_BASE_URL", ""))
    api_key_placeholder = (
        "已保存，输入新值替换"
        if values.get("SUB2API_ADMIN_API_KEY")
        else ""
    )
    group_ids = html_escape(values.get("SUB2API_GROUP_IDS", ""))
    proxy_id = html_escape(values.get("SUB2API_PROXY_ID", ""))
    outbound_proxy = html_escape(values.get("SUB2API_OUTBOUND_PROXY_URL", ""))
    validate_concurrency = html_escape(values.get("SUB2API_VALIDATE_CONCURRENCY", "24"))
    import_concurrency = html_escape(values.get("SUB2API_IMPORT_CONCURRENCY", "50"))
    oauth_defaults = load_openai_oauth_defaults(str(state.env_path))
    styles = """
    :root {
      --bg: #eef2f6;
      --surface: #ffffff;
      --surface-2: #f8fafc;
      --line: #d7dee8;
      --text: #17202f;
      --muted: #647083;
      --brand: #0f766e;
      --brand-2: #115e59;
      --blue: #22577a;
      --warn: #9a3412;
      --danger: #b42318;
      --ok: #087443;
      --shadow: 0 16px 34px rgba(22, 31, 45, .08);
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body { margin: 0; font-family: system-ui, -apple-system, Segoe UI, sans-serif; background: var(--bg); color: var(--text); }
    button, input, textarea, select { font: inherit; }
    button { border: 0; border-radius: 6px; background: var(--brand); color: white; padding: 9px 12px; cursor: pointer; min-height: 36px; }
    button:hover { background: var(--brand-2); }
    button.secondary { background: var(--blue); }
    button.warn { background: var(--warn); }
    button.danger { background: var(--danger); }
    button.ghost { background: transparent; color: var(--text); border: 1px solid var(--line); }
    button:disabled { opacity: .58; cursor: wait; }
    input, textarea, select { width: 100%; border: 1px solid var(--line); border-radius: 6px; background: white; color: var(--text); padding: 9px 10px; outline: none; }
    input:focus, textarea:focus, select:focus { border-color: var(--brand); box-shadow: 0 0 0 3px rgba(15, 118, 110, .12); }
    textarea { min-height: 132px; resize: vertical; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 13px; line-height: 1.45; }
    label { display: block; color: var(--muted); font-size: 12px; margin-bottom: 5px; }
    .app { min-height: 100vh; display: grid; grid-template-columns: 236px minmax(0, 1fr); }
    aside { position: sticky; top: 0; height: 100vh; padding: 18px; background: #162334; color: white; }
    .brand { font-size: 18px; font-weight: 750; margin-bottom: 4px; }
    .sub { color: #cbd5e1; font-size: 12px; line-height: 1.5; overflow-wrap: anywhere; }
    nav { display: grid; gap: 6px; margin-top: 22px; }
    nav a { color: #e5edf6; text-decoration: none; padding: 9px 10px; border-radius: 6px; font-size: 14px; }
    nav a:hover { background: rgba(255, 255, 255, .1); }
    main { min-width: 0; padding: 22px; }
    .topbar { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
    h1 { font-size: 24px; margin: 0 0 4px; letter-spacing: 0; }
    h2 { font-size: 17px; margin: 0; letter-spacing: 0; }
    h3 { font-size: 14px; margin: 0 0 10px; }
    .meta { color: var(--muted); font-size: 13px; }
    .status { color: var(--muted); font-size: 13px; min-height: 20px; }
    .ok { color: var(--ok); }
    .bad { color: var(--danger); }
    .band { background: var(--surface); border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); padding: 16px; margin-bottom: 14px; box-shadow: var(--shadow); }
    .section-head { display: flex; justify-content: space-between; gap: 12px; align-items: center; margin-bottom: 12px; }
    .grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
    .grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-bottom: 14px; }
    .stat { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 12px; min-height: 82px; }
    .stat b { display: block; font-size: 24px; line-height: 1.1; margin-top: 7px; }
    .row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
    .toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 12px; }
    .split { display: grid; grid-template-columns: minmax(0, 1fr) minmax(320px, .65fr); gap: 14px; }
    .table-wrap { overflow: auto; max-height: 460px; border: 1px solid var(--line); border-radius: 8px; background: white; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { border-bottom: 1px solid var(--line); padding: 8px 9px; text-align: left; vertical-align: top; }
    th { position: sticky; top: 0; background: var(--surface-2); color: var(--muted); z-index: 1; font-weight: 700; }
    tr:last-child td { border-bottom: 0; }
    .pill { display: inline-flex; align-items: center; gap: 5px; border: 1px solid var(--line); border-radius: 999px; padding: 3px 8px; background: var(--surface-2); color: var(--muted); font-size: 12px; }
    .mono { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; overflow-wrap: anywhere; }
    .mini { font-size: 12px; color: var(--muted); }
    .compact { max-width: 160px; }
    .task-list { display: grid; gap: 8px; }
    .task { border: 1px solid var(--line); border-radius: 8px; background: white; padding: 10px; display: grid; grid-template-columns: 1fr auto; gap: 8px; }
    .task strong { font-size: 13px; }
    .task small { color: var(--muted); }
    .empty { color: var(--muted); padding: 14px; border: 1px dashed var(--line); border-radius: 8px; background: var(--surface-2); }
    @media (max-width: 1080px) {
      .app { grid-template-columns: 1fr; }
      aside { position: static; height: auto; }
      nav { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .grid, .grid.two, .stats, .split { grid-template-columns: 1fr; }
      main { padding: 14px; }
    }
    """
    scripts = """
const csrf = document.getElementById('csrf').value;
let polling = new Set();
const actionStatus = {
  remote_scan: 'remote_status',
  privacy: 'remote_status',
  delete_no_quota: 'remote_status',
  delete_auth_error: 'remote_status',
  delete_dead: 'remote_status',
  low_quota_policy: 'acc_status',
  convert: 'convert_status',
  import_cached: 'convert_status',
  import_text: 'convert_status'
};
const actionNames = {
  remote_scan: '远程扫描',
  privacy: '隐私同步',
  delete_no_quota: '删除无额度',
  delete_auth_error: '删除 401',
  delete_dead: '删除死号',
  low_quota_policy: '席位策略',
  convert: '转换校验',
  import_cached: '缓存导入',
  import_text: '粘贴导入'
};
function byId(id) { return document.getElementById(id); }
function formValue(id) { const el = byId(id); return el ? el.value.trim() : ''; }
function setText(id, text, bad=false) {
  const el = byId(id);
  if (!el) return;
  el.textContent = text || '';
  el.className = bad ? 'status bad' : 'status ok';
}
function setStat(id, value) {
  const el = byId(id);
  if (el) el.textContent = value ?? '--';
}
function setBusy(action, busy) {
  document.querySelectorAll(`[data-action="${action}"]`).forEach(button => {
    button.disabled = Boolean(busy);
  });
}
async function api(path, body={}) {
  const res = await fetch(path, {
    method: 'POST',
    headers: {'Content-Type':'application/json', 'X-CSRF-Token': csrf},
    body: JSON.stringify(body)
  });
  const data = await res.json();
  if (!res.ok || data.ok === false) throw new Error(data.error || res.statusText);
  return data;
}
async function saveConfig() {
  try {
    const config = {
      SUB2API_BASE_URL: formValue('cfg_base_url'),
      SUB2API_GROUP_IDS: formValue('cfg_group_ids'),
      SUB2API_PROXY_ID: formValue('cfg_proxy_id'),
      SUB2API_OUTBOUND_PROXY_URL: formValue('cfg_outbound_proxy'),
      SUB2API_IMPORT_CONCURRENCY: formValue('cfg_import_concurrency'),
      SUB2API_VALIDATE_CONCURRENCY: formValue('cfg_validate_concurrency'),
      SUB2API_WEB_PORT: formValue('cfg_web_port'),
      SUB2API_WEB_HOST: formValue('cfg_web_host')
    };
    const adminApiKey = formValue('cfg_api_key');
    if (adminApiKey) config.SUB2API_ADMIN_API_KEY = adminApiKey;
    const webSecret = formValue('cfg_web_secret');
    if (webSecret) config.SUB2API_WEB_SECRET = webSecret;
    await api('/api/config/save', config);
    setText('config_status', '配置已保存');
    setStat('stat_proxy', formValue('cfg_outbound_proxy') ? '已配置' : '未配置');
  } catch(e) { setText('config_status', e.message, true); }
}
async function testRemote() {
  try {
    const data = await api('/api/remote/test', {});
    setText('config_status', 'Sub2API 连接成功');
    setStat('stat_remote', data.result.account_total ?? 'OK');
  } catch(e) { setText('config_status', e.message, true); }
}
async function startTask(action) {
  const body = {
    action,
    input_path: formValue('convert_input_path'),
    output_mode: formValue('convert_output_mode'),
    payload_text: byId('import_json_text').value
  };
  const statusId = actionStatus[action] || 'task_status';
  try {
    setBusy(action, true);
    setText(statusId, `${actionNames[action] || action} 已提交`);
    const data = await api('/api/tasks/start', body);
    pollTask(data.task_id, action);
    loadTasks();
  } catch(e) {
    setBusy(action, false);
    setText(statusId, e.message, true);
  }
}
function confirmTask(action, message) { if (confirm(message)) startTask(action); }
async function pollTask(id, action='') {
  if (polling.has(id)) return;
  polling.add(id);
  while (true) {
    const res = await fetch('/api/tasks/get?id=' + encodeURIComponent(id));
    const task = await res.json();
    if (task.status !== 'running' && task.status !== 'queued') {
      polling.delete(id);
      setBusy(action || task.label, false);
      renderTaskResult(task);
      loadTasks();
      return;
    }
    await new Promise(r => setTimeout(r, 900));
  }
}
function renderTaskResult(task) {
  const statusId = actionStatus[task.label] || 'task_status';
  if (task.status === 'error') {
    setText(statusId, `${actionNames[task.label] || task.label} 失败：${task.error}`, true);
    return;
  }
  const result = task.result || {};
  if (task.label === 'remote_scan') renderRemoteSummary(result);
  if (task.label === 'convert') {
    setText('convert_status', `转换完成：可用 ${result.usable_count}/${result.total_candidates}，并发 ${result.validate_concurrency}`);
    setStat('stat_convert', result.usable_count ?? 0);
  }
  if (task.label.startsWith('delete')) {
    setText('remote_status', `${actionNames[task.label]} 完成`);
    startTask('remote_scan');
  }
  if (task.label === 'privacy') setText('remote_status', '隐私同步完成');
  if (task.label.startsWith('import')) setText('convert_status', '导入完成');
  if (task.label === 'low_quota_policy') {
    renderMembers(result.members || []);
    const changed = (result.changed_members || []).length;
    const capped = (result.limit_changed_members || []).length;
    setText('acc_status', `策略完成：低额度 ${result.low_quota_count}，改 Codex ${changed + capped}，ChatGPT ${result.chatgpt_count}/${result.chatgpt_limit}`);
    setStat('stat_chatgpt', `${result.chatgpt_count}/${result.chatgpt_limit}`);
    setStat('stat_low', result.low_quota_count ?? 0);
  }
}
function renderRemoteSummary(r) {
  setText('remote_status', `远程 ${r.total_count} | 活 ${r.alive_count} | 死 ${r.dead_count} | 无额度 ${r.no_quota_count} | 均额 ${r.average_remaining_quota}%`);
  setStat('stat_remote', r.total_count ?? 0);
  setStat('stat_dead', r.dead_count ?? 0);
  const rows = (r.dead_items || []).concat(r.no_quota_items || []).slice(0, 120).map(item =>
    `<tr><td class="mono">${esc(item.account_id)}</td><td>${esc(item.name)}</td><td>${esc(item.email)}</td><td>${esc(item.status)}</td><td>${esc(item.reason)}</td></tr>`
  ).join('');
  byId('remote_summary').innerHTML = rows
    ? `<div class="table-wrap"><table><thead><tr><th>ID</th><th>账号</th><th>邮箱</th><th>状态</th><th>原因</th></tr></thead><tbody>${rows}</tbody></table></div>`
    : '<div class="empty">没有需要展示的异常账号</div>';
}
function esc(v) { return String(v ?? '').replace(/[&<>"']/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s])); }
async function createOauth() {
  try {
    const data = await api('/api/oauth/create', {
      account_name: formValue('oauth_account_name'),
      redirect_uri: formValue('oauth_redirect_uri'),
      proxy_id: formValue('oauth_proxy_id'),
      proxy_url: formValue('oauth_proxy_url'),
      group_ids: formValue('oauth_group_ids'),
      group_name: formValue('oauth_group_name'),
      concurrency: formValue('oauth_concurrency')
    });
    byId('oauth_auth_url').value = data.result.auth_url;
    setText('oauth_status', '授权链接已生成');
  } catch(e) { setText('oauth_status', e.message, true); }
}
async function completeOauth() {
  try {
    const data = await api('/api/oauth/complete', {auth_input: formValue('oauth_auth_input')});
    setText('oauth_status', '建号完成 #' + data.result.account_id);
  } catch(e) { setText('oauth_status', e.message, true); }
}
async function copyCachedPayload() {
  const res = await fetch('/api/conversion/payload');
  const data = await res.json();
  await navigator.clipboard.writeText(data.payload || '');
  setText('convert_status', '缓存 JSON 已复制');
}
async function applyAcc() {
  try {
    const data = await api('/api/acc/apply', {payload: byId('acc_payload').value});
    setText('acc_status', 'ACC 已保存 account_id=' + data.result.account_id);
  } catch(e) { setText('acc_status', e.message, true); }
}
async function loadMembers() {
  try {
    const data = await api('/api/acc/members', {});
    renderMembers(data.result.items || []);
    setText('acc_status', '已加载成员 ' + data.result.total);
  } catch(e) { setText('acc_status', e.message, true); }
}
function seatName(seatType) {
  const text = String(seatType || '');
  if (text === 'usage_based') return 'Codex';
  if (text === 'default' || text === 'null') return 'ChatGPT';
  return text || '--';
}
function renderMembers(items) {
  const chatgptCount = items.filter(u => ['default', 'null'].includes(String(u.seat_type || ''))).length;
  setStat('stat_chatgpt', `${chatgptCount}/2`);
  const rows = items.map(u => {
    const seat = seatName(u.seat_type);
    const isCodex = seat === 'Codex';
    return `<tr><td class="mono">${esc(u.id)}</td><td>${esc(u.email)}</td><td><span class="pill">${esc(seat)}</span></td><td><button class="secondary seat-action" ${isCodex ? 'disabled' : ''} data-user-id="${esc(u.id)}">改 Codex</button></td></tr>`;
  }).join('');
  byId('acc_members').innerHTML = rows
    ? `<div class="table-wrap"><table><thead><tr><th>User ID</th><th>邮箱</th><th>席位</th><th>操作</th></tr></thead><tbody>${rows}</tbody></table></div>`
    : '<div class="empty">暂无成员数据</div>';
  document.querySelectorAll('.seat-action').forEach(button => {
    button.addEventListener('click', () => seat(button.dataset.userId || '', '', 'usage_based'));
  });
}
async function seat(user_id, email, seat_type) {
  try {
    const data = await api('/api/acc/seat', {user_id, email, seat_type});
    renderMembers(data.result.members || []);
    setText('acc_status', '席位已更新');
  } catch(e) { setText('acc_status', e.message, true); }
}
function formatTaskTime(task) {
  const started = Number(task.started_at || task.created_at || 0) * 1000;
  const finished = Number(task.finished_at || 0) * 1000;
  if (!started) return '--';
  if (!finished) return '运行中';
  return Math.max(0, Math.round((finished - started) / 1000)) + 's';
}
async function loadTasks() {
  const res = await fetch('/api/tasks/list');
  const data = await res.json();
  const tasks = data.tasks || [];
  if (!tasks.length) {
    byId('task_log').innerHTML = '<div class="empty">暂无任务</div>';
    return;
  }
  byId('task_log').innerHTML = '<div class="task-list">' + tasks.slice(0, 12).map(task => {
    const summary = Object.entries(task.result_summary || {}).map(([k, v]) => `${k}:${v}`).join(' ');
    return `<div class="task"><div><strong>${esc(actionNames[task.label] || task.label)}</strong><br><small>${esc(summary || task.error || task.id)}</small></div><div><span class="pill">${esc(task.status)}</span><br><small>${formatTaskTime(task)}</small></div></div>`;
  }).join('') + '</div>';
}
loadTasks();
setInterval(loadTasks, 6000);
"""
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sub2API 控制台</title>
  <style>{styles}</style>
</head>
<body>
<div class="app">
  <aside>
    <div class="brand">Sub2API 控制台</div>
    <div class="sub">端口 {port}<br>SOCKS5: {html_escape(proxy_status)}</div>
    <nav>
      <a href="#overview">总览</a>
      <a href="#acc">ACC 策略</a>
      <a href="#remote">远程账号</a>
      <a href="#import">导入</a>
      <a href="#oauth">OAuth</a>
      <a href="#config">配置</a>
    </nav>
  </aside>
  <main>
    <input id="csrf" type="hidden" value="{csrf}">
    <div class="topbar" id="overview">
      <div>
        <h1>运行总览</h1>
        <div class="meta mono">{html_escape(str(state.env_path))}</div>
      </div>
      <div class="row"><button class="ghost" onclick="loadTasks()">刷新任务</button></div>
    </div>
    <div class="stats">
      <div class="stat"><span class="meta">ChatGPT 席位</span><b id="stat_chatgpt">--/2</b><span class="mini">硬限制 2</span></div>
      <div class="stat"><span class="meta">低额度账号</span><b id="stat_low">--</b><span class="mini">阈值 {LOW_QUOTA_THRESHOLD_PERCENT:g}%</span></div>
      <div class="stat"><span class="meta">远程账号</span><b id="stat_remote">--</b><span class="mini">Sub2API OAuth</span></div>
      <div class="stat"><span class="meta">异常账号</span><b id="stat_dead">--</b><span class="mini">死号 / 无额度</span></div>
    </div>

    <section class="band" id="acc">
      <div class="section-head">
        <div><h2>ACC 策略</h2><div class="meta">Codex 不回 ChatGPT，ChatGPT 总数收敛到 2 以内</div></div>
        <span id="acc_status" class="status"></span>
      </div>
      <div class="split">
        <div>
          <label>ACC JSON / HAR / Session</label>
          <textarea id="acc_payload"></textarea>
          <div class="toolbar">
            <button onclick="applyAcc()">保存 ACC</button>
            <button class="secondary" onclick="loadMembers()">加载成员</button>
            <button class="warn" data-action="low_quota_policy" onclick="startTask('low_quota_policy')">执行策略</button>
          </div>
        </div>
        <div id="acc_members"><div class="empty">等待加载成员</div></div>
      </div>
    </section>

    <section class="band" id="remote">
      <div class="section-head">
        <div><h2>远程账号</h2><div class="meta">状态扫描、隐私同步和异常清理</div></div>
        <span id="remote_status" class="status"></span>
      </div>
      <div class="toolbar">
        <button data-action="remote_scan" onclick="startTask('remote_scan')">扫描状态</button>
        <button class="secondary" data-action="privacy" onclick="startTask('privacy')">同步隐私</button>
        <button class="danger" data-action="delete_auth_error" onclick="confirmTask('delete_auth_error', '删除所有 401/认证失效账号？')">删 401</button>
        <button class="danger" data-action="delete_no_quota" onclick="confirmTask('delete_no_quota', '删除所有无额度账号？')">删无额度</button>
        <button class="danger" data-action="delete_dead" onclick="confirmTask('delete_dead', '删除全部死号？')">删死号</button>
      </div>
      <div id="remote_summary" style="margin-top:12px"><div class="empty">等待扫描</div></div>
    </section>

    <section class="band" id="import">
      <div class="section-head">
        <div><h2>转换与导入</h2><div class="meta">本地账号校验、缓存 JSON、上传 Sub2API</div></div>
        <span id="convert_status" class="status"></span>
      </div>
      <div class="grid">
        <div><label>Linux 路径</label><input id="convert_input_path" placeholder="/www/wwwroot/accounts"></div>
        <div><label>目标格式</label><select id="convert_output_mode"><option value="{DEFAULT_OUTPUT_MODE}">Sub</option><option value="{CAP_OUTPUT_MODE}">CAP</option></select></div>
        <div><label>校验并发</label><input id="cfg_validate_concurrency" value="{validate_concurrency}"></div>
        <div><label>导入并发</label><input id="cfg_import_concurrency" value="{import_concurrency}"></div>
      </div>
      <div class="toolbar">
        <button data-action="convert" onclick="startTask('convert')">转换校验</button>
        <button class="ghost" onclick="copyCachedPayload()">复制缓存</button>
        <button data-action="import_cached" onclick="startTask('import_cached')">上传缓存</button>
      </div>
      <div style="margin-top:12px">
        <label>粘贴 JSON 上传</label>
        <textarea id="import_json_text"></textarea>
        <div class="toolbar"><button data-action="import_text" onclick="startTask('import_text')">上传粘贴内容</button></div>
      </div>
    </section>

    <section class="band" id="oauth">
      <div class="section-head">
        <div><h2>OAuth 建号</h2><div class="meta">生成授权链接并导入 Sub2API</div></div>
        <span id="oauth_status" class="status"></span>
      </div>
      <div class="grid">
        <div><label>账号名</label><input id="oauth_account_name"></div>
        <div><label>回调地址</label><input id="oauth_redirect_uri" value="{html_escape(oauth_defaults.get('redirect_uri', ''))}"></div>
        <div><label>远程代理 ID</label><input id="oauth_proxy_id" value="{html_escape(oauth_defaults.get('proxy_id', ''))}"></div>
        <div><label>备用代理 URL</label><input id="oauth_proxy_url" value="{html_escape(oauth_defaults.get('proxy_url', ''))}"></div>
        <div><label>分组 ID</label><input id="oauth_group_ids" value="{html_escape(oauth_defaults.get('group_ids', ''))}"></div>
        <div><label>分组名</label><input id="oauth_group_name" value="{html_escape(oauth_defaults.get('group_name', 'cc'))}"></div>
        <div><label>账号并发</label><input id="oauth_concurrency" value="{html_escape(oauth_defaults.get('concurrency', '10'))}"></div>
      </div>
      <div class="toolbar">
        <button onclick="createOauth()">生成授权链接</button>
        <button class="secondary" onclick="completeOauth()">完成建号</button>
      </div>
      <div class="grid two" style="margin-top:12px">
        <div><label>授权链接</label><input id="oauth_auth_url" readonly></div>
        <div><label>回调链接或 Code</label><input id="oauth_auth_input"></div>
      </div>
    </section>

    <section class="band" id="config">
      <div class="section-head">
        <div><h2>运行配置</h2><div class="meta">保存后端、代理、端口和 Web 密码</div></div>
        <span id="config_status" class="status"></span>
      </div>
      <div class="grid">
        <div><label>Sub2API 地址</label><input id="cfg_base_url" value="{remote_base}"></div>
        <div><label>管理员 API Key</label><input id="cfg_api_key" value="" type="password" placeholder="{html_escape(api_key_placeholder)}"></div>
        <div><label>默认分组 ID</label><input id="cfg_group_ids" value="{group_ids}"></div>
        <div><label>Sub2API 代理 ID</label><input id="cfg_proxy_id" value="{proxy_id}"></div>
        <div><label>SOCKS5 出站代理</label><input id="cfg_outbound_proxy" value="{outbound_proxy}" placeholder="socks5://127.0.0.1:1080"></div>
        <div><label>Web 端口</label><input id="cfg_web_port" value="{port}"></div>
        <div><label>Web Host</label><input id="cfg_web_host" value="{html_escape(values.get('SUB2API_WEB_HOST') or WEB_DEFAULT_HOST)}"></div>
        <div><label>Web 密码</label><input id="cfg_web_secret" value="" type="password" placeholder="留空不修改"></div>
      </div>
      <div class="toolbar">
        <button onclick="saveConfig()">保存配置</button>
        <button class="secondary" onclick="testRemote()">测试连接</button>
        <span class="pill">API {html_escape(config.get('SUB2API_ADMIN_API_KEY_MASKED', '-') or '-')}</span>
        <span class="pill" id="stat_proxy">代理 {html_escape(config.get('SUB2API_OUTBOUND_PROXY_URL_MASKED', '-') or '-')}</span>
      </div>
    </section>

    <section class="band" id="tasks">
      <div class="section-head">
        <div><h2>任务</h2><div class="meta">后台任务队列最多并发 {MAX_WEB_TASK_WORKERS}</div></div>
        <span id="task_status" class="status"></span>
      </div>
      <div id="task_log"><div class="empty">暂无任务</div></div>
    </section>
  </main>
</div>
<script>{scripts}</script>
</body>
</html>"""


class WebUIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the WebUI."""

    server_version = "Sub2APIWebUI/1.0"

    @property
    def state(self) -> WebState:
        return self.server.state  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args) -> None:
        print(f"[WEBUI] {self.address_string()} {fmt % args}")

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/login":
            self._send_html(self._build_login_html())
            return
        if path == "/api/tasks/get":
            if not self._is_authorized():
                self._send_json({"ok": False, "error": "unauthorized"}, status=401)
                return
            task_id = parse_qs(urlsplit(self.path).query).get("id", [""])[0]
            task = self.state.tasks.get(task_id)
            self._send_json(task or {"status": "missing"}, status=200)
            return
        if path == "/api/tasks/list":
            if not self._is_authorized():
                self._send_json({"ok": False, "error": "unauthorized"}, status=401)
                return
            self._send_json({"tasks": self.state.tasks.list_recent()})
            return
        if path == "/api/conversion/payload":
            if not self._is_authorized():
                self._send_json({"ok": False, "error": "unauthorized"}, status=401)
                return
            self._send_json({"payload": self.state.last_conversion_payload})
            return
        if path in {"/", "/index.html"}:
            if not self._is_authorized():
                self._redirect("/login")
                return
            values = self.state.load_config()
            self._send_html(build_index_html(values, self.state))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path == "/login":
            self._handle_login()
            return
        if not self._is_authorized():
            self._send_json({"ok": False, "error": "unauthorized"}, status=401)
            return
        if not self._check_csrf():
            self._send_json({"ok": False, "error": "CSRF token 无效"}, status=403)
            return
        try:
            payload = self._read_json_body()
            result = self._route_api(path, payload)
            self._send_json({"ok": True, "result": json_safe(result)})
        except Exception as exc:  # noqa: BLE001
            self._send_json({"ok": False, "error": str(exc)}, status=400)

    def _route_api(self, path: str, payload: dict[str, Any]) -> Any:
        if path == "/api/config/save":
            proxy_url = str(payload.get("SUB2API_OUTBOUND_PROXY_URL") or "").strip()
            if proxy_url:
                parse_socks5_proxy_url(proxy_url)
            if "SUB2API_WEB_PORT" in payload:
                raw_port = str(payload.get("SUB2API_WEB_PORT") or "").strip()
                if raw_port:
                    try:
                        port = int(raw_port)
                    except ValueError as exc:
                        raise ValueError("WebUI 端口必须是数字") from exc
                    if port <= 0 or port > 65535:
                        raise ValueError("WebUI 端口范围必须是 1-65535")
            for concurrency_key in (
                "SUB2API_IMPORT_CONCURRENCY",
                "SUB2API_VALIDATE_CONCURRENCY",
            ):
                if concurrency_key not in payload:
                    continue
                raw_concurrency = str(payload.get(concurrency_key) or "").strip()
                if not raw_concurrency:
                    continue
                concurrency_value = parse_positive_int(
                    raw_concurrency,
                    default=24,
                    maximum=MAX_CONCURRENT_CHECKS,
                )
                payload[concurrency_key] = str(concurrency_value)
            allowed_keys = {
                "SUB2API_BASE_URL",
                "SUB2API_ADMIN_API_KEY",
                "SUB2API_GROUP_IDS",
                "SUB2API_PROXY_ID",
                "SUB2API_OUTBOUND_PROXY_URL",
                "SUB2API_IMPORT_CONCURRENCY",
                "SUB2API_VALIDATE_CONCURRENCY",
                "SUB2API_WEB_PORT",
                "SUB2API_WEB_HOST",
            }
            updates = {
                key: str(payload.get(key) or "")
                for key in allowed_keys
                if key in payload
            }
            if "SUB2API_WEB_SECRET" in payload:
                updates["SUB2API_WEB_SECRET"] = str(
                    payload.get("SUB2API_WEB_SECRET") or ""
                )
            return redact_config(self.state.save_config(updates))
        if path == "/api/remote/test":
            return test_sub2api_connection(self.state.build_remote_config())
        if path == "/api/tasks/start":
            return {"task_id": self._start_named_task(payload)}
        if path == "/api/oauth/create":
            form = {key: str(value or "") for key, value in payload.items()}
            return create_oauth_session(self.state, form)
        if path == "/api/oauth/complete":
            return complete_oauth_session(self.state, str(payload.get("auth_input") or ""))
        if path == "/api/acc/apply":
            return apply_acc_payload(self.state, str(payload.get("payload") or ""))
        if path == "/api/acc/members":
            return load_acc_members(self.state, str(payload.get("query") or ""))
        if path == "/api/acc/seat":
            seat_type = str(payload.get("seat_type") or "")
            if seat_type != seat_core.CODEX_SEAT_TYPE:
                raise ValueError("当前架构只允许把成员改为 Codex")
            return change_acc_user_seat(
                self.state,
                str(payload.get("user_id") or ""),
                str(payload.get("email") or ""),
                seat_type,
            )
        raise ValueError("未知接口")

    def _start_named_task(self, payload: dict[str, Any]) -> str:
        action = str(payload.get("action") or "").strip()
        if action == "remote_scan":
            return self.state.tasks.create(action, build_remote_summary, self.state)
        if action == "privacy":
            return self.state.tasks.create(
                action,
                lambda: set_all_remote_openai_account_privacy(self.state.build_remote_config()),
            )
        if action == "delete_no_quota":
            return self.state.tasks.create(action, delete_selected_remote_items, self.state, "no_quota")
        if action == "delete_auth_error":
            return self.state.tasks.create(action, delete_selected_remote_items, self.state, "auth_error")
        if action == "delete_dead":
            return self.state.tasks.create(action, delete_selected_remote_items, self.state, "dead")
        if action == "low_quota_policy":
            return self.state.tasks.create(action, enforce_acc_low_quota_policy, self.state)
        if action == "convert":
            return self.state.tasks.create(
                action,
                run_conversion,
                str(payload.get("input_path") or ""),
                str(payload.get("output_mode") or DEFAULT_OUTPUT_MODE),
                self.state,
            )
        if action == "import_cached":
            return self.state.tasks.create(action, import_cached_conversion, self.state)
        if action == "import_text":
            return self.state.tasks.create(
                action,
                import_cached_conversion,
                self.state,
                str(payload.get("payload_text") or ""),
            )
        raise ValueError("未知任务")

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_REQUEST_BODY_BYTES:
            raise ValueError("请求体过大")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("请求不是合法 JSON") from exc
        if not isinstance(data, dict):
            raise ValueError("请求 JSON 必须是对象")
        return data

    def _send_json(self, payload: Any, *, status: int = 200) -> None:
        body = json.dumps(json_safe(payload), ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, body_text: str, *, status: int = 200) -> None:
        body = body_text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    def _is_authorized(self) -> bool:
        if not self.state.auth_secret:
            return True
        cookie = self.headers.get("Cookie", "")
        sessions = {}
        for part in cookie.split(";"):
            if "=" not in part:
                continue
            key, value = part.strip().split("=", 1)
            sessions[key] = value
        return sessions.get(SESSION_COOKIE_NAME) in self.state.sessions

    def _check_csrf(self) -> bool:
        return self.headers.get("X-CSRF-Token", "") == self.state.csrf_token

    def _handle_login(self) -> None:
        payload = self._read_form_body()
        password = str(payload.get("password", "")).strip()
        if not self.state.auth_secret or secrets.compare_digest(password, self.state.auth_secret):
            session_id = secrets.token_urlsafe(24)
            self.state.sessions.add(session_id)
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", f"{SESSION_COOKIE_NAME}={session_id}; HttpOnly; SameSite=Lax; Path=/")
            self.end_headers()
            return
        self._send_html(self._build_login_html("密码错误"), status=401)

    def _read_form_body(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
        return {key: values[0] if values else "" for key, values in parsed.items()}

    def _build_login_html(self, error_message: str = "") -> str:
        err = f"<p class='bad'>{html_escape(error_message)}</p>" if error_message else ""
        return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>登录</title>
<style>body{{font-family:system-ui;margin:0;background:#f7f8fa;color:#172033}}main{{max-width:420px;margin:14vh auto;background:white;border:1px solid #d8dde6;border-radius:8px;padding:22px}}input,button{{width:100%;padding:10px;margin-top:8px;font:inherit}}button{{background:#0f766e;color:white;border:0;border-radius:6px}}.bad{{color:#b42318}}</style></head>
<body><main><h1>Sub2API WebUI</h1>{err}<form method="post" action="/login"><label>Web 密码</label><input name="password" type="password" autofocus><button>登录</button></form></main></body></html>"""


class Sub2APIWebServer(ThreadingHTTPServer):
    """ThreadingHTTPServer carrying WebState."""

    daemon_threads = True

    def __init__(self, server_address, handler_class, state: WebState):
        super().__init__(server_address, handler_class)
        self.state = state


def resolve_server_bind(args: argparse.Namespace, values: dict[str, str]) -> tuple[str, int]:
    host = str(args.host or values.get("SUB2API_WEB_HOST") or WEB_DEFAULT_HOST).strip()
    raw_port = str(args.port or values.get("SUB2API_WEB_PORT") or WEB_DEFAULT_PORT).strip()
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("WebUI 端口必须是数字") from exc
    if port <= 0 or port > 65535:
        raise ValueError("WebUI 端口范围必须是 1-65535")
    return host, port


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sub2API Linux WebUI")
    parser.add_argument("--host", default="", help="监听地址，默认读取 .env 的 SUB2API_WEB_HOST")
    parser.add_argument("--port", default="", help="监听端口，默认读取 .env 的 SUB2API_WEB_PORT")
    parser.add_argument("--env", default="", help="指定 .env 路径")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env_path = Path(args.env).resolve() if args.env else ENV_PATH
    state = WebState(env_path)
    values = state.load_config()
    host, port = resolve_server_bind(args, values)
    server = Sub2APIWebServer((host, port), WebUIHandler, state)
    print(f"Sub2API WebUI listening on http://{host}:{port}")
    if values.get("SUB2API_OUTBOUND_PROXY_URL"):
        print(f"Outbound proxy: {mask_proxy_url(values.get('SUB2API_OUTBOUND_PROXY_URL'))}")
    if not state.auth_secret:
        print("Warning: SUB2API_WEB_SECRET is empty; WebUI has no password.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping Sub2API WebUI...")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
