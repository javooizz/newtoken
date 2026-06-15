"""GPT 空间成员管理能力层。"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

LOCAL_PROJECT_DIR = Path(__file__).resolve().parent
if str(LOCAL_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(LOCAL_PROJECT_DIR))

from sub2api_runtime import get_app_dir  # noqa: E402
from sub2api_http_client import http_request_text  # noqa: E402

CHATGPT_API_BASE = "https://chatgpt.com/backend-api"
DEFAULT_SESSION_CACHE_FILE = ".chatgpt_session.json"
DEFAULT_USER_AGENT = "Mozilla/5.0"


@dataclass
class HarSession:
    """保存从 HAR 或缓存中恢复的 ChatGPT 会话。"""

    session_token: str = ""
    csrf_token: str = ""
    user_agent: str = DEFAULT_USER_AGENT
    cookie_str: str = ""

    @property
    def is_valid(self) -> bool:
        """判断当前会话是否可用。"""

        return bool(self.session_token)

    def to_dict(self) -> dict[str, str]:
        """转成可落盘结构。"""

        return {
            "session_token": self.session_token,
            "csrf_token": self.csrf_token,
            "user_agent": self.user_agent,
            "cookie_str": self.cookie_str,
        }


def resolve_session_cache_path(cache_path: str | None = None) -> str:
    """返回 GPT 会话缓存文件路径。"""

    if cache_path:
        return os.path.abspath(cache_path)
    return os.path.join(str(get_app_dir(__file__)), DEFAULT_SESSION_CACHE_FILE)


def save_session_cache(session: HarSession, cache_path: str | None = None) -> str:
    """写入本地会话缓存。"""

    if not session or not session.is_valid:
        raise ValueError("无有效 ChatGPT 会话，无法写入缓存")
    resolved_path = resolve_session_cache_path(cache_path)
    with open(resolved_path, "w", encoding="utf-8") as handle:
        json.dump(session.to_dict(), handle, ensure_ascii=False, indent=2)
    return resolved_path


def load_session_cache(cache_path: str | None = None) -> HarSession | None:
    """读取本地会话缓存。"""

    resolved_path = resolve_session_cache_path(cache_path)
    if not os.path.isfile(resolved_path):
        return None
    with open(resolved_path, "r", encoding="utf-8", errors="replace") as handle:
        raw_data = json.load(handle)
    if not isinstance(raw_data, dict):
        return None
    session = HarSession(
        session_token=str(raw_data.get("session_token", "")).strip(),
        csrf_token=str(raw_data.get("csrf_token", "")).strip(),
        user_agent=str(raw_data.get("user_agent", "")).strip() or DEFAULT_USER_AGENT,
        cookie_str=str(raw_data.get("cookie_str", "")).strip(),
    )
    if not session.is_valid:
        return None
    return session


def clear_session_cache(cache_path: str | None = None) -> bool:
    """删除本地会话缓存。"""

    resolved_path = resolve_session_cache_path(cache_path)
    if not os.path.isfile(resolved_path):
        return False
    os.remove(resolved_path)
    return True


def parse_har_file(file_path: str) -> HarSession:
    """从 HAR 文件提取 ChatGPT 会话。"""

    with open(file_path, "r", encoding="utf-8", errors="replace") as handle:
        har = json.load(handle)

    entries = har.get("log", {}).get("entries", [])
    session = HarSession()

    for entry in entries:
        request_data = entry.get("request", {})
        url = str(request_data.get("url") or "")
        if "chatgpt.com" not in url and "openai.com" not in url:
            continue

        for header in request_data.get("headers", []):
            name = str(header.get("name", "")).lower()
            value = str(header.get("value", ""))
            if name == "user-agent" and not session.user_agent:
                session.user_agent = value
            if name == "cookie":
                session.cookie_str = value
                for part in value.split(";"):
                    part = part.strip()
                    if part.startswith("__Secure-next-auth.session-token="):
                        session.session_token = part.split("=", 1)[1]
                    if part.startswith("__Host-next-auth.csrf-token="):
                        session.csrf_token = part.split("=", 1)[1]

        for header in entry.get("response", {}).get("headers", []):
            name = str(header.get("name", "")).lower()
            value = str(header.get("value", ""))
            if name == "set-cookie":
                if "__Secure-next-auth.session-token=" in value and not session.session_token:
                    match = re.search(
                        r"__Secure-next-auth\.session-token=([^;]+)",
                        value,
                    )
                    if match:
                        session.session_token = match.group(1)

        if session.session_token and session.csrf_token:
            break

    return session


def _build_headers(session: HarSession, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
    """构造 GPT 团队接口请求头。"""

    headers = {
        "Cookie": session.cookie_str
        or f"__Secure-next-auth.session-token={session.session_token}",
        "User-Agent": session.user_agent or DEFAULT_USER_AGENT,
        "Accept": "application/json",
    }
    if session.csrf_token:
        headers["X-Csrf-Token"] = session.csrf_token
    if extra_headers:
        headers.update(extra_headers)
    return headers


def _request_json(
    url: str,
    session: HarSession,
    *,
    method: str = "GET",
    body: dict | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict:
    """调用 GPT 团队接口并解析 JSON。"""

    request_body = None
    if body is not None:
        request_body = json.dumps(body).encode("utf-8")
    headers = _build_headers(session, extra_headers)
    if request_body is not None:
        headers["Content-Type"] = "application/json"
    status_code, reason, body_text, _response_headers = http_request_text(
        url,
        method=method,
        headers=headers,
        body=request_body,
        timeout=30,
    )
    if status_code < 200 or status_code >= 300:
        raise RuntimeError(f"HTTP {status_code} {reason}: {body_text[:500]}")
    return json.loads(body_text)


def fetch_team_members(session: HarSession) -> list[dict]:
    """拉取 GPT 空间成员列表。"""

    url = f"{CHATGPT_API_BASE}/organizations/members"
    try:
        data = _request_json(url, session)
    except RuntimeError:
        fallback_url = f"{CHATGPT_API_BASE}/accounts/check/v4-2024-10-25"
        fallback_data = _request_json(fallback_url, session)
        organizations = fallback_data.get("organizations", {}).get("data", [])
        if not organizations:
            return []
        data = _request_json(url, session)

    items = data.get("items") or data.get("members") or data.get("data") or []
    if isinstance(items, dict):
        items = list(items.values())
    if not isinstance(items, list):
        return []

    members = []
    for item in items:
        if not isinstance(item, dict):
            continue
        member = {
            "email": item.get("email") or item.get("user", {}).get("email", ""),
            "name": item.get("name") or item.get("user", {}).get("name", ""),
            "seat_type": item.get("seat_type") or item.get("seat", {}).get("type", ""),
            "status": item.get("status", ""),
        }
        if member["email"]:
            members.append(member)
    return members


def add_team_member(session: HarSession, email: str, seat_type: str = "codex") -> dict:
    """添加 GPT 空间成员。"""

    url = f"{CHATGPT_API_BASE}/organizations/members"
    body = {
        "email": email.strip(),
        "seat_type": seat_type,
    }
    try:
        return _request_json(url, session, method="POST", body=body)
    except RuntimeError:
        invite_url = f"{CHATGPT_API_BASE}/organizations/invites"
        invite_result = _request_json(
            invite_url,
            session,
            method="POST",
            body={"email": email.strip()},
        )
        invite_id = invite_result.get("invite_id") or invite_result.get("id", "")
        if invite_id:
            assign_url = f"{CHATGPT_API_BASE}/organizations/invites/{invite_id}/assign-seat"
            try:
                return _request_json(
                    assign_url,
                    session,
                    method="POST",
                    body={"seat_type": seat_type},
                )
            except RuntimeError:
                pass
        return invite_result
