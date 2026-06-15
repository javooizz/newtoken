"""ACC credential, member, and seat-policy actions for the WebUI."""

from __future__ import annotations

import json
from typing import Any

import standalone_acc_change_seat_cli as seat_core
from standalone_sub2api_usage_bridge import (
    Sub2APIUsageSnapshot,
    load_sub2api_usage_lookup,
    normalize_email,
    set_remote_accounts_inactive,
)
from sub2api_webui_config import LOW_QUOTA_THRESHOLD_PERCENT, SeatApiWebError, WebState


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
