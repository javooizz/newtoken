"""HTTP server and routing layer for the dependency-light WebUI."""

from __future__ import annotations

import argparse
import json
import os
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from newtoken.common.http_client import mask_proxy_url
from newtoken.webui.api import dispatch_api
from newtoken.webui.config import (
    ENV_PATH,
    MAX_REQUEST_BODY_BYTES,
    SESSION_COOKIE_NAME,
    WEB_DEFAULT_HOST,
    WEB_DEFAULT_PORT,
    WebState,
)
from newtoken.webui.server_auth import build_login_html, oauth_callback_html
from newtoken.webui.page import build_index_html
from newtoken.webui.scheduler import WebScheduler
from newtoken.webui.utils import html_escape
from newtoken.webui.utils import json_safe

from newtoken.common.logging_setup import get_logger, setup_logging

logger = get_logger("webui.server")


class WebUIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the WebUI."""

    server_version = "Sub2APIWebUI/1.0"

    @property
    def state(self) -> WebState:
        return self.server.state  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args) -> None:
        logger.debug("%s %s", self.address_string(), fmt % args)

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/login":
            self._send_html(build_login_html())
            return
        if path == "/oauth/callback":
            self._handle_oauth_callback()
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
            scheduler = self.state.scheduler.snapshot() if self.state.scheduler else {}
            self._send_json({"tasks": self.state.tasks.list_recent(), "scheduler": scheduler})
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
            result = dispatch_api(path, payload, self.state)
            self._send_json({"ok": True, "result": json_safe(result)})
        except Exception as exc:  # noqa: BLE001
            logger.exception("API 处理失败 path=%s", path)
            self._send_json({"ok": False, "error": str(exc)}, status=400)

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
        self._send_html(build_login_html("密码错误"), status=401)

    def _handle_oauth_callback(self) -> None:
        host = self.headers.get("Host", "127.0.0.1:28463")
        html = oauth_callback_html(self.state, host, self.path)
        self._send_html(html)
        return None

    def _read_form_body(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
        return {key: values[0] if values else "" for key, values in parsed.items()}


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
    _outbound_proxy = str(values.get("SUB2API_OUTBOUND_PROXY_URL") or "").strip()
    if _outbound_proxy:
        # 供 converter_core 校验/续期对 OpenAI 端走 curl_cffi 指纹+代理（防把有效号误判死）
        os.environ["SUB2API_OUTBOUND_PROXY_URL"] = _outbound_proxy
    setup_logging(
        level=values.get("SUB2API_LOG_LEVEL"),
        log_dir=values.get("SUB2API_LOG_DIR"),
        max_bytes=values.get("SUB2API_LOG_MAX_BYTES"),
        backup_count=values.get("SUB2API_LOG_BACKUP_COUNT"),
    )
    host, port = resolve_server_bind(args, values)
    scheduler = WebScheduler(state)
    state.scheduler = scheduler
    server = Sub2APIWebServer((host, port), WebUIHandler, state)
    logger.info("Sub2API WebUI 监听 http://%s:%s", host, port)
    if values.get("SUB2API_OUTBOUND_PROXY_URL"):
        logger.info("出站代理 %s", mask_proxy_url(values.get("SUB2API_OUTBOUND_PROXY_URL")))
    if not state.auth_secret:
        logger.warning("SUB2API_WEB_SECRET 为空；WebUI 无密码保护。")
    scheduler.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("正在停止 Sub2API WebUI …")
    finally:
        scheduler.stop()
        server.server_close()
        state.tasks.shutdown(wait=False)
    return 0
