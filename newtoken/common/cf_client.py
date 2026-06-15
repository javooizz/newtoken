"""curl_cffi based HTTP client with Cloudflare challenge bypass.

This module provides an HTTP transport layer that uses curl_cffi's
browser impersonation to bypass Cloudflare JS challenges and bot
detection.  It exposes the same function signatures as http_client.py
so existing callers can switch transparently.

Requires: curl_cffi
"""

from __future__ import annotations

import json
import os
import time
import random
from typing import Any

from curl_cffi import requests as curl_requests

DEFAULT_TIMEOUT = 30
CF_MARKERS = [
    "cf-browser-verification",
    "cf-im-under-attack",
    "cf-chl-bypass",
    "challenge-platform",
    "turnstile",
    "g-recaptcha",
    "Just a moment",
    "Checking your browser",
    "DDoS protection",
    "cf_captcha",
]

_IMPERSONATES = ["chrome120", "chrome124", "chrome131"]
_session: Any = None


def _get_session(proxy_url: str = "") -> Any:
    global _session
    if _session is not None:
        return _session
    _session = curl_requests.Session(impersonate=random.choice(_IMPERSONATES))
    _session.headers.update({
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    })
    if proxy_url:
        _session.proxies = {"http": proxy_url, "https": proxy_url}
    return _session


def is_cf_challenge(text: str, status: int = 0) -> bool:
    if status in (403, 503) or not text:
        return True
    lower = text.lower()
    return any(marker in lower for marker in CF_MARKERS)


def cf_request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    json_body: Any = None,
    timeout: int = DEFAULT_TIMEOUT,
    proxy_url: str = "",
    retries: int = 3,
) -> tuple[int, Any]:
    """HTTP request via curl_cffi with CF bypass, returning parsed JSON."""
    session = _get_session(_resolve_proxy(proxy_url))
    last_error = ""
    for attempt in range(retries):
        try:
            kwargs: dict[str, Any] = {"timeout": timeout, "headers": headers or {}}
            if json_body is not None:
                kwargs["json"] = json_body
            resp = getattr(session, method.lower())("get" if method.upper() == "GET" else method.lower(), url, **kwargs)
            if is_cf_challenge(resp.text or "", resp.status_code):
                if attempt < retries - 1:
                    _rotate_session()
                    time.sleep(random.uniform(1, 3))
                    continue
                raise RuntimeError(f"CF challenge detected at {url}, retries exhausted")
            try:
                return resp.status_code, resp.json()
            except Exception:
                return resp.status_code, None
        except Exception as exc:
            last_error = str(exc)
            if attempt < retries - 1:
                time.sleep(random.uniform(1, 2))
                continue
    raise RuntimeError(f"CF request failed: {last_error}")


def cf_request_text(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: bytes | str | None = None,
    json_body: Any = None,
    timeout: int = DEFAULT_TIMEOUT,
    proxy_url: str = "",
    retries: int = 3,
) -> tuple[int, str]:
    """HTTP request via curl_cffi with CF bypass, returning text body."""
    session = _get_session(_resolve_proxy(proxy_url))
    last_error = ""
    for attempt in range(retries):
        try:
            kwargs: dict[str, Any] = {"timeout": timeout, "headers": headers or {}}
            if json_body is not None:
                kwargs["json"] = json_body
            elif isinstance(body, str):
                kwargs["data"] = body.encode("utf-8")
            elif body is not None:
                kwargs["data"] = body
            resp = session.request(method.upper(), url, **kwargs)
            text = resp.text or ""
            if is_cf_challenge(text, resp.status_code):
                if attempt < retries - 1:
                    _rotate_session()
                    time.sleep(random.uniform(1, 3))
                    continue
                raise RuntimeError(f"CF challenge detected at {url}")
            return resp.status_code, text
        except Exception as exc:
            last_error = str(exc)
            if attempt < retries - 1 and "challenge" not in last_error.lower():
                time.sleep(random.uniform(1, 2))
                continue
    raise RuntimeError(f"CF request failed: {last_error}")


def _rotate_session() -> None:
    global _session
    _session = None


def _resolve_proxy(proxy_url: str) -> str:
    if proxy_url:
        return proxy_url
    for key in ("SUB2API_OUTBOUND_PROXY_URL", "SOCKS5_PROXY_URL", "ALL_PROXY"):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    return ""


def cf_test(url: str, *, timeout: int = 15) -> dict[str, Any]:
    """Test whether a URL is reachable through CF bypass."""
    t0 = time.time()
    status, data = cf_request_json(url, timeout=timeout, retries=2)
    elapsed = round((time.time() - t0) * 1000)
    return {"url": url, "status": status, "elapsed_ms": elapsed, "cf_bypassed": status < 400, "data": data}
