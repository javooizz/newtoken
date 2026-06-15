"""ACC credential, member, and seat-policy actions for the WebUI."""

from __future__ import annotations

import json
import re
from typing import Any

import newtoken.acc.seat_client as seat_core
from newtoken.sub2api.usage_bridge import (
    Sub2APIUsageSnapshot,
    load_sub2api_usage_lookup,
    normalize_email,
    set_remote_accounts_inactive,
)
from newtoken.webui.config import LOW_QUOTA_THRESHOLD_PERCENT, SeatApiWebError, WebState

_ACC_EMPTY_VALUES = {"", "none", "null", "undefined"}

_ENV_TO_ACC_KEYS = {
    "OPENAI_ACCESS_TOKEN": "accessToken",
    "ACCESS_TOKEN": "accessToken",
    "accessToken": "accessToken",
    "access_token": "accessToken",
    "OPENAI_SESSION_TOKEN": "sessionToken",
    "SESSION_TOKEN": "sessionToken",
    "sessionToken": "sessionToken",
    "session_token": "sessionToken",
    "OPENAI_ACCOUNT_ID": "accountId",
    "ACCOUNT_ID": "accountId",
    "accountId": "accountId",
    "account_id": "accountId",
    "OPENAI_DEVICE_ID": "deviceId",
    "DEVICE_ID": "deviceId",
    "deviceId": "deviceId",
    "device_id": "deviceId",
    "OPENAI_CLIENT_BUILD_NUMBER": "clientBuildNumber",
    "clientBuildNumber": "clientBuildNumber",
    "client_build_number": "clientBuildNumber",
    "OPENAI_CLIENT_VERSION": "clientVersion",
    "clientVersion": "clientVersion",
    "client_version": "clientVersion",
    "OPENAI_BASE_URL": "baseUrl",
    "baseUrl": "baseUrl",
    "base_url": "baseUrl",
}

_PAYLOAD_KEYS = (
    "warningBanner",
    "accountId",
    "deviceId",
    "accessToken",
    "sessionToken",
    "authProvider",
    "clientBuildNumber",
    "clientVersion",
    "baseUrl",
)


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

    env_payload = _parse_env_style_payload(text)
    if env_payload:
        return env_payload

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None

    if isinstance(data, dict):
        if isinstance(data.get("log"), dict):
            return seat_core.parse_har_session_bundle(text)
        payload = _payload_from_json_dict(data)
        if _payload_has_credentials(payload):
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
            "baseUrl": "",
        }
        if payload["accessToken"] or payload["sessionToken"]:
            return payload

    cookie_payload = _parse_cookie_payload(text)
    if cookie_payload:
        return cookie_payload

    bearer_payload = _parse_bearer_payload(text)
    if bearer_payload:
        return bearer_payload

    if text.count(".") >= 2 and '"sessionToken"' not in text and "\n" not in text:
        payload = _empty_acc_payload()
        payload["accessToken"] = text
        return payload

    raise SeatApiWebError("无法识别导入格式")


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
    credentials = build_acc_credentials_from_payload(state, payload)
    state.save_config(credentials)
    has_token = bool(credentials.get("OPENAI_ACCESS_TOKEN") or credentials.get("OPENAI_SESSION_TOKEN"))
    has_account = bool(credentials.get("OPENAI_ACCOUNT_ID"))
    return {
        "saved": True,
        "account_id": credentials.get("OPENAI_ACCOUNT_ID", ""),
        "has_token": has_token,
        "has_account_id": has_account,
    }
