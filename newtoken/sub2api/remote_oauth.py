# -*- coding: utf-8 -*-
"""Sub2API OpenAI OAuth 一键授权建号能力层。"""

from __future__ import annotations

import os
import random
import re
import shutil
import string
import subprocess
import time
from dataclasses import asdict, dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock, Thread, current_thread
from urllib.parse import parse_qs, urlsplit

from newtoken.sub2api.converter_core import request_json
from newtoken.sub2api.remote import (
    DEFAULT_OPENAI_ACCOUNT_STATUS,
    Sub2APIRemoteConfig,
    build_remote_config,
    build_remote_error_message,
    build_sub2api_admin_headers,
    build_sub2api_admin_url,
    bulk_update_remote_accounts,
    fetch_remote_groups,
    load_remote_import_defaults,
    parse_dotenv_file,
    parse_optional_int_text,
    resolve_env_file_path,
    unwrap_sub2api_response,
)

SUB2API_PROXIES_ALL_PATH = "/api/v1/admin/proxies/all"
SUB2API_PROXIES_CREATE_PATH = "/api/v1/admin/proxies"
SUB2API_OPENAI_GENERATE_AUTH_URL_PATH = "/api/v1/admin/openai/generate-auth-url"
SUB2API_OPENAI_CREATE_FROM_OAUTH_PATH = "/api/v1/admin/openai/create-from-oauth"

DEFAULT_OAUTH_PROXY_URL = ""
DEFAULT_OAUTH_PROXY_NAME = "default"
DEFAULT_OAUTH_REDIRECT_URI = "http://localhost:1455/auth/callback"
DEFAULT_OAUTH_ACCOUNT_CONCURRENCY = 10
DEFAULT_OAUTH_WS_MODE = "passthrough"
DEFAULT_OAUTH_GROUP_NAME = "cc"

_CODE_PARAM_PATTERN = re.compile(r"[?&]code=([^&#\\s]+)")
_KNOWN_BROWSER_CANDIDATES = (
    (
        "msedge",
        ["--new-window", "--inprivate"],
        (
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ),
    ),
    (
        "chrome",
        ["--new-window", "--incognito"],
        (
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ),
    ),
)


@dataclass
class ProxyDefinition:
    """保存解析后的代理信息。"""

    name: str
    protocol: str
    host: str
    port: int
    username: str = ""
    password: str = ""


@dataclass
class PendingOpenAIOAuthSession:
    """保存待完成的 OpenAI OAuth 授权任务。"""

    session_id: str
    state: str
    auth_url: str
    account_name: str
    proxy_id: int | None
    proxy_name: str
    group_ids: list[int]
    redirect_uri: str
    concurrency: int


@dataclass
class LocalOAuthCallbackBinding:
    """保存本地 OAuth 回调监听需要的绑定信息。"""

    host: str
    port: int
    path: str


