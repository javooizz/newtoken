"""Small outbound HTTP client with optional SOCKS5 support.

The project intentionally avoids third-party runtime dependencies.  This module
therefore implements the tiny SOCKS5 subset we need instead of requiring PySocks
or requests.
"""

from __future__ import annotations

import json
import os
import socket
import ssl
from dataclasses import dataclass
from http import client as http_client
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

DEFAULT_HTTP_TIMEOUT_SECONDS = 25
PROXY_ENV_KEYS = (
    "SUB2API_OUTBOUND_PROXY_URL",
    "SUB2API_SOCKS5_PROXY_URL",
    "SOCKS5_PROXY_URL",
    "ALL_PROXY",
    "all_proxy",
)
SOCKS5_STATUS_TEXT = {
    0x01: "general SOCKS server failure",
    0x02: "connection not allowed by ruleset",
    0x03: "network unreachable",
    0x04: "host unreachable",
    0x05: "connection refused",
    0x06: "TTL expired",
    0x07: "command not supported",
    0x08: "address type not supported",
}


@dataclass(frozen=True)
class Socks5ProxyConfig:
    """Parsed SOCKS5 proxy definition."""

    scheme: str
    host: str
    port: int
    username: str = ""
    password: str = ""


class Socks5ProxyError(RuntimeError):
    """Raised when a SOCKS5 proxy cannot establish the target connection."""


def get_configured_proxy_url(explicit_proxy_url: str | None = None) -> str:
    """Return the active outbound proxy URL, if one is configured."""

    explicit_text = str(explicit_proxy_url or "").strip()
    if explicit_text:
        return explicit_text
    for key in PROXY_ENV_KEYS:
        value = os.environ.get(key, "").strip()
        if value:
            return value
    return ""


def parse_socks5_proxy_url(proxy_url: str | None) -> Socks5ProxyConfig | None:
    """Parse a socks5/socks5h URL into a proxy config."""

    text = str(proxy_url or "").strip()
    if not text:
        return None
    parsed = urlsplit(text)
    scheme = parsed.scheme.lower()
    if scheme not in {"socks5", "socks5h"}:
        raise ValueError("出站代理只支持 socks5:// 或 socks5h:// 地址")
    if not parsed.hostname or not parsed.port:
        raise ValueError("SOCKS5 代理地址必须包含主机和端口")
    return Socks5ProxyConfig(
        scheme=scheme,
        host=parsed.hostname,
        port=int(parsed.port),
        username=unquote(parsed.username or ""),
        password=unquote(parsed.password or ""),
    )


def mask_proxy_url(proxy_url: str | None) -> str:
    """Mask credentials in a proxy URL for logs and WebUI display."""

    text = str(proxy_url or "").strip()
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
    except ValueError:
        return "<invalid proxy url>"
    if not parsed.username and not parsed.password:
        return text
    host = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    return urlunsplit((parsed.scheme, f"***:***@{host}{port}", parsed.path, "", ""))


def apply_proxy_env(proxy_url: str | None) -> None:
    """Apply the configured proxy URL to all supported env aliases."""

    text = str(proxy_url or "").strip()
    for key in PROXY_ENV_KEYS:
        if text:
            os.environ[key] = text
        else:
            os.environ.pop(key, None)


def _read_exact(sock: socket.socket, byte_count: int) -> bytes:
    """Read exactly byte_count bytes from a socket."""

    chunks: list[bytes] = []
    remaining = int(byte_count)
    while remaining > 0:
        chunk = sock.recv(remaining)
        if not chunk:
            raise Socks5ProxyError("SOCKS5 代理连接被提前关闭")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _encode_socks5_address(host: str) -> bytes:
    """Encode a target address for a SOCKS5 CONNECT request."""

    target = str(host or "").strip()
    try:
        return b"\x01" + socket.inet_aton(target)
    except OSError:
        pass
    try:
        return b"\x04" + socket.inet_pton(socket.AF_INET6, target)
    except OSError:
        pass
    encoded_host = target.encode("idna")
    if not encoded_host or len(encoded_host) > 255:
        raise Socks5ProxyError("SOCKS5 目标主机名长度无效")
    return b"\x03" + bytes([len(encoded_host)]) + encoded_host


