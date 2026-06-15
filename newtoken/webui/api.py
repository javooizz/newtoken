"""API dispatch and task routing for the WebUI."""

from __future__ import annotations

from typing import Any

import newtoken.acc.seat_client as seat_core
from newtoken.sub2api.converter_core import DEFAULT_OUTPUT_MODE, MAX_CONCURRENT_CHECKS
from newtoken.sub2api.remote import (
    set_all_remote_openai_account_privacy,
    test_sub2api_connection,
)
from newtoken.common.http_client import parse_socks5_proxy_url
from newtoken.webui.acc import (
    apply_acc_payload,
    change_acc_user_seat,
    enforce_acc_low_quota_policy,
    load_acc_members,
)
from newtoken.webui.config import (
    AUTO_POLICY_DEFAULT_INTERVAL_SECONDS,
    AUTO_POLICY_MAX_INTERVAL_SECONDS,
    AUTO_POLICY_MIN_INTERVAL_SECONDS,
    WebState,
)
from newtoken.webui.conversion import import_cached_conversion, run_conversion
from newtoken.webui.oauth import (
    build_oauth_status,
    complete_oauth_manually,
    start_oauth_flow,
)
from newtoken.webui.oidc_client import invalidate_oidc_cache
from newtoken.webui.remote import build_remote_summary, delete_selected_remote_items
from newtoken.webui.utils import parse_positive_int, redact_config

SAVE_CONFIG_KEYS = {
    "SUB2API_BASE_URL",
    "SUB2API_ADMIN_API_KEY",
    "SUB2API_GROUP_IDS",
    "SUB2API_PROXY_ID",
    "SUB2API_OUTBOUND_PROXY_URL",
    "SUB2API_IMPORT_CONCURRENCY",
    "SUB2API_VALIDATE_CONCURRENCY",
    "SUB2API_WEB_PORT",
    "SUB2API_WEB_HOST",
    "SUB2API_WEB_PUBLIC_BASE_URL",
    "SUB2API_AUTO_POLICY_ENABLED",
    "SUB2API_AUTO_POLICY_INTERVAL_SECONDS",
    "SUB2API_AUTO_POLICY_RUN_ON_START",
    "SUB2API_OIDC_API_URL",
    "SUB2API_AUTO_REGISTER_COUNT",
    "SUB2API_AUTO_REGISTER_THRESHOLD",
    "SUB2API_AUTO_REGISTER_DOMAIN",
}


def dispatch_api(path: str, payload: dict[str, Any], state: WebState) -> Any:
    if path == "/api/config/save":
        return save_config_from_payload(state, payload)
    if path == "/api/remote/test":
        return test_sub2api_connection(state.build_remote_config())
    if path == "/api/tasks/start":
        return {"task_id": start_named_task(state, payload)}
    if path == "/api/oauth/start":
        form = {key: str(value or "") for key, value in payload.items()}
        return start_oauth_flow(state, form)
    if path == "/api/oauth/status":
        return build_oauth_status(state)
    if path == "/api/oauth/manual-complete":
        return complete_oauth_manually(state, str(payload.get("auth_input") or ""))
    if path == "/api/acc/apply":
        return apply_acc_payload(state, str(payload.get("payload") or ""))
    if path == "/api/acc/members":
        return load_acc_members(state, str(payload.get("query") or ""))
    if path == "/api/acc/seat":
        seat_type = str(payload.get("seat_type") or "")
        if seat_type != seat_core.CODEX_SEAT_TYPE:
            raise ValueError("当前架构只允许把成员改为 Codex")
        return change_acc_user_seat(
            state,
            str(payload.get("user_id") or ""),
            str(payload.get("email") or ""),
            seat_type,
        )
    raise ValueError("未知接口")


