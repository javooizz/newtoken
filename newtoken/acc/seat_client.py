"""本地席位管理脚本。

用法示例：
  python change_seat_cli.py list --access-token <AT> --account-id <ACCOUNT_ID>
  python change_seat_cli.py toggle --access-token <AT> --account-id <ACCOUNT_ID> --email user@example.com
  python change_seat_cli.py set-seat --access-token <AT> --account-id <ACCOUNT_ID> --user-id <USER_ID> --seat-type usage_based
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib import error, parse

from newtoken.common.http_client import http_request_text

CLIENT_BUILD_NUMBER = "7295677"
CLIENT_VERSION = "prod-6fad808b4f8e564864e3be9a01e210e4d978ffac"
DEFAULT_BASE_URL = "https://chatgpt.com"
DEFAULT_PAGE_SIZE = 25
DEFAULT_ACCEPT_LANGUAGE = "zh-CN,zh;q=0.9"
DEFAULT_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
)
DEFAULT_SEAT_UPDATE_RETRY_COUNT = 5
DEFAULT_SEAT_RETRY_DELAY_SECONDS = 0.5
DEFAULT_TRANSPORT_RETRY_COUNT = 3
DEFAULT_TRANSPORT_RETRY_DELAY_SECONDS = 0.5
DEFAULT_INVITE_ROLE = "standard-user"
DEFAULT_INVITE_SEAT_TYPE = "usage_based"
CHATGPT_SEAT_TYPE = "default"
CODEX_SEAT_TYPE = "usage_based"
CHATGPT_SEAT_LIMIT = 2
SEAT_LABELS = {
    CHATGPT_SEAT_TYPE: "ChatGPT",
    CODEX_SEAT_TYPE: "Codex",
    "null": "ChatGPT",
}


class SeatApiError(RuntimeError):
    """统一封装远端接口错误。"""


TRANSIENT_NETWORK_EXCEPTIONS = (
    error.URLError,
    http.client.RemoteDisconnected,
    ConnectionResetError,
    TimeoutError,
)


@dataclass(slots=True)
class Config:
    """脚本运行配置。"""

    access_token: str
    account_id: str
    device_id: str
    session_token: str
    client_build_number: str
    client_version: str
    base_url: str


class SeatClient:
    """负责访问成员列表和席位修改接口。"""

    def __init__(self, config: Config) -> None:
        """保存配置并复用固定请求头。"""
        self.config = config

    def list_users(self, page: int, limit: int, query: str = "") -> dict[str, Any]:
        """分页读取账号成员列表。"""
        offset = page * limit
        encoded_query = parse.quote(query)
        path = (
            f"/backend-api/accounts/{parse.quote(self.config.account_id)}/users"
            f"?offset={offset}&limit={limit}&query={encoded_query}"
        )
        response = self._request_json("GET", path)
        return {
            "items": response.get("items", []),
            "total": int(response.get("total", 0)),
            "page": page,
            "limit": limit,
        }

    def update_user_seat(self, user_id: str, seat_type: str) -> dict[str, Any]:
        """把目标用户改成指定席位类型。"""
        path = (
            f"/backend-api/accounts/{parse.quote(self.config.account_id)}"
            f"/users/{parse.quote(user_id)}"
        )
        payload = {"seat_type": seat_type}
        return self._request_json("PATCH", path, payload)

    def invite_user(
        self,
        email: str,
        role: str = DEFAULT_INVITE_ROLE,
        seat_type: str = DEFAULT_INVITE_SEAT_TYPE,
        resend_emails: bool = True,
    ) -> dict[str, Any]:
        """邀请一个新成员并指定默认席位。"""
        normalized_email = email.strip().lower()
        if not normalized_email:
            raise SeatApiError("缺少待邀请邮箱。")
        path = f"/backend-api/accounts/{parse.quote(self.config.account_id)}/invites"
        payload = {
            "email_addresses": [normalized_email],
            "role": role,
            "seat_type": seat_type,
            "resend_emails": resend_emails,
        }
        response = self._request_json("POST", path, payload)
        errored_emails = response.get("errored_emails", [])
        if isinstance(errored_emails, list) and errored_emails:
            raise SeatApiError(f"邀请失败：{', '.join(str(item) for item in errored_emails)}")
        return response

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """发起 HTTP 请求并把 JSON 响应转成字典。"""
        url = f"{self.config.base_url}{path}"
        headers = build_headers(self.config)
        return request_json_with_retry(url=url, method=method, headers=headers, payload=payload)


def normalize_base_url(base_url: str) -> str:
    """清理 base_url 末尾斜杠。"""
    cleaned = (base_url or DEFAULT_BASE_URL).strip()
    return cleaned.rstrip("/")


def build_session_cookie(session_token: str) -> str:
    """根据 session token 构造 Cookie 头。"""
    token = session_token.strip()
    return (
        f"__Secure-next-auth.session-token={token}; "
        f"next-auth.session-token={token}"
    )


def build_headers(config: Config) -> dict[str, str]:
    """按扩展现有逻辑构造请求头。"""
    headers = {
        "accept": "*/*",
        "accept-language": DEFAULT_ACCEPT_LANGUAGE,
        "account-id": config.account_id,
        "oai-client-build-number": config.client_build_number or CLIENT_BUILD_NUMBER,
        "oai-client-version": config.client_version or CLIENT_VERSION,
        "referer": f"{normalize_base_url(config.base_url)}/",
        "sec-fetch-dest": "empty",
        "sec-fetch-mode": "cors",
        "sec-fetch-site": "same-origin",
        "user-agent": DEFAULT_BROWSER_USER_AGENT,
    }
    if config.access_token:
        headers["authorization"] = f"Bearer {config.access_token}"
    if config.device_id:
        headers["oai-device-id"] = config.device_id
    if config.session_token:
        headers["cookie"] = build_session_cookie(config.session_token)
    return headers


def decode_json_response(raw_text: str) -> dict[str, Any]:
    """把 JSON 字符串解析成字典。"""
    if not raw_text:
        return {}
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        preview = raw_text[:160]
        raise SeatApiError(f"接口返回的不是 JSON：{preview}") from exc
    if not isinstance(parsed, dict):
        raise SeatApiError("接口返回的 JSON 不是对象。")
    return parsed


def open_json_request(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """发起通用 JSON 请求。"""
    return request_json_with_retry(url=url, method=method, headers=headers, payload=payload)


def request_json_with_retry(
    url: str,
    method: str,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    max_attempts: int = DEFAULT_TRANSPORT_RETRY_COUNT,
    retry_delay_seconds: float = DEFAULT_TRANSPORT_RETRY_DELAY_SECONDS,
) -> dict[str, Any]:
    """发起 JSON 请求，并在瞬时网络异常时自动重试。"""
    request_headers = dict(headers or {})
    body: bytes | None = None

    if payload is not None:
        request_headers["content-type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")

    last_error: BaseException | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            status_code, reason, raw_text, _headers = http_request_text(
                url,
                method=method,
                headers=request_headers,
                body=body,
            )
            if status_code < 200 or status_code >= 300:
                raise SeatApiError(extract_error_message(status_code, reason, raw_text))
            return decode_json_response(raw_text)
        except SeatApiError:
            raise
        except TRANSIENT_NETWORK_EXCEPTIONS + (RuntimeError,) as exc:
            last_error = exc
            if attempt >= max_attempts:
                break
            time.sleep(retry_delay_seconds)

    if isinstance(last_error, error.URLError):
        raise SeatApiError(f"网络请求失败：{last_error.reason}") from last_error
    if last_error is not None:
        raise SeatApiError(f"网络请求失败：{last_error}") from last_error
    raise SeatApiError("网络请求失败：未知错误。")


def extract_error_message(status_code: int, reason: str, raw_text: str) -> str:
    """从错误响应中尽量提取可读提示。"""
    try:
        data = json.loads(raw_text) if raw_text else {}
    except json.JSONDecodeError:
        data = {}
    if isinstance(data, dict):
        message = data.get("error", {}).get("message") or data.get("message")
        if message:
            return str(message)
    return f"{status_code} {reason}"


def next_seat_type(current: str | None) -> str:
    """根据当前席位推导切换后的目标席位。"""

    return CODEX_SEAT_TYPE


def is_chatgpt_seat_type(seat_type: str | None) -> bool:
    """判断一个 seat_type 是否占用 ChatGPT 席位。"""

    return str(seat_type or "").strip().lower() in {CHATGPT_SEAT_TYPE, "null"}


def is_codex_seat_type(seat_type: str | None) -> bool:
    """判断一个 seat_type 是否是 Codex。"""

    return str(seat_type or "").strip().lower() == CODEX_SEAT_TYPE


def count_chatgpt_seats(users: list[dict[str, Any]]) -> int:
    """统计当前成员列表中 ChatGPT 席位数量。"""

    return sum(1 for user in users if is_chatgpt_seat_type(user.get("seat_type")))


def select_chatgpt_overflow_users(
    users: list[dict[str, Any]],
    *,
    limit: int = CHATGPT_SEAT_LIMIT,
) -> list[dict[str, Any]]:
    """找出超过上限后必须降为 Codex 的 ChatGPT 成员。"""

    chatgpt_users = [
        user
        for user in users
        if is_chatgpt_seat_type(user.get("seat_type"))
    ]
    if len(chatgpt_users) <= limit:
        return []
    return chatgpt_users[limit:]


def enforce_chatgpt_seat_limit(
    client: SeatClient,
    *,
    users: list[dict[str, Any]] | None = None,
    limit: int = CHATGPT_SEAT_LIMIT,
) -> dict[str, Any]:
    """把现有成员强制收敛到 ChatGPT 席位不超过 limit。"""

    current_users = list(users) if users is not None else list_all_users(client)
    overflow_users = select_chatgpt_overflow_users(current_users, limit=limit)
    changed_users: list[dict[str, Any]] = []
    for user in overflow_users:
        result = ensure_user_seat(
            client,
            user_id=str(user.get("id", "")),
            email=None,
            target_seat_type=CODEX_SEAT_TYPE,
        )
        changed_users.append(
            {
                "email": user.get("email") or "",
                "user_id": user.get("id") or "",
                "seat_result": result,
            }
        )
    refreshed_users = list_all_users(client)
    return {
        "limit": int(limit),
        "overflow_count": len(overflow_users),
        "changed_users": changed_users,
        "users": refreshed_users,
        "chatgpt_count": count_chatgpt_seats(refreshed_users),
    }


def seat_label(seat_type: str | None) -> str:
    """把席位枚举转成更好读的文案。"""
    if seat_type is None:
        return "-"
    return SEAT_LABELS.get(seat_type, seat_type)


def fetch_session_info(base_url: str, session_token: str) -> dict[str, Any]:
    """使用 session token 拉取当前会话。"""
    url = f"{normalize_base_url(base_url)}/api/auth/session"
    return open_json_request(
        url=url,
        method="GET",
        headers={
            "cookie": build_session_cookie(session_token),
            "accept": "application/json",
        },
    )


def extract_session_credentials(session_data: dict[str, Any]) -> tuple[str, str]:
    """从会话响应中提取 access token 和 account_id。"""
    access_token = str(session_data.get("accessToken") or "").strip()
    account = session_data.get("account") or {}
    account_id = str(account.get("id") or "").strip() if isinstance(account, dict) else ""

    if not access_token:
        raise SeatApiError("会话接口没有返回 accessToken。")
    if not account_id:
        raise SeatApiError("会话接口没有返回 account.id。")

    return access_token, account_id


def parse_har_session_bundle(har_text: str) -> dict[str, str]:
    """从 HAR 中提取会话与成员接口关键字段。"""
    try:
        data = json.loads(har_text)
    except json.JSONDecodeError as exc:
        raise SeatApiError("HAR 不是有效 JSON。") from exc

    entries = data.get("log", {}).get("entries", [])
    if not isinstance(entries, list):
        raise SeatApiError("HAR 结构无效，缺少 log.entries。")

    users_entry: dict[str, Any] | None = None
    session_entry: dict[str, Any] | None = None

    for entry in entries:
        request_data = entry.get("request", {})
        url = str(request_data.get("url") or "")
        status = int(entry.get("response", {}).get("status") or 0)
        if status != 200:
            continue
        if "/backend-api/accounts/" in url and "/users?" in url and users_entry is None:
            users_entry = entry
        if url.endswith("/api/auth/session") and session_entry is None:
            session_entry = entry
        if users_entry is not None and session_entry is not None:
            break

    if users_entry is None and session_entry is None:
        raise SeatApiError("HAR 中未找到可用的成员列表或会话请求。")

    payload = {
        "warningBanner": "",
        "accountId": "",
        "deviceId": "",
        "accessToken": "",
        "sessionToken": "",
        "authProvider": "",
        "clientBuildNumber": "",
        "clientVersion": "",
    }

    if users_entry is not None:
        request_headers = {
            header.get("name", "").lower(): str(header.get("value") or "")
            for header in users_entry.get("request", {}).get("headers", [])
        }
        payload["accountId"] = request_headers.get("account-id", "").strip()
        payload["deviceId"] = request_headers.get("oai-device-id", "").strip()
        payload["clientBuildNumber"] = request_headers.get("oai-client-build-number", "").strip()
        payload["clientVersion"] = request_headers.get("oai-client-version", "").strip()

    if session_entry is not None:
        session_text = str(session_entry.get("response", {}).get("content", {}).get("text") or "")
        session_data = decode_json_response(session_text)
        payload["warningBanner"] = str(session_data.get("WARNING_BANNER") or "").strip()
        payload["accessToken"] = str(session_data.get("accessToken") or "").strip()
        payload["sessionToken"] = str(session_data.get("sessionToken") or "").strip()
        payload["authProvider"] = str(session_data.get("authProvider") or "").strip()
        account = session_data.get("account") or {}
        if isinstance(account, dict) and not payload["accountId"]:
            payload["accountId"] = str(account.get("id") or "").strip()

    if not payload["accountId"]:
        raise SeatApiError("HAR 中未提取到 account_id。")
    if not payload["sessionToken"] and not payload["accessToken"]:
        raise SeatApiError("HAR 中未提取到 sessionToken 或 accessToken。")

    return payload


def resolve_target_user(
    users: list[dict[str, Any]],
    user_id: str | None,
    email: str | None,
) -> dict[str, Any]:
    """按用户 ID 或邮箱定位目标成员。"""
    if user_id:
        for user in users:
            if user.get("id") == user_id:
                return user
        raise SeatApiError(f"未找到 user_id={user_id} 的用户。")

    if email:
        lowered_email = email.lower()
        for user in users:
            current = str(user.get("email", "")).lower()
            if current == lowered_email:
                return user
        raise SeatApiError(f"未找到 email={email} 的用户。")

    raise SeatApiError("必须提供 --user-id 或 --email。")


def find_user(client: SeatClient, user_id: str | None, email: str | None) -> dict[str, Any]:
    """自动翻页查找目标用户，避免只命中第一页。"""
    page = 0
    limit = 100

    while True:
        result = client.list_users(page=page, limit=limit, query="")
        try:
            return resolve_target_user(result["items"], user_id, email)
        except SeatApiError:
            scanned = (page + 1) * limit
            if scanned >= result["total"]:
                break
            page += 1

    if user_id:
        raise SeatApiError(f"未找到 user_id={user_id} 的用户。")
    if email:
        raise SeatApiError(f"未找到 email={email} 的用户。")
    raise SeatApiError("必须提供 --user-id 或 --email。")


def list_all_users(client: SeatClient, query: str = "") -> list[dict[str, Any]]:
    """拉取完整成员列表，用于底层席位策略校验。"""

    users: list[dict[str, Any]] = []
    page = 0
    limit = 100
    while True:
        result = client.list_users(page=page, limit=limit, query=query)
        items = list(result.get("items") or [])
        users.extend(items)
        total = int(result.get("total", len(users)) or len(users))
        if not items or len(users) >= total:
            break
        page += 1
    return users


def enforce_seat_architecture_policy(
    *,
    users: list[dict[str, Any]],
    target_user: dict[str, Any],
    target_seat_type: str,
) -> None:
    """底层席位策略：Codex 不升 ChatGPT，ChatGPT 总数不超过 2。"""

    current_seat_type = str(target_user.get("seat_type") or "")
    if target_seat_type != CHATGPT_SEAT_TYPE:
        return
    if is_codex_seat_type(current_seat_type):
        raise SeatApiError("底层策略已禁止 Codex 席位改回 ChatGPT。")
    if is_chatgpt_seat_type(current_seat_type):
        return
    current_chatgpt_count = count_chatgpt_seats(users)
    if current_chatgpt_count >= CHATGPT_SEAT_LIMIT:
        raise SeatApiError(
            f"底层策略限制 ChatGPT 席位最多 {CHATGPT_SEAT_LIMIT} 个，当前已达上限。"
        )


def ensure_user_seat(
    client: SeatClient,
    user_id: str | None,
    email: str | None,
    target_seat_type: str,
    max_attempts: int | None = None,
    progress_callback: Callable[[int, str, str], None] | None = None,
) -> dict[str, Any]:
    """确保目标用户最终处于指定席位，必要时自动重试。"""
    if target_seat_type == CHATGPT_SEAT_TYPE:
        users = list_all_users(client)
        user = resolve_target_user(users, user_id, email)
        enforce_seat_architecture_policy(
            users=users,
            target_user=user,
            target_seat_type=target_seat_type,
        )
    else:
        user = find_user(client, user_id=user_id, email=email)
    current_seat_type = str(user.get("seat_type") or "")
    identifier = str(user.get("email") or user.get("id") or "")

    if current_seat_type == target_seat_type:
        return {
            "user": user,
            "attempts": 0,
            "changed": False,
            "targetSeatType": target_seat_type,
            "identifier": identifier,
        }

    latest_user = user
    attempt = 0

    while True:
        attempt += 1
        if progress_callback is not None:
            progress_callback(attempt, identifier, target_seat_type)
        retryable_error_seen = False
        try:
            response = client.update_user_seat(str(user.get("id", "")), target_seat_type)
            if response.get("success") is not True:
                raise SeatApiError("接口未返回 success=true。")
        except SeatApiError as exc:
            if not is_retryable_seat_update_error(exc):
                raise
            retryable_error_seen = True

        try:
            latest_user = find_user(client, user_id=str(user.get("id", "")), email=None)
        except SeatApiError as exc:
            if not is_retryable_seat_update_error(exc):
                raise
            retryable_error_seen = True
        else:
            if str(latest_user.get("seat_type") or "") == target_seat_type:
                return {
                    "user": latest_user,
                    "attempts": attempt,
                    "changed": True,
                    "targetSeatType": target_seat_type,
                    "identifier": identifier,
                }

        if max_attempts is not None and attempt >= max_attempts:
            current_label = seat_label(latest_user.get("seat_type"))
            target_label = seat_label(target_seat_type)
            raise SeatApiError(
                f"{identifier} 重试 {max_attempts} 次后仍未变为 {target_label}，当前仍是 {current_label}。"
            )

        if retryable_error_seen or str(latest_user.get("seat_type") or "") != target_seat_type:
            time.sleep(DEFAULT_SEAT_RETRY_DELAY_SECONDS)


def is_retryable_seat_update_error(error_obj: SeatApiError) -> bool:
    """识别是否属于当前业务允许持续重试的设位错误。"""
    message = str(error_obj).strip().lower()
    return (
        ("400" in message and "bad request" in message)
        or ("403" in message and "forbidden" in message)
    )


def render_users_table(users: list[dict[str, Any]], page: int, total: int, limit: int) -> str:
    """把用户列表渲染成终端表格。"""
    if not users:
        return "暂无用户数据"

    headers = ("user_id", "email", "seat_type")
    rows = [
        (
            str(user.get("id", "")),
            str(user.get("email", "")),
            seat_label(user.get("seat_type")),
        )
        for user in users
    ]
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]

    def format_row(values: tuple[str, str, str]) -> str:
        """把一行数据按列宽补齐。"""
        return " | ".join(
            values[index].ljust(widths[index]) for index in range(len(values))
        )

    divider = "-+-".join("-" * width for width in widths)
    lines = [f"第 {page + 1} 页，每页 {limit} 条，共 {total} 条"]
    lines.append(format_row(headers))
    lines.append(divider)
    lines.extend(format_row(row) for row in rows)
    return "\n".join(lines)


def load_config(args: argparse.Namespace) -> Config:
    """从命令行参数和环境变量合并配置。"""
    access_token = (args.access_token or os.getenv("OPENAI_ACCESS_TOKEN", "")).strip()
    account_id = (args.account_id or os.getenv("OPENAI_ACCOUNT_ID", "")).strip()
    device_id = (args.device_id or os.getenv("OPENAI_DEVICE_ID", "")).strip()
    session_token = (args.session_token or os.getenv("OPENAI_SESSION_TOKEN", "")).strip()
    client_build_number = (
        args.client_build_number or os.getenv("OPENAI_CLIENT_BUILD_NUMBER", CLIENT_BUILD_NUMBER)
    ).strip()
    client_version = (
        args.client_version or os.getenv("OPENAI_CLIENT_VERSION", CLIENT_VERSION)
    ).strip()
    base_url = normalize_base_url(args.base_url or os.getenv("OPENAI_BASE_URL", DEFAULT_BASE_URL))

    if not access_token and not session_token:
        raise SeatApiError("缺少 access token 或 session token。")
    if not account_id:
        raise SeatApiError("缺少 account_id。请传 --account-id 或设置 OPENAI_ACCOUNT_ID。")

    return Config(
        access_token=access_token,
        account_id=account_id,
        device_id=device_id,
        session_token=session_token,
        client_build_number=client_build_number,
        client_version=client_version,
        base_url=base_url,
    )


def add_common_auth_arguments(parser: argparse.ArgumentParser) -> None:
    """给子命令补齐鉴权相关参数。"""
    parser.add_argument("--access-token", help="OpenAI access token，可用环境变量 OPENAI_ACCESS_TOKEN")
    parser.add_argument("--account-id", help="OpenAI account_id，可用环境变量 OPENAI_ACCOUNT_ID")
    parser.add_argument("--device-id", help="可选，对应浏览器 localStorage 中的 oai-did")
    parser.add_argument("--session-token", help="可选，会优先用 Cookie 会话鉴权")
    parser.add_argument("--client-build-number", help="可选，对应 oai-client-build-number")
    parser.add_argument("--client-version", help="可选，对应 oai-client-version")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="接口域名，默认 https://chatgpt.com")


def build_parser() -> argparse.ArgumentParser:
    """构建命令行解析器。"""
    parser = argparse.ArgumentParser(description="本地管理 ChatGPT/Codex 席位")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="查看成员列表")
    add_common_auth_arguments(list_parser)
    list_parser.add_argument("--page", type=int, default=0, help="页码，从 0 开始")
    list_parser.add_argument("--limit", type=int, default=DEFAULT_PAGE_SIZE, help="每页条数")
    list_parser.add_argument("--query", default="", help="可选搜索关键字")

    toggle_parser = subparsers.add_parser("toggle", help="按策略把目标成员改为 Codex")
    add_common_auth_arguments(toggle_parser)
    toggle_parser.add_argument("--user-id", help="目标用户 ID")
    toggle_parser.add_argument("--email", help="目标用户邮箱")

    set_parser = subparsers.add_parser("set-seat", help="直接设置目标席位")
    add_common_auth_arguments(set_parser)
    set_parser.add_argument("--user-id", help="目标用户 ID")
    set_parser.add_argument("--email", help="目标用户邮箱")
    set_parser.add_argument(
        "--seat-type",
        choices=("default", "usage_based"),
        required=True,
        help="usage_based=Codex；default 会被底层策略严格限制",
    )
    return parser


def command_list(client: SeatClient, args: argparse.Namespace) -> str:
    """执行成员列表查询。"""
    if args.page < 0:
        raise SeatApiError("--page 不能小于 0。")
    if args.limit <= 0:
        raise SeatApiError("--limit 必须大于 0。")

    result = client.list_users(page=args.page, limit=args.limit, query=args.query)
    return render_users_table(
        users=result["items"],
        page=result["page"],
        total=result["total"],
        limit=result["limit"],
    )


def command_toggle(client: SeatClient, args: argparse.Namespace) -> str:
    """执行席位切换。"""
    user = find_user(client, args.user_id, args.email)
    target_seat_type = next_seat_type(user.get("seat_type"))
    result = ensure_user_seat(
        client,
        user_id=str(user.get("id", "")),
        email=None,
        target_seat_type=target_seat_type,
    )
    return (
        f"{result['identifier']} 已从 {seat_label(user.get('seat_type'))} "
        f"切换为 {seat_label(target_seat_type)}。"
    )


def command_set_seat(client: SeatClient, args: argparse.Namespace) -> str:
    """执行指定席位设置。"""
    result = ensure_user_seat(
        client,
        user_id=args.user_id,
        email=args.email,
        target_seat_type=args.seat_type,
    )
    if not result["changed"]:
        return f"{result['identifier']} 已是 {seat_label(args.seat_type)}。"
    return (
        f"{result['identifier']} 已设置为 {seat_label(args.seat_type)}，"
        f"共尝试 {result['attempts']} 次。"
    )


def main(argv: list[str] | None = None) -> int:
    """脚本主入口。"""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = load_config(args)
        client = SeatClient(config)
        if args.command == "list":
            output = command_list(client, args)
        elif args.command == "toggle":
            output = command_toggle(client, args)
        else:
            output = command_set_seat(client, args)
        print(output)
        return 0
    except SeatApiError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
