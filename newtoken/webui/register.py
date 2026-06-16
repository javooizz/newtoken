"""OpenAI team account registration engine for the WebUI.

Ports the core registration pipeline from team/ChatGPT_team.py into the WebUI
architecture so the auto-maintenance scheduler can register fresh accounts when
the pool drops below threshold.

Requires: curl_cffi (pip install curl_cffi)
"""

from __future__ import annotations

import base64
import hashlib
import json
import random
import re
import secrets
import string
import threading
import time
import uuid
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from newtoken.common.logging_setup import get_logger, log_run_context, mask_text, mask_token

logger = get_logger("webui.register")

DEFAULT_EMAIL_DOMAIN = "@ai.1bool.com"  # 母号 SSO 域名（旧 team.edu.sixoner.com authentik 方案已弃）
DEFAULT_ONBOARDING_ROLE = "engineering"
AUTH_HOST = "https://auth.openai.com"
CHATGPT_HOST = "https://chatgpt.com"
OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OAUTH_REDIRECT_URI = "http://localhost:1455/auth/callback"
OAUTH_SCOPE = "openid profile email offline_access api.connectors.read api.connectors.invoke"
OAUTH_ORIGINATOR = "codex_vscode"
CODEX_SCOPE = "openid profile email offline_access"  # codex CLI 同款 scope（不含 connectors，对齐 gpt_onboard）
SENTINEL_SDK = "20260124ceb8"
MAX_POW_ATTEMPTS = 500000
POW_ERROR_PREFIX = "wQ8Lk5FbGpA2NcR9dShT6gYjU7VxZ4D"

_PRINT_LOCK = threading.Lock()
_COUNTER_LOCK = threading.Lock()

_SCREEN_SIZES = ["1366x768", "1440x900", "1536x864", "1920x1080", "1920x1200"]
_HARDWARE_CONCURRENCY = [8, 12, 16]
_FIRST_NAMES = ["Ava", "Mia", "Ethan", "James", "Lucas", "Noah", "Grace", "Emma", "Olivia", "Mason", "Liam", "Sophia"]
_LAST_NAMES = ["Smith", "Johnson", "Taylor", "Martin", "Brown", "Garcia", "Young", "Hall", "Allen", "King", "Scott"]


@dataclass(frozen=True)
class FingerprintProfile:
    impersonate: str
    user_agent: str
    sec_ch_ua: str
    accept_language: str
    primary_language: str
    screen_size: str
    hardware_concurrency: int


_FINGERPRINTS = [
    FingerprintProfile(
        impersonate="chrome142",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
        sec_ch_ua='"Google Chrome";v="142", "Chromium";v="142", "Not_A Brand";v="99"',
        accept_language="en-US,en;q=0.9",
        primary_language="en-US",
        screen_size="1440x900",
        hardware_concurrency=8,
    ),
    FingerprintProfile(
        impersonate="chrome131",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        sec_ch_ua='"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="99"',
        accept_language="en-GB,en;q=0.9",
        primary_language="en-GB",
        screen_size="1920x1080",
        hardware_concurrency=12,
    ),
    FingerprintProfile(
        impersonate="chrome",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
        sec_ch_ua='"Google Chrome";v="142", "Chromium";v="142", "Not_A Brand";v="99"',
        accept_language="en-US,en;q=0.9",
        primary_language="en-US",
        screen_size="1536x864",
        hardware_concurrency=8,
    ),
]


@dataclass
class RegisterResult:
    """Outcome of a single registration attempt."""

    ok: bool
    email: str = ""
    token_json: str = ""
    error: str = ""
    steps_completed: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# SentinelTokenGenerator -- OpenAI anti-bot PoW solver
# ---------------------------------------------------------------------------


class SentinelTokenGenerator:

    def __init__(
        self,
        device_id: str | None = None,
        user_agent: str | None = None,
        *,
        screen_size: str | None = None,
        primary_language: str | None = None,
        accept_language: str | None = None,
        hardware_concurrency: int | None = None,
    ):
        self.device_id = device_id or str(uuid.uuid4())
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36"
        )
        self.screen_size = screen_size or random.choice(_SCREEN_SIZES)
        self.primary_language = primary_language or "en-US"
        self.accept_language = accept_language or "en-US,en"
        self.hardware_concurrency = hardware_concurrency or random.choice(_HARDWARE_CONCURRENCY)
        self.requirements_seed = str(random.random())
        self.sid = str(uuid.uuid4())

    @staticmethod
    def _fnv1a_32(text: str) -> str:
        h = 2166136261
        for ch in text:
            h ^= ord(ch)
            h = (h * 16777619) & 0xFFFFFFFF
        h ^= h >> 16
        h = (h * 2246822507) & 0xFFFFFFFF
        h ^= h >> 13
        h = (h * 3266489909) & 0xFFFFFFFF
        h ^= h >> 16
        return format(h & 0xFFFFFFFF, "08x")

    def _get_config(self) -> list[Any]:
        now_str = time.strftime("%a %b %d %Y %H:%M:%S GMT+0000 (Coordinated Universal Time)", time.gmtime())
        perf_now = random.uniform(1000, 50000)
        time_origin = time.time() * 1000 - perf_now
        nav_prop = random.choice([
            "vendorSub", "productSub", "vendor", "maxTouchPoints", "scheduling",
            "userActivation", "doNotTrack", "geolocation", "connection", "plugins",
        ])
        return [
            self.screen_size, now_str, 4294705152, random.random(),
            self.user_agent,
            f"https://sentinel.openai.com/sentinel/{SENTINEL_SDK}/sdk.js",
            None, None, self.primary_language, self.accept_language, random.random(),
            f"{nav_prop}-undefined",
            random.choice(["location", "implementation", "URL", "documentURI", "compatMode"]),
            random.choice(["Object", "Function", "Array", "Number", "parseFloat", "undefined"]),
            perf_now, self.sid, "", self.hardware_concurrency, time_origin,
        ]

    @staticmethod
    def _b64(data: Any) -> str:
        return base64.b64encode(json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).decode("ascii")

    def _run_check(self, start_time: float, seed: str, difficulty: str, config: list[Any], nonce: int) -> str | None:
        config[3] = nonce
        config[9] = round((time.time() - start_time) * 1000)
        data = self._b64(config)
        hash_hex = self._fnv1a_32(seed + data)
        if hash_hex[: len(difficulty)] <= difficulty:
            return data + "~S"
        return None

    def generate_token(self, seed: str | None = None, difficulty: str | None = None) -> str:
        seed = seed if seed is not None else self.requirements_seed
        difficulty = str(difficulty or "0")
        start_time = time.time()
        config = self._get_config()
        for i in range(MAX_POW_ATTEMPTS):
            result = self._run_check(start_time, seed, difficulty, config, i)
            if result:
                return "gAAAAAB" + result
        return "gAAAAAB" + POW_ERROR_PREFIX + self._b64(str(None))

    def generate_requirements_token(self) -> str:
        config = self._get_config()
        config[3] = 1
        config[9] = round(random.uniform(5, 50))
        return "gAAAAAC" + self._b64(config)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def generate_pkce() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def extract_code_from_url(url: str | None) -> str | None:
    if not url or "code=" not in url:
        return None
    with suppress(Exception):
        return parse_qs(urlparse(url).query).get("code", [None])[0]
    return None


