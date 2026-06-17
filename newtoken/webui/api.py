"""API dispatch and task routing for the WebUI."""

from __future__ import annotations

from typing import Any

import newtoken.acc.seat_client as seat_core
from newtoken.common.http_client import parse_socks5_proxy_url
from newtoken.sub2api.converter_core import DEFAULT_OUTPUT_MODE, MAX_CONCURRENT_CHECKS
from newtoken.sub2api.remote import (
    build_remote_config,
    fetch_remote_groups,
    set_all_remote_openai_account_privacy,
    test_sub2api_connection,
)
from newtoken.sub2api.remote_oauth import fetch_remote_proxies
from newtoken.webui.acc import (
    apply_acc_payload,
    change_acc_user_seat,
    load_acc_members,
    normalize_backend_email_template,
    parse_backend_email_start_index,
)
from newtoken.webui.config import (
    AUTO_POLICY_DEFAULT_INTERVAL_SECONDS,
    AUTO_POLICY_MAX_INTERVAL_SECONDS,
    AUTO_POLICY_MIN_INTERVAL_SECONDS,
    WebState,
)
from newtoken.webui.conversion import import_cached_conversion, run_conversion
from newtoken.webui.oidc_client import oidc_status
from newtoken.webui.oauth import (
    build_oauth_status,
    complete_oauth_manually,
    start_blind_oauth_import,
    start_oauth_flow,
)
from newtoken.webui.remote import build_remote_summary, delete_selected_remote_items
from newtoken.webui.policy_runner import run_observed_policy
from newtoken.webui.utils import parse_positive_int, redact_config


SAVE_CONFIG_KEYS = {
    "SUB2API_BASE_URL",
    "SUB2API_ADMIN_API_KEY",
    "SUB2API_GROUP_IDS",
    "SUB2API_PROXY_ID",
    "SUB2API_OUTBOUND_PROXY_URL",
    "SUB2API_VALIDATE_CONCURRENCY",
    "SUB2API_WEB_PORT",
    "SUB2API_WEB_HOST",
    "SUB2API_WEB_PUBLIC_BASE_URL",
    "SUB2API_AUTO_POLICY_ENABLED",
    "SUB2API_AUTO_POLICY_INTERVAL_SECONDS",
    "SUB2API_AUTO_POLICY_RUN_ON_START",
    "ACC_BACKEND_EMAIL_TEMPLATE",
    "ACC_BACKEND_EMAIL_START_INDEX",
    "PUSHPLUS_TOKEN",
}


def dispatch_api(path: str, payload: dict[str, Any], state: WebState) -> Any:
    if path == "/api/config/save":
        return save_config_from_payload(state, payload)
    if path == "/api/policy/events":
        limit = parse_positive_int(
            payload.get("limit"),
            default=100,
            maximum=300,
        )
        items = state.policy_events.list_recent(limit)
        return {"items": items, "total": len(items)}
    if path == "/api/remote/test":
        return test_sub2api_connection(state.build_remote_config())
    if path == "/api/remote/resources":
        return load_remote_resources(state, payload)
    if path == "/api/oidc/test":
        return oidc_status(state.load_config())
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
            raise ValueError("当前开源版只允许手动把成员改为 Codex")
        return change_acc_user_seat(
            state,
            str(payload.get("user_id") or ""),
            str(payload.get("email") or ""),
            seat_type,
        )
    raise ValueError("未知接口")


def load_remote_resources(state: WebState, payload: dict[str, Any]) -> dict[str, Any]:
    values = state.load_config()
    base_url = str(payload.get("base_url") or values.get("SUB2API_BASE_URL") or "").strip()
    admin_api_key = str(payload.get("admin_api_key") or values.get("SUB2API_ADMIN_API_KEY") or "").strip()
    if not base_url or not admin_api_key:
        raise ValueError("请先填写 Sub2API 地址和管理员 API Key")
    updates: dict[str, str] = {}
    if base_url and base_url != str(values.get("SUB2API_BASE_URL") or "").strip():
        updates["SUB2API_BASE_URL"] = base_url
    if admin_api_key and admin_api_key != str(values.get("SUB2API_ADMIN_API_KEY") or "").strip():
        updates["SUB2API_ADMIN_API_KEY"] = admin_api_key
    if updates:
        values = state.save_config(updates)
    config = build_remote_config(base_url, admin_api_key)
    return {
        "groups": build_group_options(fetch_remote_groups(config)),
        "proxies": build_proxy_options(fetch_remote_proxies(config)),
    }


