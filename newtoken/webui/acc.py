"""ACC credential, member, and seat-policy actions for the WebUI."""

from __future__ import annotations

import json
import time
from typing import Any

import newtoken.acc.seat_client as seat_core
from newtoken.sub2api.remote import delete_dead_remote_accounts
from newtoken.sub2api.usage_bridge import (
    Sub2APIUsageSnapshot,
    load_sub2api_usage_lookup,
    normalize_email,
    refresh_remote_accounts,
    set_remote_accounts_inactive,
    set_remote_accounts_status,
)
from newtoken.webui.config import LOW_QUOTA_THRESHOLD_PERCENT, SeatApiWebError, WebState


ACC_MOTHER_USER_ID = "user-s48XGo8NpCt5xv9XoI3b0w4z"
MIN_COOLDOWN_RESERVE_MEMBERS = 3
ACC_BACKEND_EMAIL_DOMAIN = "example.com"
ACC_BACKEND_EMAIL_PREFIX = "sm"
ACC_BACKEND_EMAIL_START = 1
ACC_BACKEND_EMAIL_TEMPLATE = "sm{index:03d}@example.com"
FIVE_HOURS_SECONDS = 5 * 60 * 60
SEVEN_DAYS_SECONDS = 7 * 24 * 60 * 60
THIRTY_ONE_DAYS_SECONDS = 31 * 24 * 60 * 60


def is_mother_account_user(user: dict[str, Any]) -> bool:
    return str(user.get("id") or "").strip() == ACC_MOTHER_USER_ID


def normalize_backend_email_template(template: str | None) -> str:
    normalized = str(template or "").strip() or ACC_BACKEND_EMAIL_TEMPLATE
    if "{index" not in normalized:
        raise SeatApiWebError("账号池模板必须包含 {index}，例如 sm{index:03d}@example.com")
    return normalized


def parse_backend_email_start_index(value: Any) -> int:
    try:
        start_index = int(str(value or ACC_BACKEND_EMAIL_START).strip())
    except (TypeError, ValueError) as exc:
        raise SeatApiWebError("账号池起始序号必须是正整数") from exc
    if start_index <= 0:
        raise SeatApiWebError("账号池起始序号必须是正整数")
    return start_index


def build_backend_account_email(index: int, template: str | None = None) -> str:
    normalized_template = normalize_backend_email_template(template)
    try:
        return normalized_template.format(index=int(index))
    except (KeyError, IndexError, ValueError) as exc:
        raise SeatApiWebError("账号池模板格式错误，请使用 {index} 或 {index:03d}") from exc


def iter_backend_account_email_pool(
    *,
    template: str | None = None,
    start_index: int = ACC_BACKEND_EMAIL_START,
):
    index = parse_backend_email_start_index(start_index)
    while True:
        yield build_backend_account_email(index, template)
        index += 1