def _generate_password() -> str:
    alphabet = string.ascii_letters + string.digits
    while True:
        pw = "".join(random.choice(alphabet) for _ in range(13))
        if any(ch.islower() for ch in pw) and any(ch.isupper() for ch in pw) and any(ch.isdigit() for ch in pw):
            return pw


def _random_name() -> str:
    return f"{random.choice(_FIRST_NAMES)} {random.choice(_LAST_NAMES)}"


def _random_prefix() -> str:
    """随机邮箱前缀（自动注册用）。"""
    name = (random.choice(_FIRST_NAMES) + random.choice(_LAST_NAMES)).lower()
    return f"{name}{random.randint(1000, 9999)}"


def issue_oidc_card(api_url: str, api_key: str) -> str:
    """调 OIDC 发卡 API 生成一张卡并返回卡密。

    用 curl_cffi impersonate 直连（OIDC 经 Cloudflare，urllib 默认 UA 会被 403）。
    """
    from curl_cffi import requests as curl_requests

    api_url = str(api_url or "").strip().rstrip("/")
    api_key = str(api_key or "").strip()
    if not api_url or not api_key:
        raise RuntimeError("OIDC api_url/api_key 未配置，无法发卡")
    resp = curl_requests.post(
        f"{api_url}/api/cards/generate",
        json={"count": 1, "expires_days": 30, "note": "auto_register"},
        headers={"Authorization": f"Bearer {api_key}"}, impersonate="chrome", timeout=20,
    )
    if int(getattr(resp, "status_code", 0) or 0) != 200:
        raise RuntimeError(f"发卡失败 http={getattr(resp, 'status_code', '-')}: {str(getattr(resp, 'text', ''))[:160]}")
    data = resp.json()
    cards = data.get("cards") if isinstance(data, dict) else None
    if not cards:
        raise RuntimeError(f"发卡响应无 cards: {str(data)[:160]}")
    return str(cards[0])


def _random_birthdate() -> str:
    return f"{random.randint(1988, 2003):04d}-{random.randint(1, 12):02d}-{random.randint(1, 28):02d}"


def _short_url(url: str) -> str:
    """日志用：去掉 query（可能含 code/token），只留 scheme://host/path。"""
    try:
        parsed = urlparse(str(url))
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    except Exception:
        return str(url)[:80]


def _make_trace_headers() -> dict[str, str]:
    parent_id = random.randint(10**17, 10**18 - 1)
    return {
        "traceparent": f"00-{uuid.uuid4().hex}-{parent_id:016x}-01",
        "tracestate": "dd=s:1;o:rum",
        "x-datadog-origin": "rum",
        "x-datadog-sampling-priority": "1",
        "x-datadog-trace-id": str(random.randint(10**17, 10**18 - 1)),
        "x-datadog-parent-id": str(parent_id),
    }


def _extract_first_form(html: str) -> tuple[str, dict[str, str]]:
    html = str(html or "")
    match = re.search(r'<form[^>]+action="([^"]+)"[^>]*>(.*?)</form>', html, re.I | re.S)
    if not match:
        return "", {}
    fields: dict[str, str] = {}
    for name, value in re.findall(r'name="([^"]+)"(?:[^>]*value="([^"]*)")?', match.group(2), re.I | re.S):
        fields[str(name)] = str(value or "")
    return match.group(1), fields


def _decode_auth_session_cookie(raw_value: str) -> dict[str, Any]:
    raw_value = str(raw_value or "").strip()
    if not raw_value:
        return {}
    for candidate in (raw_value, raw_value.strip('"').strip("'")):
        try:
            payload = candidate.split(".", 1)[0]
            payload += "=" * ((4 - len(payload) % 4) % 4)
            data = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8", errors="replace"))
            if isinstance(data, dict):
                return data
        except Exception:
            continue
    return {}


# ---------------------------------------------------------------------------
# TeamRegistration -- core registration engine
# ---------------------------------------------------------------------------