class LocalOAuthCallbackListener:
    """监听本地 localhost OAuth 回调并把完整链接回传给上层。"""

    def __init__(self, redirect_uri: str, on_callback, on_error=None):
        self.binding = parse_local_callback_binding(redirect_uri)
        self.on_callback = on_callback
        self.on_error = on_error
        self._server = None
        self._thread = None
        self._handled = False
        self._lock = Lock()

    def start(self):
        """启动本地回调监听服务。"""

        if self._server:
            return
        listener = self

        class CallbackHandler(BaseHTTPRequestHandler):
            """处理本地 OAuth 回调请求。"""

            def do_GET(self):
                listener._handle_http_get(self)

            def log_message(self, _format, *_args):
                """关闭默认控制台日志，避免污染终端输出。"""

        self._server = ThreadingHTTPServer(
            (self.binding.host, self.binding.port),
            CallbackHandler,
        )
        self._thread = Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        """停止本地回调监听服务。"""

        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        if server:
            server.shutdown()
            server.server_close()
        if thread and thread.is_alive() and thread is not current_thread():
            thread.join(timeout=1)

    def _handle_http_get(self, handler):
        """处理浏览器打回本地的 OAuth 回调请求。"""

        parsed = urlsplit(handler.path)
        if parsed.path != self.binding.path:
            handler.send_response(404)
            handler.send_header("Content-Type", "text/plain; charset=utf-8")
            handler.end_headers()
            handler.wfile.write("Not Found".encode("utf-8"))
            return

        callback_url = self._build_callback_url(handler.headers.get("Host", ""), handler.path)
        try:
            self._dispatch_callback(callback_url)
            body = (
                "<html><body><h3>OAuth 回调已接收</h3>"
                "<p>可以关闭当前页面，程序会自动继续建号。</p></body></html>"
            )
            handler.send_response(200)
            handler.send_header("Content-Type", "text/html; charset=utf-8")
            handler.end_headers()
            handler.wfile.write(body.encode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            body = (
                "<html><body><h3>OAuth 回调接收失败</h3>"
                "<p>请回到程序窗口查看错误提示。</p></body></html>"
            )
            handler.send_response(500)
            handler.send_header("Content-Type", "text/html; charset=utf-8")
            handler.end_headers()
            handler.wfile.write(body.encode("utf-8"))
            if callable(self.on_error):
                Thread(target=self.on_error, args=(str(exc),), daemon=True).start()
        finally:
            Thread(target=self.stop, daemon=True).start()

    def _build_callback_url(self, host_header: str, request_path: str) -> str:
        """拼出浏览器实际回来的完整回调 URL。"""

        host = host_header.strip() or f"{self.binding.host}:{self.binding.port}"
        return f"http://{host}{request_path}"

    def _dispatch_callback(self, callback_url: str):
        """确保只回调一次，避免重复建号。"""

        with self._lock:
            if self._handled:
                return
            self._handled = True
        if callable(self.on_callback):
            Thread(target=self.on_callback, args=(callback_url,), daemon=True).start()


def parse_local_callback_binding(redirect_uri: str) -> LocalOAuthCallbackBinding:
    """把 localhost 回调地址解析为本地监听绑定信息。"""

    text = (redirect_uri or "").strip()
    if not text:
        raise ValueError("请先填写回调地址")
    parsed = urlsplit(text)
    if parsed.scheme.lower() != "http":
        raise ValueError("自动接收回调只支持 http://localhost 地址")
    host = (parsed.hostname or "").strip().lower()
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("自动接收回调只支持 localhost / 127.0.0.1 / ::1")
    if not parsed.port:
        raise ValueError("回调地址必须包含端口")
    path = parsed.path.strip() or "/"
    return LocalOAuthCallbackBinding(host=host, port=int(parsed.port), path=path)


def generate_random_oauth_account_name(prefix: str = "openai-oauth") -> str:
    """生成默认随机账号名称。"""

    timestamp = time.strftime("%Y%m%d-%H%M%S")
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=4))
    return f"{prefix}-{timestamp}-{suffix}"


def load_openai_oauth_defaults(env_path: str = ".env") -> dict[str, str]:
    """读取 OAuth 建号页的默认配置，避免把隐私值写进代码。"""

    remote_defaults = load_remote_import_defaults(env_path)
    values = parse_dotenv_file(resolve_env_file_path(env_path))
    return {
        "base_url": remote_defaults.get("base_url", "").strip(),
        "admin_api_key": remote_defaults.get("admin_api_key", "").strip(),
        "redirect_uri": (
            values.get("SUB2API_OAUTH_REDIRECT_URI", "").strip()
            or DEFAULT_OAUTH_REDIRECT_URI
        ),
        "proxy_id": (
            values.get("SUB2API_OAUTH_PROXY_ID", "").strip()
            or values.get("SUB2API_PROXY_ID", "").strip()
        ),
        "proxy_url": values.get("SUB2API_OAUTH_PROXY_URL", "").strip(),
        "proxy_name": (
            values.get("SUB2API_OAUTH_PROXY_NAME", "").strip()
            or DEFAULT_OAUTH_PROXY_NAME
        ),
        "group_ids": (
            values.get("SUB2API_OAUTH_GROUP_IDS", "").strip()
            or values.get("SUB2API_GROUP_IDS", "").strip()
        ),
        "group_name": (
            values.get("SUB2API_OAUTH_GROUP_NAME", "").strip()
            or DEFAULT_OAUTH_GROUP_NAME
        ),
        "concurrency": (
            values.get("SUB2API_OAUTH_ACCOUNT_CONCURRENCY", "").strip()
            or str(DEFAULT_OAUTH_ACCOUNT_CONCURRENCY)
        ),
    }