def _connect_via_socks5(
    proxy: Socks5ProxyConfig,
    target_host: str,
    target_port: int,
    timeout: int | float | None,
) -> socket.socket:
    """Open a TCP socket to target_host:target_port through a SOCKS5 proxy."""

    sock = socket.create_connection((proxy.host, proxy.port), timeout=timeout)
    try:
        methods = [0x00]
        if proxy.username or proxy.password:
            methods.append(0x02)
        sock.sendall(b"\x05" + bytes([len(methods)]) + bytes(methods))
        version, selected_method = _read_exact(sock, 2)
        if version != 0x05:
            raise Socks5ProxyError("SOCKS5 代理响应版本无效")
        if selected_method == 0xFF:
            raise Socks5ProxyError("SOCKS5 代理没有接受可用的认证方式")
        if selected_method == 0x02:
            username = proxy.username.encode("utf-8")
            password = proxy.password.encode("utf-8")
            if len(username) > 255 or len(password) > 255:
                raise Socks5ProxyError("SOCKS5 用户名或密码过长")
            sock.sendall(
                b"\x01"
                + bytes([len(username)])
                + username
                + bytes([len(password)])
                + password
            )
            auth_version, auth_status = _read_exact(sock, 2)
            if auth_version != 0x01 or auth_status != 0x00:
                raise Socks5ProxyError("SOCKS5 用户名密码认证失败")
        elif selected_method != 0x00:
            raise Socks5ProxyError(f"SOCKS5 不支持的认证方式: {selected_method}")

        port_bytes = int(target_port).to_bytes(2, "big")
        sock.sendall(
            b"\x05\x01\x00"
            + _encode_socks5_address(target_host)
            + port_bytes
        )
        response_header = _read_exact(sock, 4)
        version = response_header[0]
        status = response_header[1]
        address_type = response_header[3]
        if version != 0x05:
            raise Socks5ProxyError("SOCKS5 CONNECT 响应版本无效")
        if status != 0x00:
            detail = SOCKS5_STATUS_TEXT.get(status, f"unknown status {status}")
            raise Socks5ProxyError(f"SOCKS5 CONNECT 失败: {detail}")
        if address_type == 0x01:
            _read_exact(sock, 4)
        elif address_type == 0x04:
            _read_exact(sock, 16)
        elif address_type == 0x03:
            domain_length = _read_exact(sock, 1)[0]
            _read_exact(sock, domain_length)
        else:
            raise Socks5ProxyError("SOCKS5 CONNECT 返回了未知地址类型")
        _read_exact(sock, 2)
        return sock
    except Exception:
        sock.close()
        raise


class SocksHTTPConnection(http_client.HTTPConnection):
    """HTTPConnection that connects through SOCKS5."""

    def __init__(self, host: str, port: int | None, *, proxy: Socks5ProxyConfig, timeout=None):
        super().__init__(host, port=port, timeout=timeout)
        self._socks_proxy = proxy

    def connect(self) -> None:
        self.sock = _connect_via_socks5(
            self._socks_proxy,
            self.host,
            self.port,
            self.timeout,
        )


class SocksHTTPSConnection(http_client.HTTPSConnection):
    """HTTPSConnection that connects through SOCKS5."""

    def __init__(self, host: str, port: int | None, *, proxy: Socks5ProxyConfig, timeout=None):
        super().__init__(host, port=port, timeout=timeout)
        self._socks_proxy = proxy

    def connect(self) -> None:
        raw_sock = _connect_via_socks5(
            self._socks_proxy,
            self.host,
            self.port,
            self.timeout,
        )
        self.sock = self._context.wrap_socket(raw_sock, server_hostname=self.host)


def _build_connection(
    scheme: str,
    host: str,
    port: int,
    *,
    proxy: Socks5ProxyConfig | None,
    timeout: int | float | None,
):
    """Create a suitable HTTP(S) connection."""

    if proxy is None:
        if scheme == "https":
            return http_client.HTTPSConnection(host, port=port, timeout=timeout)
        return http_client.HTTPConnection(host, port=port, timeout=timeout)
    if scheme == "https":
        return SocksHTTPSConnection(host, port=port, proxy=proxy, timeout=timeout)
    return SocksHTTPConnection(host, port=port, proxy=proxy, timeout=timeout)