def save_config_from_payload(state: WebState, payload: dict[str, Any]) -> dict[str, str]:
    proxy_url = str(payload.get("SUB2API_OUTBOUND_PROXY_URL") or "").strip()
    if proxy_url:
        parse_socks5_proxy_url(proxy_url)
    validate_web_port(payload)
    normalize_concurrency_fields(payload)
    normalize_scheduler_fields(payload)
    updates = {
        key: str(payload.get(key) or "")
        for key in SAVE_CONFIG_KEYS
        if key in payload
    }
    if "SUB2API_WEB_SECRET" in payload:
        updates["SUB2API_WEB_SECRET"] = str(payload.get("SUB2API_WEB_SECRET") or "")
    if "SUB2API_OIDC_API_KEY" in payload and str(payload.get("SUB2API_OIDC_API_KEY") or ""):
        updates["SUB2API_OIDC_API_KEY"] = str(payload.get("SUB2API_OIDC_API_KEY") or "")
    result = redact_config(state.save_config(updates))
    invalidate_oidc_cache()
    if state.scheduler:
        state.scheduler.wake()
    return result


def validate_web_port(payload: dict[str, Any]) -> None:
    if "SUB2API_WEB_PORT" not in payload:
        return
    raw_port = str(payload.get("SUB2API_WEB_PORT") or "").strip()
    if not raw_port:
        return
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ValueError("WebUI 端口必须是数字") from exc
    if port <= 0 or port > 65535:
        raise ValueError("WebUI 端口范围必须是 1-65535")


def normalize_concurrency_fields(payload: dict[str, Any]) -> None:
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


def normalize_scheduler_fields(payload: dict[str, Any]) -> None:
    interval_key = "SUB2API_AUTO_POLICY_INTERVAL_SECONDS"
    if interval_key in payload:
        raw_interval = str(payload.get(interval_key) or "").strip()
        if raw_interval:
            payload[interval_key] = str(
                parse_positive_int(
                    raw_interval,
                    default=AUTO_POLICY_DEFAULT_INTERVAL_SECONDS,
                    minimum=AUTO_POLICY_MIN_INTERVAL_SECONDS,
                    maximum=AUTO_POLICY_MAX_INTERVAL_SECONDS,
                )
            )
    for bool_key in (
        "SUB2API_AUTO_POLICY_ENABLED",
        "SUB2API_AUTO_POLICY_RUN_ON_START",
    ):
        if bool_key not in payload:
            continue
        raw_value = str(payload.get(bool_key) or "").strip().lower()
        payload[bool_key] = "true" if raw_value in {"1", "true", "yes", "on"} else "false"


def start_named_task(state: WebState, payload: dict[str, Any]) -> str:
    action = str(payload.get("action") or "").strip()
    if action == "remote_scan":
        return state.tasks.create(action, build_remote_summary, state)
    if action == "privacy":
        return state.tasks.create(
            action,
            lambda: set_all_remote_openai_account_privacy(state.build_remote_config()),
        )
    if action == "delete_no_quota":
        return state.tasks.create(action, delete_selected_remote_items, state, "no_quota")
    if action == "delete_auth_error":
        return state.tasks.create(action, delete_selected_remote_items, state, "auth_error")
    if action == "delete_dead":
        return state.tasks.create(action, delete_selected_remote_items, state, "dead")
    if action == "low_quota_policy":
        return state.tasks.create(action, enforce_acc_low_quota_policy, state)
    if action == "auto_maintenance":
        from newtoken.webui.auto import run_auto_maintenance
        return state.tasks.create(action, run_auto_maintenance, state)
    if action == "convert":
        return state.tasks.create(
            action,
            run_conversion,
            str(payload.get("input_path") or ""),
            str(payload.get("output_mode") or DEFAULT_OUTPUT_MODE),
            state,
        )
    if action == "import_cached":
        return state.tasks.create(action, import_cached_conversion, state)
    if action == "import_text":
        return state.tasks.create(
            action,
            import_cached_conversion,
            state,
            str(payload.get("payload_text") or ""),
        )
    raise ValueError("未知任务")