def parse_proxy_url(proxy_url: str, proxy_name: str = DEFAULT_OAUTH_PROXY_NAME) -> ProxyDefinition:
    """把代理 URL 拆成 Sub2API 代理创建参数。"""

    text = (proxy_url or "").strip()
    if not text:
        raise ValueError("请填写代理 URL")
    parsed = urlsplit(text)
    protocol = parsed.scheme.strip().lower()
    if protocol not in {"http", "https", "socks5", "socks5h"}:
        raise ValueError("代理 URL 只支持 http/https/socks5/socks5h")
    if not parsed.hostname or not parsed.port:
        raise ValueError("代理 URL 必须包含主机和端口")
    return ProxyDefinition(
        name=proxy_name,
        protocol=protocol,
        host=parsed.hostname.strip(),
        port=int(parsed.port),
        username=(parsed.username or "").strip(),
        password=(parsed.password or "").strip(),
    )


def normalize_oauth_concurrency(raw_value: int | str | None) -> int:
    """把 OAuth 并发值安全归一化。"""

    normalized = parse_optional_int_text(str(raw_value or "").strip())
    if normalized is None or normalized <= 0:
        return DEFAULT_OAUTH_ACCOUNT_CONCURRENCY
    return normalized


def extract_code_from_auth_input(auth_input: str) -> str:
    """从完整回调链接或纯 code 文本中提取授权码。"""

    text = (auth_input or "").strip()
    if not text:
        raise ValueError("请输入授权链接或 Code")
    if text.startswith("http://") or text.startswith("https://"):
        parsed = urlsplit(text)
        code_values = parse_qs(parsed.query).get("code") or []
        if code_values and code_values[0].strip():
            return code_values[0].strip()
    match = _CODE_PARAM_PATTERN.search(text)
    if match:
        return match.group(1).strip()
    if any(marker in text for marker in ("?", "&", "code=")):
        raise ValueError("未从回调链接中识别到 code 参数")
    return text


def extract_state_from_auth_url(auth_url: str) -> str:
    """从授权链接中提取 state 参数。"""

    parsed = urlsplit(auth_url)
    state_values = parse_qs(parsed.query).get("state") or []
    state = state_values[0].strip() if state_values else ""
    if not state:
        raise RuntimeError("授权链接中缺少 state 参数")
    return state


def fetch_remote_proxies(config: Sub2APIRemoteConfig) -> list[dict]:
    """读取远程全部代理列表。"""

    url = build_sub2api_admin_url(config.base_url, SUB2API_PROXIES_ALL_PATH)
    status_code, body_text, payload = request_json(
        url,
        headers=build_sub2api_admin_headers(config.admin_api_key),
    )
    if status_code < 200 or status_code >= 300:
        raise RuntimeError(
            build_remote_error_message("读取远程代理列表", status_code, body_text, payload)
        )
    data = unwrap_sub2api_response(payload)
    if not isinstance(data, list):
        raise RuntimeError("远程代理列表返回格式不符合预期")
    return [item for item in data if isinstance(item, dict)]


def find_remote_proxy_by_id(proxies: list[dict], proxy_id: int) -> dict | None:
    """按 ID 从远程代理列表里查找已存在代理。"""

    for item in proxies:
        try:
            current_proxy_id = int(item.get("id", 0) or 0)
        except (TypeError, ValueError):
            current_proxy_id = 0
        if current_proxy_id == int(proxy_id):
            return item
    return None


