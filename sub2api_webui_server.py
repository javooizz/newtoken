"""HTTP server and routing layer for the dependency-light WebUI."""

from __future__ import annotations

import argparse
import json
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from sub2api_http_client import mask_proxy_url
from sub2api_webui_api import dispatch_api
from sub2api_webui_config import (
    ENV_PATH,
    MAX_REQUEST_BODY_BYTES,
    SESSION_COOKIE_NAME,
    WEB_DEFAULT_HOST,
    WEB_DEFAULT_PORT,
    WebState,
)
from sub2api_webui_page import build_index_html
from sub2api_webui_utils import json_safe

class WebUIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the WebUI."""

    server_version = "Sub2APIWebUI/1.0"

    @property
    def state(self) -> WebState:
        return self.server.state  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args) -> None:
        print(f"[WEBUI] {self.address_string()} {fmt % args}")

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/login":
            self._send_html(self._build_login_html())
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
            self._send_json({"tasks": self.state.tasks.list_recent()})
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
        self._send_html(self._build_login_html("密码错误"), status=401)

    def _read_form_body(self) -> dict[str, str]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        parsed = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
        return {key: values[0] if values else "" for key, values in parsed.items()}

    def _build_login_html(self, error_message: str = "") -> str:
        err = f"<p class='bad'>{html_escape(error_message)}</p>" if error_message else ""
        return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>登录</title>
<style>body{{font-family:system-ui;margin:0;background:#f7f8fa;color:#172033}}main{{max-width:420px;margin:14vh auto;background:white;border:1px solid #d8dde6;border-radius:8px;padding:22px}}input,button{{width:100%;padding:10px;margin-top:8px;font:inherit}}button{{background:#0f766e;color:white;border:0;border-radius:6px}}.bad{{color:#b42318}}</style></head>
<body><main><h1>Sub2API WebUI</h1>{err}<form method="post" action="/login"><label>Web 密码</label><input name="password" type="password" autofocus><button>登录</button></form></main></body></html>"""


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
    host, port = resolve_server_bind(args, values)
    server = Sub2APIWebServer((host, port), WebUIHandler, state)
    print(f"Sub2API WebUI listening on http://{host}:{port}")
    if values.get("SUB2API_OUTBOUND_PROXY_URL"):
        print(f"Outbound proxy: {mask_proxy_url(values.get('SUB2API_OUTBOUND_PROXY_URL'))}")
    if not state.auth_secret:
        print("Warning: SUB2API_WEB_SECRET is empty; WebUI has no password.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping Sub2API WebUI...")
    finally:
        server.server_close()
    return 0
