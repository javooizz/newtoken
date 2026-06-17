"""ACC 席位工具与 Sub2API 远程额度的桥接能力。"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

LOCAL_PROJECT_DIR = Path(__file__).resolve().parent
if str(LOCAL_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(LOCAL_PROJECT_DIR))

from newtoken.common.runtime import ensure_on_sys_path, get_app_dir  # noqa: E402

PROJECT_DIR = get_app_dir(__file__)
STANDALONE_DIR = get_app_dir(__file__)
ensure_on_sys_path(PROJECT_DIR)
ensure_on_sys_path(STANDALONE_DIR)

from newtoken.sub2api.remote import (  # noqa: E402
    build_remote_error_message,
    build_remote_config,
    build_sub2api_admin_headers,
    build_sub2api_admin_url,
    bulk_update_remote_accounts,
    fetch_remote_account_list,
    load_remote_import_defaults,
    unwrap_sub2api_response,
)
from newtoken.sub2api.converter_core import request_json  # noqa: E402

LOCAL_ENV_PATH = STANDALONE_DIR / ".env"
PROJECT_ENV_PATH = PROJECT_DIR / ".env"
SUB2API_BATCH_REFRESH_PATH = "/api/v1/admin/accounts/batch-refresh"
SUB2API_SINGLE_REFRESH_PATH_TEMPLATE = "/api/v1/admin/accounts/{account_id}/refresh"
SUB2API_RECOVER_STATE_PATH_TEMPLATE = "/api/v1/admin/accounts/{account_id}/recover-state"


@dataclass
class Sub2APIUsageSnapshot:
    """保存单个 Sub2API 账号的额度快照。"""

    account_id: int
    name: str
    email: str
    quota_5h_text: str
    quota_7d_text: str
    usage_updated_at: str
    quota_31d_text: str = "--"
    quota_5h_remaining_percent: float | None = None
    quota_7d_remaining_percent: float | None = None
    quota_31d_remaining_percent: float | None = None
    account_status: str = ""
    quota_5h_reset_at: str = ""
    quota_7d_reset_at: str = ""
    quota_31d_reset_at: str = ""
    quota_5h_reset_after_seconds: int | None = None
    quota_7d_reset_after_seconds: int | None = None
    quota_31d_reset_after_seconds: int | None = None


@dataclass
class Sub2APIUsageLoadResult:
    """保存一次远程额度读取结果。"""

    config_path: str
    remote_total: int
    lookup: dict[str, Sub2APIUsageSnapshot]
    summaries: list[Sub2APIRemoteAccountSummary]


@dataclass
class Sub2APIRemoteAccountSummary:
    """保存账号管理表所需的远程账号摘要。"""

    account_id: int
    email: str
    name: str
    plan_type: str
    status: str


def normalize_email(value: str | None) -> str:
    """把邮箱压成稳定匹配键。"""

    return str(value or "").strip().lower()


def parse_optional_percent(raw_value: Any) -> float | None:
    """把远程接口中的百分比安全转成 float。"""

    if raw_value in (None, ""):
        return None
    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return None


def parse_optional_int(raw_value: Any) -> int | None:
    """把可选整数安全转成 int。"""

    if raw_value in (None, ""):
        return None
    try:
        return int(float(raw_value))
    except (TypeError, ValueError):
        return None


def normalize_remote_account_ids(
    account_ids: list[int] | tuple[int, ...],
) -> list[int]:
    """把远程账号 ID 规整成去重后的正整数列表。"""

    normalized_ids: list[int] = []
    seen_ids: set[int] = set()
    for account_id in (account_ids or []):
        normalized_id = parse_optional_int(account_id)
        if normalized_id is None or normalized_id <= 0 or normalized_id in seen_ids:
            continue
        seen_ids.add(normalized_id)
        normalized_ids.append(normalized_id)
    normalized_ids.sort()
    return normalized_ids


def parse_optional_datetime(raw_value: Any) -> datetime | None:
    """把 Sub2API 返回的时间字符串安全解析成 datetime。"""

    text = str(raw_value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        local_tz = datetime.now().astimezone().tzinfo or timezone.utc
        parsed = parsed.replace(tzinfo=local_tz)
    return parsed


def format_remaining_quota_text(raw_used_percent: Any) -> str:
    """把已用百分比转成剩余百分比文本。"""

    used_percent = parse_optional_percent(raw_used_percent)
    if used_percent is None:
        return "--"
    remaining_percent = max(0.0, 100.0 - used_percent)
    return f"剩{remaining_percent:.2f}%"


def calculate_remaining_percent(raw_used_percent: Any) -> float | None:
    """把已用百分比转换成剩余额度百分比。"""

    used_percent = parse_optional_percent(raw_used_percent)
    if used_percent is None:
        return None
    return max(0.0, 100.0 - used_percent)


def format_reset_eta_text(
    reset_at: str | None,
    reset_after_seconds: int | None,
    *,
    now: datetime | None = None,
) -> str:
    """把额度刷新时间格式化成“还剩多久”。"""

    current_time = now or datetime.now(timezone.utc)
    target_time = parse_optional_datetime(reset_at)
    remaining_seconds: int | None = None
    if target_time is not None:
        remaining_seconds = max(
            0,
            int((target_time.astimezone(timezone.utc) - current_time).total_seconds()),
        )
    elif reset_after_seconds is not None:
        remaining_seconds = max(0, int(reset_after_seconds))
        target_time = current_time + timedelta(seconds=remaining_seconds)
    if remaining_seconds is None:
        return "--"
    if remaining_seconds <= 0:
        return "已刷新"

    days, remainder = divmod(remaining_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days > 0:
        return f"{days}天{hours}小时"
    if hours > 0:
        return f"{hours}小时{minutes}分"
    if minutes > 0:
        return f"{minutes}分{seconds}秒"
    return f"{seconds}秒"


def extract_remote_plan_type(account_item: dict[str, Any]) -> str:
    """从远程账号项里尽量提取账号类型。"""

    if not isinstance(account_item, dict):
        return "--"
    credentials = account_item.get("credentials") or {}
    extra = account_item.get("extra") or {}
    if not isinstance(credentials, dict):
        credentials = {}
    if not isinstance(extra, dict):
        extra = {}
    for raw_value in (
        credentials.get("chatgpt_plan_type"),
        extra.get("chatgpt_plan_type"),
        credentials.get("plan_type"),
        extra.get("plan_type"),
        extra.get("subscription_plan"),
        extra.get("account_type"),
        extra.get("openai_account_type"),
    ):
        text = str(raw_value or "").strip().lower()
        if text:
            return text
    return "--"


def extract_remote_account_summary(
    account_item: dict[str, Any],
) -> Sub2APIRemoteAccountSummary | None:
    """从远程账号项里提取账号管理摘要。"""

    snapshot = extract_snapshot_from_account_item(account_item)
    if snapshot is None:
        return None
    return Sub2APIRemoteAccountSummary(
        account_id=snapshot.account_id,
        email=snapshot.email,
        name=snapshot.name,
        plan_type=extract_remote_plan_type(account_item),
        status=snapshot.account_status or "--",
    )


def extract_snapshot_from_account_item(account_item: dict[str, Any]) -> Sub2APIUsageSnapshot | None:
    """从远程账号列表项中提取可展示的额度快照。"""

    if not isinstance(account_item, dict):
        return None
    credentials = account_item.get("credentials") or {}
    extra = account_item.get("extra") or {}
    if not isinstance(credentials, dict) or not isinstance(extra, dict):
        return None
    email = normalize_email(credentials.get("email") or extra.get("email"))
    if not email:
        return None
    try:
        account_id = int(account_item.get("id", 0) or 0)
    except (TypeError, ValueError):
        account_id = 0
    quota_31d_used_percent = None
    quota_31d_reset_at = ""
    quota_31d_reset_after_seconds = None
    for used_percent_key, reset_at_key, reset_after_key in (
        ("codex_31d_used_percent", "codex_31d_reset_at", "codex_31d_reset_after_seconds"),
        ("codex_30d_used_percent", "codex_30d_reset_at", "codex_30d_reset_after_seconds"),
        ("codex_month_used_percent", "codex_month_reset_at", "codex_month_reset_after_seconds"),
        ("codex_monthly_used_percent", "codex_monthly_reset_at", "codex_monthly_reset_after_seconds"),
    ):
        if extra.get(used_percent_key) in (None, ""):
            continue
        quota_31d_used_percent = extra.get(used_percent_key)
        quota_31d_reset_at = str(extra.get(reset_at_key) or "").strip()
        quota_31d_reset_after_seconds = parse_optional_int(extra.get(reset_after_key))
        break
    return Sub2APIUsageSnapshot(
        account_id=account_id,
        name=str(account_item.get("name", "")).strip(),
        email=email,
        quota_5h_text=format_remaining_quota_text(
            extra.get("codex_5h_used_percent")
        ),
        quota_7d_text=format_remaining_quota_text(
            extra.get("codex_7d_used_percent")
        ),
        quota_31d_text=format_remaining_quota_text(quota_31d_used_percent),
        usage_updated_at=str(extra.get("codex_usage_updated_at") or "").strip(),
        quota_5h_remaining_percent=calculate_remaining_percent(
            extra.get("codex_5h_used_percent")
        ),
        quota_7d_remaining_percent=calculate_remaining_percent(
            extra.get("codex_7d_used_percent")
        ),
        quota_31d_remaining_percent=calculate_remaining_percent(quota_31d_used_percent),
        account_status=str(account_item.get("status") or "").strip().lower(),
        quota_5h_reset_at=str(extra.get("codex_5h_reset_at") or "").strip(),
        quota_7d_reset_at=str(extra.get("codex_7d_reset_at") or "").strip(),
        quota_31d_reset_at=quota_31d_reset_at,
        quota_5h_reset_after_seconds=parse_optional_int(
            extra.get("codex_5h_reset_after_seconds")
        ),
        quota_7d_reset_after_seconds=parse_optional_int(
            extra.get("codex_7d_reset_after_seconds")
        ),
        quota_31d_reset_after_seconds=quota_31d_reset_after_seconds,
    )


def load_available_remote_config(env_path: str | Path | None = None):
    """从指定 .env、独立工具目录或项目根目录读取可用的 Sub2API 远程配置。"""

    candidate_paths = [Path(env_path)] if env_path else [LOCAL_ENV_PATH, PROJECT_ENV_PATH]
    for candidate_path in candidate_paths:
        remote_defaults = load_remote_import_defaults(str(candidate_path))
        if not remote_defaults.get("base_url") or not remote_defaults.get("admin_api_key"):
            continue
        return (
            build_remote_config(
                base_url=remote_defaults["base_url"],
                admin_api_key=remote_defaults["admin_api_key"],
                group_ids_text=remote_defaults.get("group_ids", ""),
                proxy_id_text=remote_defaults.get("proxy_id", ""),
                concurrency_text=remote_defaults.get("concurrency", ""),
                priority_text=remote_defaults.get("priority", ""),
                update_existing=remote_defaults.get("update_existing", True),
                skip_default_group_bind=remote_defaults.get(
                    "skip_default_group_bind", False
                ),
                confirm_mixed_channel_risk=remote_defaults.get(
                    "confirm_mixed_channel_risk", False
                ),
            ),
            str(candidate_path),
        )
    raise RuntimeError(
        "未检测到 Sub2API 配置，请先在项目根目录 .env 或当前目录 .env 填写 "
        "SUB2API_BASE_URL 和 SUB2API_ADMIN_API_KEY。"
    )


def load_sub2api_usage_lookup(env_path: str | Path | None = None) -> Sub2APIUsageLoadResult:
    """读取远程 OpenAI OAuth 账号额度，并按邮箱建立索引。"""

    remote_config, config_path = load_available_remote_config(env_path)
    account_items = fetch_remote_account_list(remote_config)
    lookup: dict[str, Sub2APIUsageSnapshot] = {}
    for account_item in account_items:
        snapshot = extract_snapshot_from_account_item(account_item)
        if snapshot is None or snapshot.email in lookup:
            continue
        lookup[snapshot.email] = snapshot
    return Sub2APIUsageLoadResult(
        config_path=config_path,
        remote_total=len(account_items),
        lookup=lookup,
        summaries=load_remote_account_summaries_from_items(account_items),
    )


def load_remote_account_summaries(
    env_path: str | Path | None = None,
) -> list[Sub2APIRemoteAccountSummary]:
    """读取远程账号摘要列表。"""

    remote_config, _config_path = load_available_remote_config(env_path)
    account_items = fetch_remote_account_list(remote_config)
    return load_remote_account_summaries_from_items(account_items)


def load_remote_account_summaries_from_items(
    account_items: list[dict[str, Any]],
) -> list[Sub2APIRemoteAccountSummary]:
    """从远程账号列表构建账号摘要。"""

    summaries: list[Sub2APIRemoteAccountSummary] = []
    seen_ids: set[int] = set()
    for account_item in account_items:
        summary = extract_remote_account_summary(account_item)
        if summary is None or summary.account_id in seen_ids:
            continue
        seen_ids.add(summary.account_id)
        summaries.append(summary)
    return summaries


def set_remote_accounts_status(
    account_ids: list[int] | tuple[int, ...],
    status: str,
    env_path: str | Path | None = None,
) -> dict[str, Any]:
    """批量设置远程账号状态。"""

    normalized_ids = normalize_remote_account_ids(account_ids)
    if not normalized_ids:
        return {
            "success": 0,
            "failed": 0,
            "success_ids": [],
            "failed_ids": [],
            "results": [],
            "skipped": True,
        }
    remote_config, _config_path = load_available_remote_config(env_path)
    return bulk_update_remote_accounts(
        remote_config,
        {
            "account_ids": normalized_ids,
            "status": str(status or "").strip().lower(),
        },
    )


def set_remote_accounts_inactive(
    account_ids: list[int] | tuple[int, ...],
    env_path: str | Path | None = None,
) -> dict[str, Any]:
    """把远程账号批量停用为 inactive。"""

    return set_remote_accounts_status(account_ids, "inactive", env_path=env_path)


def refresh_remote_accounts(
    account_ids: list[int] | tuple[int, ...],
    env_path: str | Path | None = None,
) -> dict[str, Any]:
    """批量刷新远程账号 token 和额度快照。"""

    normalized_ids = normalize_remote_account_ids(account_ids)
    if not normalized_ids:
        return {
            "total": 0,
            "success": 0,
            "failed": 0,
            "success_ids": [],
            "failed_ids": [],
            "errors": [],
            "warnings": [],
            "results": [],
            "skipped": True,
        }

    remote_config, _config_path = load_available_remote_config(env_path)
    url = build_sub2api_admin_url(remote_config.base_url, SUB2API_BATCH_REFRESH_PATH)
    status_code, body_text, payload = request_json(
        url,
        method="POST",
        headers=build_sub2api_admin_headers(remote_config.admin_api_key),
        json_body={"account_ids": normalized_ids},
    )
    if status_code < 200 or status_code >= 300:
        raise RuntimeError(
            build_remote_error_message("批量刷新远程账号", status_code, body_text, payload)
        )
    data = unwrap_sub2api_response(payload)
    if not isinstance(data, dict):
        raise RuntimeError("批量刷新远程账号成功但返回结果格式不符合预期")
    success_ids = normalize_remote_account_ids(data.get("success_ids") or [])
    failed_ids = normalize_remote_account_ids(data.get("failed_ids") or [])
    success_count = int(data.get("success", 0) or 0)
    failed_count = int(data.get("failed", 0) or 0)
    if not success_ids and success_count == len(normalized_ids) and failed_count == 0:
        success_ids = list(normalized_ids)
    if not failed_ids and failed_count == len(normalized_ids) and success_count == 0:
        failed_ids = list(normalized_ids)
    return {
        "total": int(data.get("total", len(normalized_ids)) or len(normalized_ids)),
        "success": success_count,
        "failed": failed_count,
        "success_ids": success_ids,
        "failed_ids": failed_ids,
        "errors": data.get("errors") or [],
        "warnings": data.get("warnings") or [],
        "results": data.get("results") or [],
    }


def refresh_remote_account(account_id: int) -> dict[str, Any]:
    """调用单账号 refresh 接口，刷新指定账号的令牌和远程状态。"""

    normalized_ids = normalize_remote_account_ids([account_id])
    if not normalized_ids:
        return {
            "success": 0,
            "failed": 0,
            "success_ids": [],
            "failed_ids": [],
            "results": [],
            "skipped": True,
        }
    normalized_id = normalized_ids[0]
    remote_config, _config_path = load_available_remote_config()
    path = SUB2API_SINGLE_REFRESH_PATH_TEMPLATE.format(account_id=normalized_id)
    url = build_sub2api_admin_url(remote_config.base_url, path)
    status_code, body_text, payload = request_json(
        url,
        method="POST",
        headers=build_sub2api_admin_headers(remote_config.admin_api_key),
    )
    if status_code < 200 or status_code >= 300:
        raise RuntimeError(
            build_remote_error_message("刷新远程账号令牌", status_code, body_text, payload)
        )
    data = unwrap_sub2api_response(payload)
    return {
        "success": 1,
        "failed": 0,
        "success_ids": [normalized_id],
        "failed_ids": [],
        "results": [{"account_id": normalized_id, "data": data}],
        "url": url,
    }


def refresh_remote_accounts_serial(
    account_ids: list[int] | tuple[int, ...],
) -> dict[str, Any]:
    """逐个调用单账号 refresh 接口，适合席位切换后的稳定恢复链路。"""

    normalized_ids = normalize_remote_account_ids(account_ids)
    if not normalized_ids:
        return {
            "success": 0,
            "failed": 0,
            "success_ids": [],
            "failed_ids": [],
            "results": [],
            "errors": [],
            "warnings": [],
            "skipped": True,
        }

    success_ids: list[int] = []
    failed_ids: list[int] = []
    errors: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    for account_id in normalized_ids:
        try:
            item_result = refresh_remote_account(account_id)
        except Exception as exc:  # noqa: BLE001
            failed_ids.append(account_id)
            error_message = str(exc).strip() or "未知错误"
            errors.append(
                {
                    "account_id": account_id,
                    "message": error_message,
                }
            )
            results.append(
                {
                    "account_id": account_id,
                    "success": False,
                    "message": error_message,
                }
            )
            continue
        success_ids.extend(normalize_remote_account_ids(item_result.get("success_ids") or []))
        results.extend(item_result.get("results") or [])
    return {
        "success": len(success_ids),
        "failed": len(failed_ids),
        "success_ids": normalize_remote_account_ids(success_ids),
        "failed_ids": normalize_remote_account_ids(failed_ids),
        "results": results,
        "errors": errors,
        "warnings": [],
    }


def recover_remote_account_state(account_id: int) -> dict[str, Any]:
    """调用单账号 recover-state，把限流/异常状态恢复成可再次校验的状态。"""

    normalized_ids = normalize_remote_account_ids([account_id])
    if not normalized_ids:
        return {
            "success": 0,
            "failed": 0,
            "success_ids": [],
            "failed_ids": [],
            "results": [],
            "skipped": True,
        }
    normalized_id = normalized_ids[0]
    remote_config, _config_path = load_available_remote_config()
    path = SUB2API_RECOVER_STATE_PATH_TEMPLATE.format(account_id=normalized_id)
    url = build_sub2api_admin_url(remote_config.base_url, path)
    status_code, body_text, payload = request_json(
        url,
        method="POST",
        headers=build_sub2api_admin_headers(remote_config.admin_api_key),
    )
    if status_code < 200 or status_code >= 300:
        raise RuntimeError(
            build_remote_error_message("恢复远程账号状态", status_code, body_text, payload)
        )
    data = unwrap_sub2api_response(payload)
    return {
        "success": 1,
        "failed": 0,
        "success_ids": [normalized_id],
        "failed_ids": [],
        "results": [{"account_id": normalized_id, "data": data}],
        "url": url,
    }


def recover_remote_accounts_state(
    account_ids: list[int] | tuple[int, ...],
) -> dict[str, Any]:
    """逐个调用 recover-state，返回真实成功和失败的账号 ID。"""

    normalized_ids = normalize_remote_account_ids(account_ids)
    if not normalized_ids:
        return {
            "success": 0,
            "failed": 0,
            "success_ids": [],
            "failed_ids": [],
            "results": [],
            "errors": [],
            "skipped": True,
        }

    success_ids: list[int] = []
    failed_ids: list[int] = []
    errors: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    for account_id in normalized_ids:
        try:
            item_result = recover_remote_account_state(account_id)
        except Exception as exc:  # noqa: BLE001
            failed_ids.append(account_id)
            error_message = str(exc).strip() or "未知错误"
            errors.append(
                {
                    "account_id": account_id,
                    "message": error_message,
                }
            )
            results.append(
                {
                    "account_id": account_id,
                    "success": False,
                    "message": error_message,
                }
            )
            continue
        success_ids.extend(normalize_remote_account_ids(item_result.get("success_ids") or []))
        results.extend(item_result.get("results") or [])
    return {
        "success": len(success_ids),
        "failed": len(failed_ids),
        "success_ids": normalize_remote_account_ids(success_ids),
        "failed_ids": normalize_remote_account_ids(failed_ids),
        "results": results,
        "errors": errors,
    }