def find_matching_remote_proxy(proxies: list[dict], proxy_def: ProxyDefinition) -> dict | None:
    """优先按协议/主机/端口/用户名匹配已存在代理。"""

    endpoint_candidates = []
    exact_auth_candidates = []
    same_name_candidates = []
    target_host = proxy_def.host.lower()

    for item in proxies:
        protocol = str(item.get("protocol", "")).strip().lower()
        host = str(item.get("host", "")).strip().lower()
        username = str(item.get("username", "")).strip()
        password = str(item.get("password", "")).strip()
        name = str(item.get("name", "")).strip()
        port = int(item.get("port", 0) or 0)
        if protocol != proxy_def.protocol or host != target_host or port != proxy_def.port:
            continue
        endpoint_candidates.append(item)
        if username == proxy_def.username and password == proxy_def.password:
            exact_auth_candidates.append(item)
        if name == proxy_def.name:
            same_name_candidates.append(item)

    if proxy_def.username or proxy_def.password:
        if exact_auth_candidates:
            return exact_auth_candidates[0]
        return None

    if same_name_candidates:
        auth_enabled_candidates = [
            item
            for item in same_name_candidates
            if str(item.get("username", "")).strip() or str(item.get("password", "")).strip()
        ]
        if auth_enabled_candidates:
            return auth_enabled_candidates[0]
        return same_name_candidates[0]

    if exact_auth_candidates:
        return exact_auth_candidates[0]

    if endpoint_candidates:
        return endpoint_candidates[0]
    return None


def create_remote_proxy(config: Sub2APIRemoteConfig, proxy_def: ProxyDefinition) -> dict:
    """在远程创建一个代理。"""

    url = build_sub2api_admin_url(config.base_url, SUB2API_PROXIES_CREATE_PATH)
    request_body = asdict(proxy_def)
    status_code, body_text, payload = request_json(
        url,
        method="POST",
        headers=build_sub2api_admin_headers(config.admin_api_key),
        json_body=request_body,
    )
    if status_code < 200 or status_code >= 300:
        raise RuntimeError(
            build_remote_error_message("创建远程代理", status_code, body_text, payload)
        )
    data = unwrap_sub2api_response(payload)
    if not isinstance(data, dict):
        raise RuntimeError("远程代理创建成功但返回格式不符合预期")
    return data


def ensure_remote_proxy_by_url(
    config: Sub2APIRemoteConfig,
    proxy_url: str,
    proxy_name: str = DEFAULT_OAUTH_PROXY_NAME,
) -> dict:
    """查找或创建指定 URL 的 default 代理。"""

    proxy_def = parse_proxy_url(proxy_url, proxy_name=proxy_name)
    proxies = fetch_remote_proxies(config)
    matched = find_matching_remote_proxy(proxies, proxy_def)
    if matched:
        proxy_id = int(matched.get("id", 0) or 0)
        if proxy_id <= 0:
            raise RuntimeError("匹配到的远程代理缺少有效 ID")
        return {
            "proxy_id": proxy_id,
            "proxy_name": str(matched.get("name", "")).strip() or proxy_def.name,
            "created": False,
        }
    created_proxy = create_remote_proxy(config, proxy_def)
    proxy_id = int(created_proxy.get("id", 0) or 0)
    if proxy_id <= 0:
        raise RuntimeError("远程代理创建成功但未返回有效 ID")
    return {
        "proxy_id": proxy_id,
        "proxy_name": str(created_proxy.get("name", "")).strip() or proxy_def.name,
        "created": True,
    }


def resolve_remote_group_ids(
    config: Sub2APIRemoteConfig,
    explicit_group_ids: list[int] | None = None,
    preferred_group_name: str = DEFAULT_OAUTH_GROUP_NAME,
) -> list[int]:
    """解析 OAuth 建号要绑定的分组 ID。"""

    if explicit_group_ids is not None:
        return [int(item) for item in explicit_group_ids if int(item) > 0]
    target_group_name = str(preferred_group_name or "").strip().lower()
    if not target_group_name:
        return []
    for item in fetch_remote_groups(config):
        if not isinstance(item, dict):
            continue
        group_id = int(item.get("id", 0) or 0)
        name = str(item.get("name", "")).strip().lower()
        platform = str(item.get("platform", "")).strip().lower()
        if group_id <= 0 or name != target_group_name:
            continue
        if platform and platform != "openai":
            continue
        return [group_id]
    raise RuntimeError(
        f"未找到名为 {preferred_group_name} 的 OpenAI 分组，请先刷新分组列表或手动选择。"
    )