def demote_protected_mother_account(
    client: seat_core.SeatClient,
    users: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    changed_members: list[dict[str, Any]] = []
    for user in users:
        if not is_mother_account_user(user):
            continue
        if seat_core.is_codex_seat_type(user.get("seat_type")):
            continue
        result = seat_core.ensure_user_seat(
            client,
            user_id=ACC_MOTHER_USER_ID,
            email=None,
            target_seat_type=seat_core.CODEX_SEAT_TYPE,
        )
        changed_members.append(
            {
                "email": user.get("email") or "",
                "user_id": ACC_MOTHER_USER_ID,
                "reason": "母号不能占用 ChatGPT 席位",
                "seat_result": result,
            }
        )
    return changed_members


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
            "accountId": str(
                account_data.get("id")
                or data.get("accountId")
                or data.get("account_id")
                or data.get("account-id")
                or ""
            ).strip(),
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


def load_acc_members(state: WebState, query: str = "") -> dict[str, Any]:
    client = state.build_seat_client()
    normalized_query = str(query or "").strip()
    usage_lookup: dict[str, Sub2APIUsageSnapshot] = {}
    usage_error = ""
    try:
        usage_result = load_sub2api_usage_lookup(state.env_path)
    except Exception as exc:  # noqa: BLE001
        usage_result = None
        usage_error = str(exc)
    if usage_result is not None:
        usage_lookup = dict(usage_result.lookup)
        state.last_usage_lookup = dict(usage_result.lookup)
    all_users = seat_core.list_all_users(client, query="")
    protected_mother_members = demote_protected_mother_account(client, all_users)
    if protected_mother_members:
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
    users = [enrich_user_with_usage(user, usage_lookup) for user in users]
    state.last_acc_members = users
    return {
        "items": users,
        "total": len(users),
        "chatgpt_count": seat_core.count_chatgpt_seats(all_users),
        "chatgpt_limit": seat_core.CHATGPT_SEAT_LIMIT,
        "limit_changed_members": limit_result.get("changed_users") or [],
        "protected_mother_members": protected_mother_members,
        "usage_error": usage_error,
    }


def enrich_user_with_usage(
    user: dict[str, Any],
    usage_lookup: dict[str, Sub2APIUsageSnapshot],
) -> dict[str, Any]:
    normalized_email = normalize_email(user.get("email"))
    snapshot = usage_lookup.get(normalized_email)
    enriched = dict(user)
    if snapshot is None:
        enriched.update(
            {
                "quota_current": "未导入",
                "quota_5h": "未导入",
                "quota_7d": "未导入",
                "quota_31d": "未导入",
                "quota_5h_eta": "--",
                "quota_7d_eta": "--",
                "quota_31d_eta": "--",
                "quota_updated_at": "--",
            }
        )
        return enriched
    quota_5h_text = str(snapshot.quota_5h_text or "--").strip() or "--"
    quota_7d_text = str(snapshot.quota_7d_text or "--").strip() or "--"
    quota_31d_text = str(getattr(snapshot, "quota_31d_text", "--") or "--").strip() or "--"
    current_quota_text = "--"
    if quota_31d_text != "--":
        current_quota_text = f"31天 {quota_31d_text}"
    elif quota_7d_text != "--":
        current_quota_text = f"7天 {quota_7d_text}"
    elif quota_5h_text != "--":
        current_quota_text = f"5h {quota_5h_text}"
    enriched.update(
        {
            "quota_current": current_quota_text,
            "quota_5h": quota_5h_text,
            "quota_7d": quota_7d_text,
            "quota_31d": quota_31d_text,
            "quota_5h_eta": estimate_quota_exhaust_eta_text(
                snapshot.quota_5h_remaining_percent,
                snapshot.quota_5h_reset_after_seconds,
                FIVE_HOURS_SECONDS,
            ),
            "quota_7d_eta": estimate_quota_exhaust_eta_text(
                snapshot.quota_7d_remaining_percent,
                snapshot.quota_7d_reset_after_seconds,
                SEVEN_DAYS_SECONDS,
            ),
            "quota_31d_eta": estimate_quota_exhaust_eta_text(
                getattr(snapshot, "quota_31d_remaining_percent", None),
                getattr(snapshot, "quota_31d_reset_after_seconds", None),
                THIRTY_ONE_DAYS_SECONDS,
            ),
            "quota_updated_at": str(snapshot.usage_updated_at or "--").strip() or "--",
        }
    )
    return enriched


def estimate_quota_exhaust_eta_text(
    remaining_percent: float | None,
    reset_after_seconds: int | None,
    window_seconds: int,
) -> str:
    if remaining_percent is None:
        return "--"
    if remaining_percent <= 0:
        return "已用完"
    if reset_after_seconds is None:
        return "--"
    remaining_seconds = max(0, int(reset_after_seconds))
    elapsed_seconds = max(0, int(window_seconds) - remaining_seconds)
    used_percent = 100.0 - float(remaining_percent)
    if used_percent <= 0 or elapsed_seconds <= 0:
        return "样本不足"
    consume_rate = used_percent / float(elapsed_seconds)
    if consume_rate <= 0:
        return "样本不足"
    exhaust_seconds = int(float(remaining_percent) / consume_rate)
    if exhaust_seconds >= remaining_seconds:
        return "本周期用不完"
    return format_eta_seconds(exhaust_seconds)


def format_eta_seconds(value: int) -> str:
    seconds = max(0, int(value or 0))
    if seconds <= 0:
        return "即将用完"
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _seconds = divmod(remainder, 60)
    if days > 0:
        return f"{days}天{hours}小时"
    if hours > 0:
        return f"{hours}小时{minutes}分"
    if minutes > 0:
        return f"{minutes}分"
    return f"{seconds}秒"


def is_low_quota_snapshot(
    snapshot: Sub2APIUsageSnapshot,
    *,
    threshold_percent: float = LOW_QUOTA_THRESHOLD_PERCENT,
) -> bool:
    """Return True when any tracked quota window is below threshold."""

    values = [
        snapshot.quota_5h_remaining_percent,
        snapshot.quota_7d_remaining_percent,
        getattr(snapshot, "quota_31d_remaining_percent", None),
    ]
    known_values = [float(value) for value in values if value is not None]
    if not known_values:
        return False
    return any(value < threshold_percent for value in known_values)


def has_enough_quota_snapshot(
    snapshot: Sub2APIUsageSnapshot,
    *,
    threshold_percent: float = LOW_QUOTA_THRESHOLD_PERCENT,
) -> bool:
    """Return True only when every known quota window is at or above threshold."""

    values = [
        snapshot.quota_5h_remaining_percent,
        snapshot.quota_7d_remaining_percent,
        getattr(snapshot, "quota_31d_remaining_percent", None),
    ]
    known_values = [float(value) for value in values if value is not None]
    if not known_values:
        return False
    return all(value >= threshold_percent for value in known_values)


def classify_remote_runtime_ids_by_acc_seat(
    users: list[dict[str, Any]],
    usage_lookup: dict[str, Sub2APIUsageSnapshot],
    *,
    threshold_percent: float = LOW_QUOTA_THRESHOLD_PERCENT,
) -> dict[str, list[int]]:
    """按 ACC 席位决定 Sub2API 运行状态：只有 ChatGPT 且额度健康才启用。"""

    active_ids: set[int] = set()
    inactive_ids: set[int] = set()
    for user in users:
        email = normalize_email(user.get("email"))
        if not email:
            continue
        snapshot = usage_lookup.get(email)
        if snapshot is None:
            continue
        try:
            account_id = int(snapshot.account_id or 0)
        except (TypeError, ValueError):
            account_id = 0
        if account_id <= 0:
            continue
        is_chatgpt = seat_core.is_chatgpt_seat_type(user.get("seat_type"))
        can_run = (
            is_chatgpt
            and not is_mother_account_user(user)
            and has_enough_quota_snapshot(
                snapshot,
                threshold_percent=threshold_percent,
            )
        )
        if can_run:
            active_ids.add(account_id)
        else:
            inactive_ids.add(account_id)
    inactive_ids.difference_update(active_ids)
    return {
        "active_ids": sorted(active_ids),
        "inactive_ids": sorted(inactive_ids),
    }


def extract_invalidated_remote_account_ids(
    refresh_result: dict[str, Any],
) -> list[int]:
    """提取额度刷新时返回 401 或 token_invalidated 的远程账号 ID。"""

    invalidated_ids: set[int] = set()
    candidates: list[dict[str, Any]] = []
    for key in ("errors", "results"):
        values = refresh_result.get(key) if isinstance(refresh_result, dict) else None
        if isinstance(values, list):
            candidates.extend(item for item in values if isinstance(item, dict))
    markers = (
        "token_invalidated",
        "token_revoked",
        "authentication token has been invalidated",
        "invalidated oauth token",
        "http 401",
        '"status": 401',
        '"status_code": 401',
    )
    for item in candidates:
        try:
            account_id = int(item.get("account_id") or item.get("id") or 0)
        except (TypeError, ValueError):
            account_id = 0
        if account_id <= 0:
            continue
        serialized = json.dumps(item, ensure_ascii=False, sort_keys=True).lower()
        if any(marker in serialized for marker in markers):
            invalidated_ids.add(account_id)
    return sorted(invalidated_ids)


def delete_invalidated_accounts(
    client: seat_core.SeatClient,
    users_by_email: dict[str, dict[str, Any]],
    snapshots_by_account_id: dict[int, Sub2APIUsageSnapshot],
    invalidated_account_ids: list[int],
    *,
    remote_config: Any,
    remote_delete=delete_dead_remote_accounts,
    block_promotion=None,
) -> dict[str, Any]:
    """先删除 ACC 成员，再删除对应的 Sub2API 失效账号。"""

    deleted_acc_user_ids: list[str] = []
    acc_delete_failures: list[dict[str, Any]] = []
    remote_items: list[dict[str, Any]] = []
    invalidated_accounts: list[dict[str, Any]] = []
    for account_id in sorted(set(invalidated_account_ids)):
        snapshot = snapshots_by_account_id.get(account_id)
        email = normalize_email(snapshot.email if snapshot else "")
        user = users_by_email.get(email) if email else None
        account_result = {
            "account_id": account_id,
            "email": email,
            "acc_deleted": user is None,
            "permanently_blocked": False,
            "acc_error": "",
            "remote_deleted": False,
            "remote_error": "",
        }
        if user is not None:
            user_id = str(user.get("id") or "").strip()
            try:
                client.delete_user(user_id)
            except Exception as exc:  # noqa: BLE001
                if block_promotion is not None and email:
                    block_promotion(email)
                account_result["permanently_blocked"] = True
                account_result["acc_error"] = str(exc)
                acc_delete_failures.append(
                    {
                        "account_id": account_id,
                        "email": email,
                        "error": str(exc),
                    }
                )
            else:
                deleted_acc_user_ids.append(user_id)
                account_result["acc_deleted"] = True
        remote_items.append(
            {
                "account_id": account_id,
                "name": snapshot.name if snapshot else email or str(account_id),
            }
        )
        invalidated_accounts.append(account_result)
    remote_result = remote_delete(remote_config, remote_items)
    remote_results_by_id = {
        int(item.get("account_id") or 0): item
        for item in remote_result.get("items") or []
        if isinstance(item, dict)
    }
    for item in invalidated_accounts:
        remote_item = remote_results_by_id.get(int(item["account_id"]))
        if remote_item is not None:
            item["remote_deleted"] = bool(remote_item.get("success"))
            item["remote_error"] = str(remote_item.get("error") or "")
    return {
        "deleted_acc_user_ids": deleted_acc_user_ids,
        "acc_delete_failures": acc_delete_failures,
        "remote_result": remote_result,
        "invalidated_accounts": invalidated_accounts,
    }


def refresh_all_remote_usage_snapshots(state: WebState):
    """Refresh all Sub2API account quota snapshots before making policy decisions."""

    initial_result = load_sub2api_usage_lookup(state.env_path)
    account_ids = sorted(
        {
            int(summary.account_id)
            for summary in initial_result.summaries
            if int(summary.account_id or 0) > 0
        }
    )
    if not account_ids:
        return initial_result, {
            "total": 0,
            "success": 0,
            "failed": 0,
            "success_ids": [],
            "failed_ids": [],
            "skipped": True,
        }
    refresh_result = refresh_remote_accounts(account_ids, env_path=state.env_path)
    return load_sub2api_usage_lookup(state.env_path), refresh_result


def rank_promotion_snapshot(snapshot: Sub2APIUsageSnapshot) -> tuple[float, float, str]:
    """Prefer accounts with the most conservative remaining quota."""

    known_values = [
        float(value)
        for value in (
            snapshot.quota_5h_remaining_percent,
            snapshot.quota_7d_remaining_percent,
        )
        if value is not None
    ]
    minimum_remaining = min(known_values) if known_values else -1.0
    maximum_remaining = max(known_values) if known_values else -1.0
    return (-minimum_remaining, -maximum_remaining, snapshot.email)


def ensure_minimum_cooldown_reserve_members(
    client: seat_core.SeatClient,
    state: WebState,
    users: list[dict[str, Any]],
    usage_lookup: dict[str, Sub2APIUsageSnapshot],
    *,
    now: float,
    target_count: int = MIN_COOLDOWN_RESERVE_MEMBERS,
) -> dict[str, Any]:
    """Invite new ACC members only when available Codex reserve members are too few."""

    users_by_email = {
        normalize_email(user.get("email")): user
        for user in users
        if normalize_email(user.get("email"))
    }
    reserve_emails: set[str] = set()
    for user in users:
        email = normalize_email(user.get("email"))
        if not email:
            continue
        if is_mother_account_user(user):
            continue
        if not seat_core.is_codex_seat_type(user.get("seat_type")):
            continue
        if state.is_promotion_permanently_blocked(email):
            continue
        if state.is_promotion_on_cooldown(email, now):
            continue
        reserve_emails.add(email)

    missing_count = max(0, int(target_count) - len(reserve_emails))
    invited_members: list[dict[str, Any]] = []
    skipped_members: list[dict[str, Any]] = []
    if missing_count <= 0:
        return {
            "target_count": target_count,
            "reserve_count": len(reserve_emails),
            "missing_count": 0,
            "invited_members": [],
            "skipped_members": [],
        }

    config_values = state.load_config() if hasattr(state, "load_config") else {}
    backend_template = normalize_backend_email_template(
        config_values.get("ACC_BACKEND_EMAIL_TEMPLATE")
    )
    backend_start_index = parse_backend_email_start_index(
        config_values.get("ACC_BACKEND_EMAIL_START_INDEX")
    )
    candidates: list[str] = []
    for email in iter_backend_account_email_pool(
        template=backend_template,
        start_index=backend_start_index,
    ):
        if email in users_by_email:
            continue
        if state.is_promotion_permanently_blocked(email):
            continue
        if state.is_promotion_on_cooldown(email, now):
            continue
        candidates.append(email)
        if len(candidates) >= missing_count:
            break
    for email in candidates:
        try:
            invite_result = client.invite_user(
                email,
                seat_type=seat_core.CODEX_SEAT_TYPE,
            )
        except Exception as exc:  # noqa: BLE001
            permanently_blocked = False
            if hasattr(state, "block_promotion_permanently"):
                state.block_promotion_permanently(email)
                permanently_blocked = True
            skipped_members.append(
                {
                    "email": email,
                    "account_id": None,
                    "reason": str(exc),
                    "permanently_blocked": permanently_blocked,
                }
            )
            continue
        invited_members.append(
            {
                "email": email,
                "account_id": None,
                "seat_type": seat_core.CODEX_SEAT_TYPE,
                "invite_result": invite_result,
            }
        )

    return {
        "target_count": target_count,
        "reserve_count": len(reserve_emails),
        "missing_count": missing_count,
        "invited_members": invited_members,
        "skipped_members": skipped_members,
    }


def promote_user_to_chatgpt_with_hard_cap(
    client: seat_core.SeatClient,
    user: dict[str, Any],
) -> dict[str, Any]:
    """Promote one Codex user to ChatGPT only when the hard cap still has room."""

    if is_mother_account_user(user):
        raise SeatApiWebError("母号不能改为 ChatGPT")
    current_users = seat_core.list_all_users(client)
    if seat_core.count_chatgpt_seats(current_users) >= seat_core.CHATGPT_SEAT_LIMIT:
        raise SeatApiWebError(
            f"ChatGPT 席位硬限制为 {seat_core.CHATGPT_SEAT_LIMIT}，当前已满"
        )
    user_id = str(user.get("id", "")).strip()
    if not user_id:
        raise SeatApiWebError("补位用户缺少 user_id")
    latest_user = seat_core.resolve_target_user(current_users, user_id, None)
    current_seat_type = str(latest_user.get("seat_type") or "")
    if seat_core.is_chatgpt_seat_type(current_seat_type):
        return {
            "user": latest_user,
            "attempts": 0,
            "changed": False,
            "targetSeatType": seat_core.CHATGPT_SEAT_TYPE,
            "identifier": latest_user.get("email") or user_id,
        }
    for attempt in range(1, seat_core.DEFAULT_SEAT_UPDATE_RETRY_COUNT + 1):
        response = client.update_user_seat(user_id, seat_core.CHATGPT_SEAT_TYPE)
        if response.get("success") is not True:
            raise SeatApiWebError("补位接口未返回 success=true")
        verified_user = seat_core.find_user(client, user_id=user_id, email=None)
        if seat_core.is_chatgpt_seat_type(verified_user.get("seat_type")):
            if seat_core.count_chatgpt_seats(seat_core.list_all_users(client)) > seat_core.CHATGPT_SEAT_LIMIT:
                seat_core.ensure_user_seat(
                    client,
                    user_id=user_id,
                    email=None,
                    target_seat_type=seat_core.CODEX_SEAT_TYPE,
                )
                raise SeatApiWebError("补位后 ChatGPT 席位超过硬限制，已回退 Codex")
            return {
                "user": verified_user,
                "attempts": attempt,
                "changed": True,
                "targetSeatType": seat_core.CHATGPT_SEAT_TYPE,
                "identifier": verified_user.get("email") or user_id,
            }
        time.sleep(seat_core.DEFAULT_SEAT_RETRY_DELAY_SECONDS)
    raise SeatApiWebError("补位重试后仍未变成 ChatGPT")


def enforce_acc_low_quota_policy(state: WebState) -> dict[str, Any]:
    """Refresh usage, demote low-quota accounts, and promote healthy Codex accounts."""

    usage_result, refresh_result = refresh_all_remote_usage_snapshots(state)
    state.last_usage_lookup = dict(usage_result.lookup)
    client = state.build_seat_client()
    users = seat_core.list_all_users(client)
    protected_mother_members = demote_protected_mother_account(client, users)
    if protected_mother_members:
        users = seat_core.list_all_users(client)
    users_by_email = {
        normalize_email(user.get("email")): user
        for user in users
        if normalize_email(user.get("email"))
    }
    invalidated_remote_ids = extract_invalidated_remote_account_ids(refresh_result)
    snapshots_by_account_id = {
        int(snapshot.account_id): snapshot
        for snapshot in usage_result.lookup.values()
        if int(snapshot.account_id or 0) > 0
    }
    invalidated_result = delete_invalidated_accounts(
        client,
        users_by_email,
        snapshots_by_account_id,
        invalidated_remote_ids,
        remote_config=state.build_remote_config(),
        block_promotion=state.block_promotion_permanently,
    )
    if invalidated_remote_ids:
        users = seat_core.list_all_users(client)
        users_by_email = {
            normalize_email(user.get("email")): user
            for user in users
            if normalize_email(user.get("email"))
        }
    low_items = [
        snapshot
        for snapshot in usage_result.lookup.values()
        if int(snapshot.account_id or 0) not in invalidated_remote_ids
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
    low_quota_delete_items = [
        {
            "account_id": int(snapshot.account_id or 0),
            "name": str(snapshot.name or snapshot.email or "").strip() or str(snapshot.account_id or ""),
        }
        for snapshot in low_items
        if int(snapshot.account_id or 0) > 0
        and str(snapshot.account_status or "").lower() != "inactive"
    ]
    deleted_low_quota_result = delete_dead_remote_accounts(
        state.build_remote_config(),
        low_quota_delete_items,
    )
    changed_members: list[dict[str, Any]] = []
    skipped_members: list[dict[str, Any]] = []
    promoted_members: list[dict[str, Any]] = []
    promotion_skips: list[dict[str, Any]] = []
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
        cooldown_until = state.mark_promotion_cooldown(
            normalize_email(snapshot.email),
            time.time(),
        )
        changed_members.append(
            {
                "email": snapshot.email,
                "account_id": snapshot.account_id,
                "quota_5h": snapshot.quota_5h_text,
                "quota_7d": snapshot.quota_7d_text,
                "seat_result": result,
                "cooldown_until": cooldown_until,
            }
        )
    after_low_quota_users = seat_core.list_all_users(client)
    limit_result = seat_core.enforce_chatgpt_seat_limit(
        client,
        users=after_low_quota_users,
        limit=seat_core.CHATGPT_SEAT_LIMIT,
        )
    for changed_user in limit_result.get("changed_users") or []:
        state.mark_promotion_cooldown(
            normalize_email(changed_user.get("email")),
            time.time(),
        )
    refreshed_users = limit_result["users"]
    chatgpt_count = seat_core.count_chatgpt_seats(refreshed_users)
    remaining_low_quota_chatgpt_members = [
        {
            "email": snapshot.email,
            "account_id": snapshot.account_id,
        }
        for snapshot in low_items
        for user in [next(
            (
                item
                for item in refreshed_users
                if normalize_email(item.get("email")) == normalize_email(snapshot.email)
            ),
            None,
        )]
        if user is not None
        and not seat_core.is_codex_seat_type(user.get("seat_type"))
    ]
    seat_count_verified = (
        chatgpt_count <= seat_core.CHATGPT_SEAT_LIMIT
        and not remaining_low_quota_chatgpt_members
    )
    users_by_email = {
        normalize_email(user.get("email")): user
        for user in refreshed_users
        if normalize_email(user.get("email"))
    }
    now = time.time()
    reserve_result = {
        "target_count": 0,
        "reserve_count": 0,
        "missing_count": 0,
        "invited_members": [],
        "skipped_members": [],
    }
    # feat/javoo：补位由 auto.py 的注册引擎(register_batch, OIDC 卡密注册)承担，
    # 策略本身不做 blind oauth 导入（main 的脱敏补位机制在此分支不适用）。
    blind_import_results: list[dict[str, Any]] = []

    final_users = seat_core.list_all_users(client)
    final_mother_members = demote_protected_mother_account(client, final_users)
    if final_mother_members:
        protected_mother_members.extend(final_mother_members)
        final_users = seat_core.list_all_users(client)
    final_limit_result = seat_core.enforce_chatgpt_seat_limit(
        client,
        users=final_users,
        limit=seat_core.CHATGPT_SEAT_LIMIT,
    )
    for changed_user in final_limit_result.get("changed_users") or []:
        state.mark_promotion_cooldown(
            normalize_email(changed_user.get("email")),
            time.time(),
        )
    refreshed_users = final_limit_result["users"]
    runtime_remote_ids = classify_remote_runtime_ids_by_acc_seat(
        refreshed_users,
        usage_result.lookup,
    )
    active_chatgpt_remote_ids = runtime_remote_ids["active_ids"]
    inactive_non_chatgpt_remote_ids = runtime_remote_ids["inactive_ids"]
    inactive_non_chatgpt_result = set_remote_accounts_status(
        inactive_non_chatgpt_remote_ids,
        "inactive",
        env_path=state.env_path,
    )
    active_chatgpt_result = set_remote_accounts_status(
        active_chatgpt_remote_ids,
        "active",
        env_path=state.env_path,
    )
    state.last_acc_members = refreshed_users
    return {
        "threshold_percent": LOW_QUOTA_THRESHOLD_PERCENT,
        "remote_refresh": refresh_result,
        "invalidated_remote_ids": invalidated_remote_ids,
        "invalidated_result": invalidated_result,
        "remote_total": usage_result.remote_total,
        "low_quota_count": len(low_items),
        "disabled_remote_ids": low_remote_ids,
        "disabled_result": deleted_low_quota_result,
        "deleted_low_quota_result": deleted_low_quota_result,
        "seat_count_verified_before_promotion": seat_count_verified,
        "remaining_low_quota_chatgpt_members": remaining_low_quota_chatgpt_members,
        "active_chatgpt_remote_ids": active_chatgpt_remote_ids,
        "active_chatgpt_result": active_chatgpt_result,
        "inactive_non_chatgpt_remote_ids": inactive_non_chatgpt_remote_ids,
        "inactive_non_chatgpt_result": inactive_non_chatgpt_result,
        "changed_members": changed_members,
        "protected_mother_members": protected_mother_members,
        "reserve_members": reserve_result,
        "promoted_members": promoted_members,
        "promotion_skips": promotion_skips,
        "blind_import_results": blind_import_results,
        "skipped_members": skipped_members,
        "limit_changed_members": (
            (limit_result.get("changed_users") or [])
            + (final_limit_result.get("changed_users") or [])
        ),
        "limit_overflow_count": (
            int(limit_result.get("overflow_count", 0) or 0)
            + int(final_limit_result.get("overflow_count", 0) or 0)
        ),
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
    changed_user = result.get("user") if isinstance(result, dict) else {}
    state.policy_events.append(
        action="demote_codex",
        email=(
            str(changed_user.get("email") or "").strip()
            if isinstance(changed_user, dict)
            else email
        ),
        reason="手动调整席位",
        result="success",
        details={"user_id": user_id},
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
        payload.get("accountId", "") or current_values.get("OPENAI_ACCOUNT_ID", ""),
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
        access_token, account_id = seat_core.extract_session_credentials(
            session_data,
            fallback_account_id=credentials.get("OPENAI_ACCOUNT_ID", ""),
        )
        credentials["OPENAI_ACCESS_TOKEN"] = access_token
        credentials["OPENAI_ACCOUNT_ID"] = account_id
    state.save_config(credentials)
    return {"saved": True, "account_id": credentials.get("OPENAI_ACCOUNT_ID", "")}


# ===== feat/javoo ACC 凭证解析（api.py 调用，main 基底缺，补回）=====
def _empty_acc_payload() -> dict[str, str]:
    return {key: "" for key in _PAYLOAD_KEYS}


def _clean_acc_value(value: Any) -> str:
    text = str(value or "").strip().strip('"').strip("'").strip()
    return "" if text.lower() in _ACC_EMPTY_VALUES else text


def _first_value(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        if key in data:
            value = _clean_acc_value(data.get(key))
            if value:
                return value
    return ""


def _merge_payload(base: dict[str, str], extra: dict[str, str]) -> dict[str, str]:
    merged = dict(base)
    for key, value in extra.items():
        if value and not merged.get(key):
            merged[key] = value
    return merged


def _payload_has_credentials(payload: dict[str, str]) -> bool:
    return bool(payload.get("accessToken") or payload.get("sessionToken") or payload.get("accountId"))


def _parse_env_style_payload(text: str) -> dict[str, str] | None:
    payload = _empty_acc_payload()
    found = False
    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        mapped_key = _ENV_TO_ACC_KEYS.get(key)
        if not mapped_key:
            continue
        value = raw_value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            try:
                value = str(json.loads(value))
            except json.JSONDecodeError:
                value = value[1:-1]
        payload[mapped_key] = _clean_acc_value(value)
        found = True
    return payload if found and _payload_has_credentials(payload) else None


def _payload_from_json_dict(data: dict[str, Any]) -> dict[str, str]:
    account_data = data.get("account") if isinstance(data.get("account"), dict) else {}
    payload = _empty_acc_payload()
    payload.update(
        {
            "warningBanner": _first_value(data, "WARNING_BANNER", "warningBanner"),
            "accountId": _first_value(
                account_data,
                "id",
                "accountId",
                "account_id",
                "OPENAI_ACCOUNT_ID",
            )
            or _first_value(data, "accountId", "account_id", "OPENAI_ACCOUNT_ID", "account-id"),
            "deviceId": _first_value(
                data,
                "deviceId",
                "device_id",
                "OPENAI_DEVICE_ID",
                "oai-did",
                "oaiDid",
                "did",
            ),
            "accessToken": _first_value(data, "accessToken", "access_token", "OPENAI_ACCESS_TOKEN"),
            "sessionToken": _first_value(data, "sessionToken", "session_token", "OPENAI_SESSION_TOKEN"),
            "authProvider": _first_value(data, "authProvider", "auth_provider"),
            "clientBuildNumber": _first_value(
                data,
                "clientBuildNumber",
                "client_build_number",
                "OPENAI_CLIENT_BUILD_NUMBER",
            ),
            "clientVersion": _first_value(data, "clientVersion", "client_version", "OPENAI_CLIENT_VERSION"),
            "baseUrl": _first_value(data, "baseUrl", "base_url", "OPENAI_BASE_URL"),
        }
    )
    for child_key in ("payload", "credentials", "session", "data"):
        child = data.get(child_key)
        if isinstance(child, dict):
            payload = _merge_payload(payload, _payload_from_json_dict(child))
    return payload


def _parse_cookie_payload(text: str) -> dict[str, str] | None:
    match = re.search(
        r"(?:__Secure-next-auth\.session-token|next-auth\.session-token)\s*=\s*([^;\s\"']+)",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    payload = _empty_acc_payload()
    payload["sessionToken"] = _clean_acc_value(match.group(1))
    return payload if payload["sessionToken"] else None


def _parse_bearer_payload(text: str) -> dict[str, str] | None:
    match = re.search(r"\bBearer\s+([A-Za-z0-9._~+/=-]+)", text, flags=re.IGNORECASE)
    if not match:
        return None
    payload = _empty_acc_payload()
    payload["accessToken"] = _clean_acc_value(match.group(1))
    return payload if payload["accessToken"] else None



def build_acc_credentials_from_payload(
    state: WebState,
    payload: dict[str, str],
    *,
    resolve_session: bool = True,
) -> dict[str, str]:
    current_values = state.load_config()
    base_url = (
        payload.get("baseUrl")
        or str(current_values.get("OPENAI_BASE_URL") or "").strip()
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
    if (
        resolve_session
        and payload.get("sessionToken")
        and (not credentials.get("OPENAI_ACCESS_TOKEN") or not credentials.get("OPENAI_ACCOUNT_ID"))
    ):
        session_data = seat_core.fetch_session_info(
            credentials["OPENAI_BASE_URL"],
            payload["sessionToken"],
        )
        access_token, account_id = seat_core.extract_session_credentials(session_data)
        credentials["OPENAI_ACCESS_TOKEN"] = access_token
        credentials["OPENAI_ACCOUNT_ID"] = account_id
    return credentials



def normalize_unknown_seats(state: WebState) -> dict[str, Any]:
    """Force all non-Codex/non-ChatGPT seats to Codex in bulk."""
    client = state.build_seat_client()
    users = seat_core.list_all_users(client)
    unknown = []
    changed = []
    for user in users:
        seat = str(user.get("seat_type") or "")
        if seat in ("default", "null", ""):
            continue
        if seat_core.is_codex_seat_type(seat):
            continue
        unknown.append({"id": user.get("id"), "email": user.get("email"), "seat_type": seat})
        try:
            seat_core.ensure_user_seat(client, str(user.get("id")), email=None,
                                       target_seat_type=seat_core.CODEX_SEAT_TYPE)
            changed.append({"email": user.get("email"), "from": seat, "to": "usage_based"})
        except Exception:
            pass
    return {"unknown_count": len(unknown), "changed": len(changed), "items": changed}

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