def build_group_options(groups: list[dict[str, Any]]) -> list[dict[str, str]]:
    options = [{"value": "", "label": "不绑定分组"}]
    for item in groups:
        if not isinstance(item, dict):
            continue
        try:
            group_id = int(item.get("id", 0) or 0)
        except (TypeError, ValueError):
            group_id = 0
        if group_id <= 0:
            continue
        platform = str(item.get("platform", "")).strip().lower()
        if platform and platform != "openai":
            continue
        name = str(item.get("name", "")).strip() or f"group-{group_id}"
        label = f"{name} (#{group_id} | {platform or '-'})"
        options.append({"value": str(group_id), "label": label})
    return options


def build_proxy_options(proxies: list[dict[str, Any]]) -> list[dict[str, str]]:
    options = [{"value": "", "label": "留空自动使用账号配置"}]
    for item in proxies:
        if not isinstance(item, dict):
            continue
        try:
            proxy_id = int(item.get("id", 0) or 0)
        except (TypeError, ValueError):
            proxy_id = 0
        if proxy_id <= 0:
            continue
        name = str(item.get("name", "")).strip() or "default"
        protocol = str(item.get("protocol", "")).strip().lower()
        host = str(item.get("host", "")).strip()
        port = str(item.get("port", "")).strip()
        location = f"{protocol}://{host}:{port}" if protocol and host and port else "地址未知"
        label = f"{name} (#{proxy_id} | {location})"
        options.append({"value": str(proxy_id), "label": label})
    return options


def save_config_from_payload(state: WebState, payload: dict[str, Any]) -> dict[str, str]:
    proxy_url = str(payload.get("SUB2API_OUTBOUND_PROXY_URL") or "").strip()
    if proxy_url:
        parse_socks5_proxy_url(proxy_url)
    validate_web_port(payload)
    validate_backend_email_pool(payload)
    normalize_concurrency_fields(payload)
    normalize_scheduler_fields(payload)
    updates = {
        key: str(payload.get(key) or "")
        for key in SAVE_CONFIG_KEYS
        if key in payload
    }
    if "SUB2API_WEB_SECRET" in payload:
        updates["SUB2API_WEB_SECRET"] = str(payload.get("SUB2API_WEB_SECRET") or "")
    result = redact_config(state.save_config(updates))
    if state.scheduler:
        state.scheduler.wake()
    return result


def validate_backend_email_pool(payload: dict[str, Any]) -> None:
    if "ACC_BACKEND_EMAIL_TEMPLATE" in payload:
        payload["ACC_BACKEND_EMAIL_TEMPLATE"] = normalize_backend_email_template(
            str(payload.get("ACC_BACKEND_EMAIL_TEMPLATE") or "")
        )
    if "ACC_BACKEND_EMAIL_START_INDEX" in payload:
        payload["ACC_BACKEND_EMAIL_START_INDEX"] = str(
            parse_backend_email_start_index(
                payload.get("ACC_BACKEND_EMAIL_START_INDEX")
            )
        )


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
    payload["SUB2API_IMPORT_CONCURRENCY"] = "5"
    for concurrency_key in ("SUB2API_VALIDATE_CONCURRENCY",):
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
    if action == "oauth_blind_import":
        if state.tasks.has_active(action):
            raise ValueError("当前已有一键建号任务正在运行，请等上一条结束后再试")
        form = {key: str(value or "") for key, value in payload.items()}
        return state.tasks.create(
            action,
            start_blind_oauth_import,
            state,
            form,
            task_logger_param="_task_logger",
        )
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
        return state.tasks.create(action, run_observed_policy, state)
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