def build_openai_oauth_post_update_payload(
    account_id: int,
    proxy_id: int | None,
    group_ids: list[int],
    concurrency: int = DEFAULT_OAUTH_ACCOUNT_CONCURRENCY,
) -> dict:
    """构造 OpenAI OAuth 账号创建后的固定默认配置。"""

    payload = {
        "account_ids": [int(account_id)],
        "concurrency": int(concurrency),
        "status": DEFAULT_OPENAI_ACCOUNT_STATUS,
        "extra": {
            "openai_passthrough": True,
            "openai_oauth_responses_websockets_v2_enabled": True,
            "openai_oauth_responses_websockets_v2_mode": DEFAULT_OAUTH_WS_MODE,
            "codex_cli_only": True,
        },
    }
    if proxy_id is not None and int(proxy_id) > 0:
        payload["proxy_id"] = int(proxy_id)
    if group_ids:
        payload["group_ids"] = [int(item) for item in group_ids]
    return payload


def create_openai_oauth_pending_session(
    *,
    base_url: str,
    admin_api_key: str,
    proxy_id: int | str | None = None,
    proxy_url: str = DEFAULT_OAUTH_PROXY_URL,
    proxy_name: str = DEFAULT_OAUTH_PROXY_NAME,
    redirect_uri: str = DEFAULT_OAUTH_REDIRECT_URI,
    account_name: str = "",
    group_ids: list[int] | None = None,
    group_name: str = DEFAULT_OAUTH_GROUP_NAME,
    concurrency: int | str | None = None,
) -> dict:
    """创建待办授权任务并返回授权链接。"""

    remote_config = build_remote_config(
        base_url=base_url,
        admin_api_key=admin_api_key,
    )
    resolved_group_ids = resolve_remote_group_ids(
        remote_config,
        explicit_group_ids=group_ids,
        preferred_group_name=group_name,
    )
    selected_proxy_id = parse_optional_int_text(str(proxy_id or "").strip())
    if selected_proxy_id is not None and selected_proxy_id > 0:
        proxies = fetch_remote_proxies(remote_config)
        matched_proxy = find_remote_proxy_by_id(proxies, selected_proxy_id)
        proxy_info = {
            "proxy_id": selected_proxy_id,
            "proxy_name": (
                str(matched_proxy.get("name", "")).strip()
                if isinstance(matched_proxy, dict)
                else ""
            )
            or str(proxy_name or "").strip()
            or f"proxy-{selected_proxy_id}",
            "created": False,
        }
    elif (proxy_url or "").strip():
        proxy_info = ensure_remote_proxy_by_url(
            remote_config,
            proxy_url,
            proxy_name=proxy_name,
        )
    else:
        proxy_info = {
            "proxy_id": None,
            "proxy_name": "未指定代理",
            "created": False,
        }
    url = build_sub2api_admin_url(
        remote_config.base_url, SUB2API_OPENAI_GENERATE_AUTH_URL_PATH
    )
    request_body = {
        "redirect_uri": (redirect_uri or "").strip() or DEFAULT_OAUTH_REDIRECT_URI,
    }
    if proxy_info["proxy_id"] is not None:
        request_body["proxy_id"] = int(proxy_info["proxy_id"])
    status_code, body_text, payload = request_json(
        url,
        method="POST",
        headers=build_sub2api_admin_headers(remote_config.admin_api_key),
        json_body=request_body,
    )
    if status_code < 200 or status_code >= 300:
        raise RuntimeError(
            build_remote_error_message("生成授权链接", status_code, body_text, payload)
        )
    data = unwrap_sub2api_response(payload)
    if not isinstance(data, dict):
        raise RuntimeError("授权链接生成成功但返回格式不符合预期")
    auth_url = str(data.get("auth_url", "")).strip()
    session_id = str(data.get("session_id", "")).strip()
    if not auth_url or not session_id:
        raise RuntimeError("授权链接生成成功，但缺少 auth_url 或 session_id")
    pending_session = PendingOpenAIOAuthSession(
        session_id=session_id,
        state=extract_state_from_auth_url(auth_url),
        auth_url=auth_url,
        account_name=(account_name or "").strip() or generate_random_oauth_account_name(),
        proxy_id=proxy_info["proxy_id"],
        proxy_name=str(proxy_info["proxy_name"]).strip() or "未指定代理",
        group_ids=list(resolved_group_ids),
        redirect_uri=request_body["redirect_uri"],
        concurrency=normalize_oauth_concurrency(concurrency),
    )
    return {
        "remote_config": remote_config,
        "pending_session": pending_session,
        "proxy_created": bool(proxy_info["created"]),
        "proxy_id": proxy_info["proxy_id"],
        "proxy_name": pending_session.proxy_name,
    }