class TeamRegistration:
    """Single-account ChatGPT team registration pipeline.

    Uses curl_cffi with Chrome impersonation to bypass TLS fingerprinting.
    The Sentinel token generator handles OpenAI's PoW anti-bot challenge.
    """

    def __init__(self, *, proxy_url: str = "", tag: str = "", email_domain: str = ""):
        from curl_cffi import requests as curl_requests
        try:
            from curl_cffi.const import CurlHttpVersion
        except ImportError:
            CurlHttpVersion = None

        self._tag = str(tag or "")
        self._email_domain = str(email_domain or DEFAULT_EMAIL_DOMAIN)
        self._device_id = str(uuid.uuid4())
        self._auth_logging_id = str(uuid.uuid4())
        self._callback_url = ""

        self._fp = random.choice(_FINGERPRINTS)
        self._impersonate = self._fp.impersonate
        self._ua = self._fp.user_agent
        self._sec_ch_ua = self._fp.sec_ch_ua
        self._accept_language = self._fp.accept_language
        self._primary_language = self._fp.primary_language
        self._screen_size = self._fp.screen_size
        self._hw_concurrency = self._fp.hardware_concurrency

        session_kwargs: dict[str, Any] = {"impersonate": self._impersonate}
        proxy_url = str(proxy_url or "").strip()
        if proxy_url:
            # Cloudflare 后端（chatgpt / auth.openai / sentinel）必须用代理侧 DNS：
            # socks5://（本地解析）会拿到与出口 IP 不匹配的 CF anycast IP，TLS 握手被 reset。
            # 强制升级为 socks5h://（远端解析）。
            if proxy_url.startswith("socks5://"):
                proxy_url = "socks5h://" + proxy_url[len("socks5://") :]
            session_kwargs["proxies"] = {"http": proxy_url, "https": proxy_url}
        if CurlHttpVersion is not None:
            session_kwargs["http_version"] = CurlHttpVersion.V1_1
        self._session = curl_requests.Session(**session_kwargs)
        self._session.headers.update({
            "User-Agent": self._ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": self._accept_language,
            "Accept-Encoding": "gzip, deflate, br",
            "sec-ch-ua": self._sec_ch_ua,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        })
        self._session.cookies.set("oai-did", self._device_id, domain="chatgpt.com")

        # 住宅代理对 Cloudflare 后端会间歇性 reset/timeout（实测单次失败率 ~37%）。
        # 长注册链路十几个串行请求，单步抖动即整体失败。对传输级失败（连接阶段、
        # 请求未送达，重试安全）自动重试，穿过代理噪音。
        _orig_request = self._session.request
        _retry_markers = (
            "Recv failure", "Connection reset", "timed out",
            "TLS connect error", "Connection refused", "Could not resolve",
        )

        def _retry_request(method, url, *args, **kwargs):
            last_exc = None
            for attempt in range(5):
                started = time.time()
                try:
                    resp = _orig_request(method, url, *args, **kwargs)
                except Exception as exc:  # noqa: BLE001
                    if not any(m in str(exc) for m in _retry_markers):
                        logger.debug("HTTP %s %s 异常(不重试): %s", method, _short_url(url), exc)
                        raise
                    last_exc = exc
                    logger.debug("HTTP %s %s 传输失败(重试%d): %s", method, _short_url(url), attempt + 1, exc)
                    if attempt < 4:
                        time.sleep(min(0.5 * (2 ** attempt), 5.0) + random.uniform(0, 0.4))
                    continue
                elapsed_ms = (time.time() - started) * 1000
                status = getattr(resp, "status_code", "-")
                if isinstance(status, int) and status >= 400:
                    body = mask_text(str(getattr(resp, "text", ""))[:200])
                    logger.warning("HTTP %s %s -> %s (%.0fms) body=%s", method, _short_url(url), status, elapsed_ms, body)
                else:
                    logger.debug("HTTP %s %s -> %s (%.0fms)", method, _short_url(url), status, elapsed_ms)
                return resp
            raise last_exc

        self._session.request = _retry_request

    def close(self) -> None:
        with suppress(Exception):
            self._session.close()

    def __enter__(self) -> TeamRegistration:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # -- internal helpers ----------------------------------------------------

    def _log(self, msg: str) -> None:
        logger.info("%s", msg)

    def _get_cookie(self, name: str, domain_hint: str = "") -> str:
        jar = getattr(self._session.cookies, "jar", None)
        if jar is None:
            return ""
        for cookie in list(jar):
            if getattr(cookie, "name", "") != name:
                continue
            domain = str(getattr(cookie, "domain", "") or "")
            if domain_hint and domain_hint not in domain:
                continue
            return str(getattr(cookie, "value", "") or "")
        return ""

    def _export_cookies(self) -> list[dict[str, Any]]:
        jar = getattr(self._session.cookies, "jar", None)
        if jar is None:
            return []
        return [
            {"name": str(getattr(c, "name", "")), "value": str(getattr(c, "value", "")),
             "domain": str(getattr(c, "domain", "")), "path": str(getattr(c, "path", "") or "/")}
            for c in list(jar)
        ]

    def _json_or_raise(self, resp: Any, step: str) -> dict[str, Any]:
        try:
            data = resp.json()
        except Exception:
            text = str(getattr(resp, "text", "") or "")[:300]
            raise RuntimeError(f"{step} failed: HTTP {getattr(resp, 'status_code', '-')} non_json={text}")
        if not isinstance(data, dict):
            raise RuntimeError(f"{step} failed: unexpected JSON type")
        return data

    def _build_sentinel(self, flow: str) -> str:
        try:
            from curl_cffi import requests as curl_requests
        except ImportError:
            return ""

        generator = SentinelTokenGenerator(
            device_id=self._device_id,
            user_agent=self._ua,
            screen_size=self._screen_size,
            primary_language=self._primary_language,
            accept_language=self._accept_language,
            hardware_concurrency=self._hw_concurrency,
        )
        body = {"p": generator.generate_requirements_token(), "id": self._device_id, "flow": flow}
        headers = {
            "Content-Type": "text/plain;charset=UTF-8",
            "Referer": "https://sentinel.openai.com/backend-api/sentinel/frame.html",
            "Origin": "https://sentinel.openai.com",
            "User-Agent": self._ua,
        }
        with suppress(Exception):
            resp = self._session.post("https://sentinel.openai.com/backend-api/sentinel/req",
                                       data=json.dumps(body), headers=headers, timeout=20)
            if resp.status_code == 200:
                challenge = resp.json()
                if isinstance(challenge, dict):
                    c_value = challenge.get("token", "")
                    pow_data = challenge.get("proofofwork") or {}
                    if c_value:
                        if pow_data.get("required") and pow_data.get("seed"):
                            p_value = generator.generate_token(seed=pow_data.get("seed"), difficulty=pow_data.get("difficulty", "0"))
                        else:
                            p_value = generator.generate_requirements_token()
                        return json.dumps({"p": p_value, "t": "", "c": c_value, "id": self._device_id, "flow": flow},
                                          separators=(",", ":"), ensure_ascii=False)
        return str(generator.generate_requirements_token())

    # -- pipeline steps ------------------------------------------------------

    def visit_homepage(self) -> None:
        resp = self._session.get(
            f"{CHATGPT_HOST}/",
            headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                     "Upgrade-Insecure-Requests": "1"},
            allow_redirects=True, timeout=30, impersonate=self._impersonate,
        )
        self._log(f"[homepage] {resp.status_code}")

    def get_csrf(self) -> str:
        resp = self._session.get(
            f"{CHATGPT_HOST}/api/auth/csrf",
            headers={"Accept": "application/json", "Referer": f"{CHATGPT_HOST}/"},
            timeout=30, impersonate=self._impersonate,
        )
        data = self._json_or_raise(resp, "csrf")
        token = str(data.get("csrfToken") or "")
        if not token:
            raise RuntimeError("missing csrfToken")
        return token

    def signin(self, email: str, csrf: str) -> str:
        params = {
            "prompt": "login", "ext-oai-did": self._device_id,
            "auth_session_logging_id": self._auth_logging_id,
            "ext-passkey-client-capabilities": "1111",
            "screen_hint": "login_or_signup", "login_hint": email,
        }
        form = {"callbackUrl": f"{CHATGPT_HOST}/", "csrfToken": csrf, "json": "true"}
        resp = self._session.post(
            f"{CHATGPT_HOST}/api/auth/signin/openai",
            params=params, data=form,
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json",
                     "Referer": f"{CHATGPT_HOST}/", "Origin": CHATGPT_HOST},
            timeout=30, impersonate=self._impersonate,
        )
        data = self._json_or_raise(resp, "signin")
        auth_url = str(data.get("url") or "")
        if not auth_url:
            raise RuntimeError("signin did not return authorize url")
        return auth_url

    def authorize(self, url: str) -> str:
        resp = self._session.get(
            url,
            headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                     "Referer": f"{CHATGPT_HOST}/", "Upgrade-Insecure-Requests": "1"},
            allow_redirects=True, timeout=30, impersonate=self._impersonate,
        )
        final = str(resp.url)
        if int(resp.status_code or 0) >= 400:
            raise RuntimeError(f"authorize failed status={resp.status_code} final={final}")
        auth_did = self._get_cookie("oai-did", "auth.openai.com") or self._get_cookie("oai-did", ".auth.openai.com")
        if auth_did and auth_did != self._device_id:
            self._device_id = auth_did
        return final

    def create_account(self, name: str, birthdate: str) -> str:
        sentinel = self._build_sentinel("create_account")
        headers = {
            "Content-Type": "application/json", "Accept": "application/json",
            "Referer": f"{AUTH_HOST}/about-you", "Origin": AUTH_HOST,
            "oai-device-id": self._device_id,
        }
        headers.update(_make_trace_headers())
        if sentinel:
            headers["openai-sentinel-token"] = sentinel
        resp = self._session.post(
            f"{AUTH_HOST}/api/accounts/create_account",
            json={"name": name, "birthdate": birthdate},
            headers=headers, timeout=30, impersonate=self._impersonate,
        )
        data = self._json_or_raise(resp, "create_account")
        cb = str(data.get("continue_url") or data.get("url") or "")
        if cb:
            self._callback_url = cb
        return cb

    def callback(self, url: str = "") -> None:
        final_url = url or self._callback_url
        if not final_url:
            raise RuntimeError("missing callback url")
        resp = self._session.get(
            final_url,
            headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                     "Accept-Language": self._accept_language, "Referer": f"{AUTH_HOST}/",
                     "Upgrade-Insecure-Requests": "1",
                     "Sec-Fetch-Dest": "document", "Sec-Fetch-Mode": "navigate",
                     "Sec-Fetch-Site": "same-site", "Sec-Fetch-User": "?1"},
            allow_redirects=True, timeout=30, impersonate=self._impersonate,
        )
        self._log(f"[callback] -> {resp.status_code} {str(resp.url)[:80]}")

    def client_auth_session_dump(self) -> dict[str, Any]:
        url = f"{AUTH_HOST}/api/accounts/client_auth_session_dump"
        resp = self._session.get(url, headers={"Accept": "application/json", "Referer": f"{AUTH_HOST}/email-verification"},
                                 timeout=30, impersonate=self._impersonate)
        try:
            data = resp.json()
        except Exception:
            data = {"text": str(getattr(resp, "text", "") or "")[:400]}
        if not isinstance(data, dict):
            data = {"data": data}
        self._log(f"[client_auth_session_dump] status={resp.status_code}")
        return data

    def _extract_sso_connection(self) -> tuple[str, int]:
        cookie_val = self._get_cookie("oai-client-auth-session", "auth.openai.com") or self._get_cookie("oai-client-auth-session", "openai.com")
        session_data = _decode_auth_session_cookie(cookie_val)
        sso = session_data.get("sso") if isinstance(session_data.get("sso"), dict) else {}
        conns = sso.get("connections") if isinstance(sso, dict) else []
        if isinstance(conns, list):
            for item in conns:
                if isinstance(item, dict):
                    name = str(item.get("connection_name") or "").strip()
                    provider = int(item.get("connection_provider") or 0)
                    if name and provider:
                        self._log(f"[SSO] connection={name} provider={provider}")
                        return name, provider
        dump = self.client_auth_session_dump()
        client_auth = dump.get("client_auth_session") if isinstance(dump.get("client_auth_session"), dict) else dump
        sso2 = client_auth.get("sso") if isinstance(client_auth, dict) and isinstance(client_auth.get("sso"), dict) else {}
        conns2 = sso2.get("connections") if isinstance(sso2, dict) else []
        if isinstance(conns2, list):
            for item in conns2:
                if isinstance(item, dict):
                    name = str(item.get("connection_name") or "").strip()
                    provider = int(item.get("connection_provider") or 0)
                    if name and provider:
                        self._log(f"[SSO dump] connection={name} provider={provider}")
                        return name, provider
        raise RuntimeError("enterprise SSO connection not found")

    def _complete_external_sso_flow(self, *, email: str, continue_url: str, referer: str) -> str:
        page_headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": referer, "Upgrade-Insecure-Requests": "1",
        }
        current_url = continue_url
        for _ in range(10):
            self._log(f"[SSO] GET {current_url[:100]}")
            resp = self._session.get(current_url, headers=page_headers, allow_redirects=False,
                                     timeout=30, impersonate=self._impersonate)
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = str(resp.headers.get("Location") or "")
                if loc:
                    current_url = urljoin(current_url, loc)
                    continue
            break
        sso_url = str(resp.url)
        body = str(getattr(resp, "text", "") or "")
        self._log(f"[SSO] final_url={sso_url[:120]} len={len(body)}")

        approve_action, approve_fields = _extract_first_form(body)
        challenge = str(approve_fields.get("challenge") or "").strip()
        if not approve_action or not challenge:
            raise RuntimeError(f"SSO approve form missing challenge: {sso_url}")
        approve_data = {"email": email, "confirm_password": "", "challenge": challenge}
        approve_resp = self._session.post(
            urljoin(sso_url, approve_action), data=approve_data,
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                     "Referer": sso_url},
            allow_redirects=False, timeout=30, impersonate=self._impersonate,
        )
        approve_loc = str(approve_resp.headers.get("Location") or "")
        if approve_resp.status_code not in (301, 302, 303, 307, 308) or not approve_loc:
            raise RuntimeError(f"SSO approve failed ({approve_resp.status_code})")

        consent_resp = self._session.get(
            approve_loc,
            headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                     "Referer": sso_url, "Upgrade-Insecure-Requests": "1"},
            allow_redirects=True, timeout=30, impersonate=self._impersonate,
        )
        consent_url = str(consent_resp.url)
        self._log(f"[SSO] interstitial -> {consent_url[:120]}")
        if "/sign-in-with-chatgpt/codex/consent" in consent_url:
            return consent_url

        interstitial_action, interstitial_fields = _extract_first_form(str(getattr(consent_resp, "text", "") or ""))
        interstitial_token = str(interstitial_fields.get("interstitial_token") or "").strip()
        csrf_token = str(interstitial_fields.get("csrf_token") or "").strip()
        action_value = str(interstitial_fields.get("action") or "confirm").strip() or "confirm"
        if not interstitial_action or not interstitial_token or not csrf_token:
            raise RuntimeError(f"interstitial form missing fields: {consent_url}")

        final_resp = self._session.post(
            urljoin(consent_url, interstitial_action),
            data={"interstitial_token": interstitial_token, "action": action_value, "csrf_token": csrf_token},
            headers={"Content-Type": "application/x-www-form-urlencoded",
                     "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                     "Cache-Control": "max-age=0", "Origin": "null", "Referer": consent_url,
                     "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "navigate",
                     "Sec-Fetch-User": "?1", "Sec-Fetch-Dest": "document",
                     "Upgrade-Insecure-Requests": "1"},
            allow_redirects=False, timeout=30, impersonate=self._impersonate,
        )
        loc = str(final_resp.headers.get("Location") or "")
        self._log(f"[SSO] confirm -> {final_resp.status_code} next={loc[:100] or '-'}")
        if final_resp.status_code in (301, 302, 303, 307, 308) and loc:
            callback_resp = self._session.get(
                loc,
                headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                         "Referer": consent_url, "Upgrade-Insecure-Requests": "1"},
                allow_redirects=True, timeout=30, impersonate=self._impersonate,
            )
            return str(callback_resp.url)
        return str(final_resp.url)

    def _complete_sso_web_flow(self, email: str, sso_url: str) -> str:
        conn_name, conn_provider = self._extract_sso_connection()
        sentinel = self._build_sentinel("authorize_continue")
        headers = {
            "Content-Type": "application/json", "Accept": "application/json",
            "Accept-Language": self._accept_language, "Referer": sso_url,
            "Origin": AUTH_HOST, "oai-device-id": self._device_id,
            "openai-sentinel-token": sentinel,
            "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }
        headers.update(_make_trace_headers())
        resp = self._session.post(
            f"{AUTH_HOST}/api/accounts/authorize/continue",
            json={"connection": conn_name, "connection_provider": conn_provider},
            headers=headers, allow_redirects=False, timeout=30, impersonate=self._impersonate,
        )
        data = self._json_or_raise(resp, "authorize_continue")
        continue_url = str(data.get("continue_url") or ((data.get("page") or {}).get("payload") or {}).get("url") or "")
        if not continue_url:
            raise RuntimeError("authorize/continue did not return continue_url")
        return self._complete_external_sso_flow(email=email, continue_url=continue_url, referer=f"{AUTH_HOST}/")

    def get_access_token(self) -> dict[str, Any]:
        last_error = ""
        for attempt in range(1, 11):
            if attempt > 1:
                with suppress(Exception):
                    self._session.get(f"{CHATGPT_HOST}/",
                                      headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                                               "Referer": f"{CHATGPT_HOST}/", "Upgrade-Insecure-Requests": "1"},
                                      allow_redirects=True, timeout=30, impersonate=self._impersonate)
                time.sleep(random.uniform(1.5, 3.0))
            try:
                resp = self._session.get(
                    f"{CHATGPT_HOST}/api/auth/session",
                    headers={"Accept": "application/json", "Referer": f"{CHATGPT_HOST}/"},
                    timeout=30, impersonate=self._impersonate,
                )
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                time.sleep(random.uniform(1.0, 2.0))
                continue
            if resp.status_code == 200:
                data = resp.json()
                at = str((data or {}).get("accessToken") or "").strip()
                if at:
                    return {"access_token": at, "session_token": str((data or {}).get("sessionToken") or "").strip(),
                            "raw_session": data}
                last_error = f"missing accessToken (attempt {attempt})"
            else:
                last_error = f"HTTP {resp.status_code} (attempt {attempt})"
                if resp.status_code == 403:
                    time.sleep(random.uniform(2.0, 4.0))
            time.sleep(random.uniform(1.0, 2.0))
        raise RuntimeError(f"failed to get access token: {last_error}")

    def oauth_authorize_codex(self) -> str:
        verifier, challenge = generate_pkce()
        state = secrets.token_urlsafe(24)
        params = {
            "response_type": "code", "client_id": OAUTH_CLIENT_ID,
            "redirect_uri": OAUTH_REDIRECT_URI, "scope": OAUTH_SCOPE,
            "code_challenge": challenge, "code_challenge_method": "S256",
            "codex_cli_simplified_flow": "true", "id_token_add_organizations": "true",
            "originator": OAUTH_ORIGINATOR, "state": state,
        }
        url = f"{AUTH_HOST}/oauth/authorize?{urlencode(params)}"
        resp = self._session.get(
            url,
            headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                     "Referer": f"{CHATGPT_HOST}/", "Upgrade-Insecure-Requests": "1"},
            allow_redirects=True, timeout=30, impersonate=self._impersonate,
        )
        return {"verifier": verifier, "state": state, "final_url": str(resp.url)}

    def exchange_codex_code(self, code: str, verifier: str) -> dict[str, Any] | None:
        resp = self._session.post(
            f"{AUTH_HOST}/oauth/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={"grant_type": "authorization_code", "code": code,
                  "redirect_uri": OAUTH_REDIRECT_URI, "client_id": OAUTH_CLIENT_ID,
                  "code_verifier": verifier},
            timeout=60, impersonate=self._impersonate,
        )
        try:
            data = resp.json()
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    # -- codex oauth + oidc 卡密 SSO 登录（免手机验证，2026-06 现行方案） -------

    def build_codex_auth_url(self, email: str) -> tuple[str, str, str]:
        """生成 codex CLI 同款 PKCE auth_url（带 login_hint），返回 (url, verifier, state)。"""
        verifier, challenge = generate_pkce()
        state = secrets.token_urlsafe(24)
        params = {
            "response_type": "code", "client_id": OAUTH_CLIENT_ID, "redirect_uri": OAUTH_REDIRECT_URI,
            "scope": CODEX_SCOPE, "state": state,
            "code_challenge": challenge, "code_challenge_method": "S256",
            "id_token_add_organizations": "true", "codex_cli_simplified_flow": "true",
            "login_hint": email,
        }
        return f"{AUTH_HOST}/oauth/authorize?{urlencode(params)}", verifier, state

    def codex_card_login(self, *, email: str, prefix: str, card: str, account_id: str,
                         domain: str, full_name: str, steps: list[str]) -> dict[str, Any]:
        """直接 codex oauth + 自建 OIDC 卡密 SSO 登录，换取 codex token（含 refresh_token）。

        关键：必须以 codex auth_url 为第一个请求、全程不碰 chatgpt 网页，否则触发手机验证。
        复刻已验证的 10 步流程（见 codex-card-sso-flow 记录）。
        """
        imp = self._impersonate
        S = self._session
        html_accept = (
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8"
        )

        def _is_card_page(resp: Any) -> bool:
            return 'name="card_key"' in str(getattr(resp, "text", "") or "")

        # 1. GET codex auth_url(login_hint) → OpenAI SSO 选择页 或直接我方卡密页
        auth_url, verifier, _state = self.build_codex_auth_url(email)
        resp = S.get(auth_url, allow_redirects=True, timeout=30, impersonate=imp,
                     headers={"Accept": html_accept, "Upgrade-Insecure-Requests": "1"})
        final = str(resp.url)
        self._log(f"[codex] authorize landed {resp.status_code} {final[:80]}")
        steps.append("codex_authorize")

        # 2. 若停在 OpenAI SSO 选择页 → 取 connection + authorize/continue → 跟随进我方卡密页
        if not _is_card_page(resp):
            conn_name, conn_provider = self._extract_sso_connection()
            sentinel = self._build_sentinel("authorize_continue")
            headers = {
                "Content-Type": "application/json", "Accept": "application/json",
                "Accept-Language": self._accept_language, "Referer": final, "Origin": AUTH_HOST,
                "oai-device-id": self._device_id, "openai-sentinel-token": sentinel,
                "Sec-Fetch-Dest": "empty", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin",
            }
            headers.update(_make_trace_headers())
            r = S.post(f"{AUTH_HOST}/api/accounts/authorize/continue",
                       json={"connection": conn_name, "connection_provider": conn_provider},
                       headers=headers, allow_redirects=False, timeout=30, impersonate=imp)
            data = self._json_or_raise(r, "authorize/continue")
            cur = str(data.get("continue_url") or ((data.get("page") or {}).get("payload") or {}).get("url") or "")
            if not cur:
                raise RuntimeError("authorize/continue did not return continue_url")
            steps.append("sso_continue")
            for _ in range(10):
                r = S.get(cur, headers={"Accept": html_accept, "Upgrade-Insecure-Requests": "1"},
                          allow_redirects=False, timeout=30, impersonate=imp)
                if int(r.status_code or 0) in (301, 302, 303, 307, 308):
                    cur = urljoin(cur, str(r.headers.get("Location") or ""))
                    continue
                break
            resp = r
            final = str(r.url)

        if not _is_card_page(resp):
            raise RuntimeError(f"did not reach OIDC card page, landed at {final}")

        origin = f"{urlparse(final).scheme}://{urlparse(final).netloc}"
        card_post_url = origin + urlparse(final).path  # e.g. https://oidc.1bool.com/sso

        # 3. 解析 csrf → POST 卡密 + 邮箱前缀（首次激活绑卡）
        csrf_m = re.search(r'name="csrf_token"\s+value="([^"]+)"', str(resp.text))
        csrf = csrf_m.group(1) if csrf_m else ""
        r = S.post(card_post_url,
                   data={"csrf_token": csrf, "email_prefix": prefix, "email_domain": domain,
                         "card_key": card, "full_name": full_name},
                   headers={"Content-Type": "application/x-www-form-urlencoded", "Referer": final, "Origin": origin},
                   allow_redirects=False, timeout=30, impersonate=imp)
        if int(r.status_code or 0) not in (301, 302, 303, 307, 308):
            raise RuntimeError(f"card submit failed http={r.status_code}: {str(r.text)[:160]}")
        steps.append("card_submit")

        # 4. 跟随 resume 桥接页 → 抽取回 OpenAI 的 callback href（含 code）
        r = S.get(urljoin(card_post_url, str(r.headers.get("Location") or "")),
                  allow_redirects=True, timeout=30, impersonate=imp, headers={"Accept": html_accept})
        cb_m = re.search(r'href="(https://[^"]+/sso/oidc/[^"]+callback\?code=[^"]+)"', str(r.text))
        callback = cb_m.group(1).replace("&amp;", "&") if cb_m else ""
        if not callback:
            raise RuntimeError("bridge page missing OpenAI callback href")
        steps.append("oidc_callback")

        # 5. GET callback → signin-consent → POST interstitial 确认
        r = S.get(callback, allow_redirects=True, timeout=30, impersonate=imp, headers={"Accept": html_accept})
        consent_url, html = str(r.url), str(r.text)
        if "signin-consent" in consent_url or 'name="interstitial_token"' in html:
            action, fields = _extract_first_form(html)
            r = S.post(urljoin(consent_url, action),
                       data={"interstitial_token": fields.get("interstitial_token", ""),
                             "action": fields.get("action", "confirm"), "csrf_token": fields.get("csrf_token", "")},
                       headers={"Content-Type": "application/x-www-form-urlencoded", "Referer": consent_url},
                       allow_redirects=False, timeout=30, impersonate=imp)
            r = S.get(urljoin(consent_url, str(r.headers.get("Location") or "")),
                      allow_redirects=True, timeout=30, impersonate=imp, headers={"Accept": html_accept})
            consent_url, html = str(r.url), str(r.text)
            steps.append("signin_consent")

        # 6. codex consent「Continue」实为 POST /api/accounts/workspace/select (JSON) → continue_url → code
        code = extract_code_from_url(consent_url)
        if not code and "codex/consent" in consent_url:
            sentinel = self._build_sentinel("login")
            headers = {
                "Content-Type": "application/json", "Accept": "application/json", "Referer": consent_url,
                "Origin": AUTH_HOST, "oai-device-id": self._device_id,
                "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty",
            }
            headers.update(_make_trace_headers())
            if sentinel:
                headers["openai-sentinel-token"] = sentinel
            r = S.post(f"{AUTH_HOST}/api/accounts/workspace/select",
                       json={"workspace_id": account_id}, headers=headers,
                       allow_redirects=False, timeout=30, impersonate=imp)
            nxt = ""
            try:
                d = r.json()
                if isinstance(d, dict):
                    nxt = str(d.get("continue_url") or d.get("url") or d.get("redirect_url")
                              or ((d.get("page") or {}).get("payload") or {}).get("url") or "")
            except Exception:
                nxt = ""
            nxt = nxt or str(r.headers.get("Location") or "")
            if nxt:
                code = extract_code_from_url(nxt) or self.follow_url_for_code(nxt, referer=consent_url)
            steps.append("workspace_select")

        if not code:
            raise RuntimeError(f"missing authorization code at {consent_url}")
        steps.append("codex_code")

        # 7. 换 token（必须有 refresh_token）
        tokens = self.exchange_codex_code(code, verifier)
        if not tokens or not isinstance(tokens, dict) or not str(tokens.get("refresh_token") or "").strip():
            raise RuntimeError("/oauth/token failed or missing refresh_token")
        steps.append("codex_token")
        return tokens

    def follow_url_for_code(self, start_url: str, referer: str = "") -> str:
        current = str(start_url or "")
        for _ in range(12):
            if not current:
                return ""
            code = extract_code_from_url(current)
            if code:
                return code
            try:
                resp = self._session.get(
                    current,
                    headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                             "Referer": referer or current, "Upgrade-Insecure-Requests": "1"},
                    allow_redirects=False, timeout=30, impersonate=self._impersonate,
                )
            except Exception as exc:
                maybe = re.search(r"(https?://localhost[^\s'\"]+)", str(exc))
                if maybe:
                    return extract_code_from_url(maybe.group(1)) or ""
                return ""
            current = str(resp.url)
            code = extract_code_from_url(current)
            if code:
                return code
            if resp.status_code in (301, 302, 303, 307, 308):
                loc = str(resp.headers.get("Location") or "")
                if loc.startswith("/"):
                    loc = f"{AUTH_HOST}{loc}"
                code = extract_code_from_url(loc)
                if code:
                    return code
                if loc:
                    referer = current
                    current = loc
                    continue
            body = str(getattr(resp, "text", "") or "")
            if body:
                hrefs = re.findall(r'href=["\']([^"\']+)["\']', body, flags=re.I)
                for href in hrefs:
                    if href.startswith("/"):
                        href = f"{AUTH_HOST}{href}"
                    code = extract_code_from_url(href)
                    if code:
                        return code
                    if href.startswith("http://localhost") or href.startswith("https://localhost"):
                        return extract_code_from_url(href) or ""
                    if href.startswith(AUTH_HOST) and any(m in href for m in ("/api/accounts/consent", "/api/oauth/oauth2/auth", "/sign-in-with-chatgpt/")):
                        referer = current
                        current = href
                        break
            return ""
        return ""

    def patch_onboarding(self, access_token: str) -> None:
        st_me, me = self._chatgpt_json("GET", "/backend-api/me", access_token=access_token)
        if st_me != 200:
            raise RuntimeError(f"backend-api/me failed http={st_me}")
        user_id = str((me or {}).get("id") or "").strip()
        if not user_id:
            raise RuntimeError("backend-api/me missing user id")
        st_chk, chk = self._chatgpt_json("GET", "/backend-api/accounts/check/v4-2023-04-27?timezone_offset_min=-480", access_token=access_token)
        if st_chk != 200:
            raise RuntimeError(f"accounts/check failed http={st_chk}")
        accounts = (chk or {}).get("accounts") or {}
        if not isinstance(accounts, dict) or not accounts:
            raise RuntimeError("accounts/check missing accounts")
        account_id = next(iter(accounts.keys()))
        path = f"/backend-api/accounts/{account_id}/users/{user_id}"
        payload = {"onboarding_information": {"role": DEFAULT_ONBOARDING_ROLE, "departments": []}}
        st_patch, _ = self._chatgpt_json("PATCH", path, access_token=access_token, json_body=payload)
        if st_patch != 200:
            raise RuntimeError(f"onboarding patch failed http={st_patch}")

    def _chatgpt_json(self, method: str, path: str, *, access_token: str = "", json_body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        url = f"{CHATGPT_HOST}{path}"
        headers: dict[str, str] = {
            "Accept": "application/json", "Origin": CHATGPT_HOST,
            "Referer": f"{CHATGPT_HOST}/", "oai-device-id": self._device_id,
        }
        if json_body is not None:
            headers["Content-Type"] = "application/json"
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        headers.update(_make_trace_headers())
        func = getattr(self._session, method.lower())
        resp = func(url, json=json_body, headers=headers, timeout=30, impersonate=self._impersonate)
        try:
            data = resp.json()
        except Exception:
            data = {"text": str(getattr(resp, "text", "") or "")[:800]}
        return int(resp.status_code or 0), data if isinstance(data, dict) else {"data": data}


# ---------------------------------------------------------------------------
# Pipeline orchestration
# ---------------------------------------------------------------------------


def build_codex_token_json(email: str, tokens: dict[str, Any]) -> str:
    return json.dumps({
        "type": "codex",
        "email": email,
        "token_source": "ChatGPT_team",
        "refresh_token": str(tokens.get("refresh_token") or ""),
        "access_token": str(tokens.get("access_token") or ""),
        "id_token": str(tokens.get("id_token") or ""),
        "saved_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }, ensure_ascii=False)


def register_one(idx: int, *, email_domain: str = "", proxy_url: str = "",
                 oidc_api_url: str = "", oidc_api_key: str = "", account_id: str = "",
                 tag_prefix: str = "r", run_id: str = "") -> RegisterResult:
    """直接 codex oauth + 自建 OIDC 卡密 SSO 注册单个账号，换取 codex token。

    流程：发卡 → codex auth_url(login_hint) → SSO → 卡密首次激活 → consent →
    workspace/select → code → 换 token。全程不碰 chatgpt 网页（避免手机验证）。
    """
    tag = f"{tag_prefix}{idx}"
    context_id = f"{run_id}/{tag}" if run_id else tag
    with log_run_context(context_id):
        reg: TeamRegistration | None = None
        email = ""
        steps: list[str] = []
        try:
            domain = (email_domain or DEFAULT_EMAIL_DOMAIN).lstrip("@").strip()
            if not domain:
                raise RuntimeError("email_domain 为空")
            if not str(account_id or "").strip():
                raise RuntimeError("account_id（母号 workspace_id）为空")

            # 1. 发卡
            card = issue_oidc_card(oidc_api_url, oidc_api_key)
            steps.append("issue_card")

            # 2. 随机身份
            prefix = _random_prefix()
            email = f"{prefix}@{domain}"
            full_name = _random_name()

            # 3. codex oauth + 卡密 SSO 登录 → codex token
            reg = TeamRegistration(proxy_url=proxy_url, tag=tag, email_domain="@" + domain)
            logger.info("开始注册 email=%s", email)
            tokens = reg.codex_card_login(email=email, prefix=prefix, card=card,
                                          account_id=str(account_id).strip(), domain=domain,
                                          full_name=full_name, steps=steps)
            token_json = build_codex_token_json(email, tokens)
            reg._log(f"[done] email={email} rt={mask_token(str(tokens.get('refresh_token') or ''))}")
            logger.info("注册成功 email=%s steps=%s", email, ",".join(steps))
            return RegisterResult(ok=True, email=email, token_json=token_json, steps_completed=steps)

        except Exception as exc:
            logger.exception("注册失败 email=%s steps=%s", email or "-", ",".join(steps))
            return RegisterResult(ok=False, email=email, error=f"{type(exc).__name__}: {exc}", steps_completed=steps)
        finally:
            if reg is not None:
                reg.close()


def register_batch(count: int, *, email_domain: str = "", proxy_url: str = "",
                   oidc_api_url: str = "", oidc_api_key: str = "", account_id: str = "",
                   max_workers: int = 1, run_id: str = "") -> list[RegisterResult]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: list[RegisterResult] = []
    with ThreadPoolExecutor(max_workers=min(max_workers, max(1, count)), thread_name_prefix="webui-reg-") as ex:
        futures = {
            ex.submit(register_one, i + 1, email_domain=email_domain, proxy_url=proxy_url,
                      oidc_api_url=oidc_api_url, oidc_api_key=oidc_api_key, account_id=account_id,
                      run_id=run_id): i + 1
            for i in range(count)
        }
        for fut in as_completed(futures):
            results.append(fut.result())
    return sorted(results, key=lambda r: r.ok, reverse=True)