def http_request_text(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | str | None = None,
    json_body: Any = None,
    timeout: int | float | None = DEFAULT_HTTP_TIMEOUT_SECONDS,
    proxy_url: str | None = None,
) -> tuple[int, str, str, dict[str, str]]:
    """Perform an HTTP request and return status, reason, text body and headers."""

    parsed = urlsplit(str(url or "").strip())
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("请求地址必须以 http:// 或 https:// 开头")
    host = parsed.hostname or ""
    if not host:
        raise ValueError("请求地址缺少主机名")
    port = parsed.port or (443 if scheme == "https" else 80)
    path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    request_headers = dict(headers or {})
    request_body: bytes | None = None
    if json_body is not None:
        request_body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    elif isinstance(body, str):
        request_body = body.encode("utf-8")
    elif body is not None:
        request_body = body
    if request_body is not None:
        request_headers.setdefault("Content-Length", str(len(request_body)))

    active_proxy_url = get_configured_proxy_url(proxy_url)
    proxy = parse_socks5_proxy_url(active_proxy_url) if active_proxy_url else None
    connection = _build_connection(
        scheme,
        host,
        port,
        proxy=proxy,
        timeout=timeout,
    )
    try:
        connection.request(method.upper(), path, body=request_body, headers=request_headers)
        response = connection.getresponse()
        raw_body = response.read()
        encoding = response.headers.get_content_charset() or "utf-8"
        body_text = raw_body.decode(encoding, errors="replace")
        response_headers = {
            str(key).lower(): str(value)
            for key, value in response.getheaders()
        }
        return response.status, response.reason, body_text, response_headers
    except (
        OSError,
        ssl.SSLError,
        socket.timeout,
        http_client.HTTPException,
        Socks5ProxyError,
    ) as exc:
        raise RuntimeError(f"网络请求失败: {exc}") from exc
    finally:
        connection.close()


def http_request_bytes(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | str | None = None,
    json_body: Any = None,
    timeout: int | float | None = DEFAULT_HTTP_TIMEOUT_SECONDS,
    proxy_url: str | None = None,
) -> tuple[int, str, bytes, dict[str, str]]:
    """Perform an HTTP request and return the raw response body."""

    parsed = urlsplit(str(url or "").strip())
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("请求地址必须以 http:// 或 https:// 开头")
    host = parsed.hostname or ""
    if not host:
        raise ValueError("请求地址缺少主机名")
    port = parsed.port or (443 if scheme == "https" else 80)
    path = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    request_headers = dict(headers or {})
    request_body: bytes | None = None
    if json_body is not None:
        request_body = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    elif isinstance(body, str):
        request_body = body.encode("utf-8")
    elif body is not None:
        request_body = body
    if request_body is not None:
        request_headers.setdefault("Content-Length", str(len(request_body)))

    active_proxy_url = get_configured_proxy_url(proxy_url)
    proxy = parse_socks5_proxy_url(active_proxy_url) if active_proxy_url else None
    connection = _build_connection(
        scheme,
        host,
        port,
        proxy=proxy,
        timeout=timeout,
    )
    try:
        connection.request(method.upper(), path, body=request_body, headers=request_headers)
        response = connection.getresponse()
        raw_body = response.read()
        response_headers = {
            str(key).lower(): str(value)
            for key, value in response.getheaders()
        }
        return response.status, response.reason, raw_body, response_headers
    except (
        OSError,
        ssl.SSLError,
        socket.timeout,
        http_client.HTTPException,
        Socks5ProxyError,
    ) as exc:
        raise RuntimeError(f"网络请求失败: {exc}") from exc
    finally:
        connection.close()


def request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    json_body: Any = None,
    timeout: int | float | None = DEFAULT_HTTP_TIMEOUT_SECONDS,
    proxy_url: str | None = None,
) -> tuple[int, str, Any]:
    """Perform an HTTP request and parse a JSON response when possible."""

    status_code, _reason, body_text, _headers = http_request_text(
        url,
        method=method,
        headers=headers,
        json_body=json_body,
        timeout=timeout,
        proxy_url=proxy_url,
    )
    payload = None
    if body_text.strip():
        try:
            payload = json.loads(body_text)
        except json.JSONDecodeError:
            payload = None
    return status_code, body_text, payload


def http_get_json(url: str, *, timeout: int = 15) -> dict[str, Any] | list[Any]:
    """Fetch a JSON document with the common outbound proxy settings."""

    status_code, reason, body_text, _headers = http_request_text(
        url,
        timeout=timeout,
        headers={"Accept": "application/json"},
    )
    if status_code < 200 or status_code >= 300:
        raise RuntimeError(f"HTTP {status_code} {reason}: {body_text[:500]}")
    return json.loads(body_text)


def download_file(url: str, target_path: str | Path, *, timeout: int = 120) -> Path:
    """Download a remote file using the common outbound proxy settings."""

    status_code, reason, raw_body, _headers = http_request_bytes(
        url,
        timeout=timeout,
    )
    if status_code < 200 or status_code >= 300:
        preview = raw_body.decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"下载失败 HTTP {status_code} {reason}: {preview}")
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw_body)
    return target