def complete_openai_oauth_account_creation(
    *,
    remote_config: Sub2APIRemoteConfig,
    pending_session: PendingOpenAIOAuthSession,
    auth_input: str,
) -> dict:
    """用用户粘贴的链接或 code 完成 OpenAI OAuth 建号。"""

    code = extract_code_from_auth_input(auth_input)
    url = build_sub2api_admin_url(
        remote_config.base_url, SUB2API_OPENAI_CREATE_FROM_OAUTH_PATH
    )
    request_body = {
        "session_id": pending_session.session_id,
        "code": code,
        "state": pending_session.state,
        "redirect_uri": pending_session.redirect_uri,
        "name": pending_session.account_name,
        "concurrency": pending_session.concurrency,
        "group_ids": list(pending_session.group_ids),
    }
    if pending_session.proxy_id is not None:
        request_body["proxy_id"] = pending_session.proxy_id
    status_code, body_text, payload = request_json(
        url,
        method="POST",
        headers=build_sub2api_admin_headers(remote_config.admin_api_key),
        json_body=request_body,
    )
    if status_code < 200 or status_code >= 300:
        raise RuntimeError(
            build_remote_error_message("OAuth 建号", status_code, body_text, payload)
        )
    data = unwrap_sub2api_response(payload)
    if not isinstance(data, dict):
        raise RuntimeError("OAuth 建号成功但返回格式不符合预期")
    account_id = int(data.get("id", 0) or 0)
    if account_id <= 0:
        raise RuntimeError("账号创建成功但未返回有效账号 ID")

    post_update_error = ""
    post_update = None
    try:
        post_update = bulk_update_remote_accounts(
            remote_config,
            build_openai_oauth_post_update_payload(
                account_id,
                pending_session.proxy_id,
                pending_session.group_ids,
                pending_session.concurrency,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        post_update_error = str(exc)

    return {
        "account_id": account_id,
        "account_name": str(data.get("name", "")).strip() or pending_session.account_name,
        "account_email": str(data.get("email", "")).strip(),
        "proxy_id": pending_session.proxy_id,
        "proxy_name": pending_session.proxy_name,
        "group_ids": list(pending_session.group_ids),
        "concurrency": pending_session.concurrency,
        "create_url": url,
        "post_update": post_update,
        "post_update_error": post_update_error,
        "created_account": data,
    }


def _resolve_browser_command() -> tuple[list[str], str] | tuple[None, str]:
    """解析可用的隐私浏览器启动命令。"""

    for executable_name, flags, path_candidates in _KNOWN_BROWSER_CANDIDATES:
        resolved = shutil.which(executable_name)
        if resolved:
            return [resolved, *flags], executable_name
        for candidate in path_candidates:
            if os.path.exists(candidate):
                return [candidate, *flags], executable_name
    return None, ""


def launch_private_auth_browser(
    auth_url: str,
    previous_process: subprocess.Popen | None = None,
) -> dict:
    """关闭本工具上一次授权浏览器并打开新的隐私窗口。"""

    if previous_process and previous_process.poll() is None:
        try:
            previous_process.terminate()
        except OSError:
            pass
    command_prefix, browser_name = _resolve_browser_command()
    if not command_prefix:
        return {"process": None, "browser_name": "", "opened": False}
    process = subprocess.Popen([*command_prefix, auth_url])
    return {"process": process, "browser_name": browser_name, "opened": True}
