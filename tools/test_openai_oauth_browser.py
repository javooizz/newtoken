"""服务器侧测试 OpenAI OAuth 浏览器链路的小脚本。"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from newtoken.sub2api.remote_oauth import (
    create_openai_oauth_pending_session,
    load_openai_oauth_defaults,
)


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"')
    return values


def resolve_auth_url(env_path: Path, auth_url: str, redirect_uri: str) -> str:
    """优先使用外部传入链接，否则现生成一条新的授权链接。"""

    if auth_url.strip():
        return auth_url.strip()

    defaults = load_openai_oauth_defaults(str(env_path))
    result = create_openai_oauth_pending_session(
        base_url=defaults.get("base_url", ""),
        admin_api_key=defaults.get("admin_api_key", ""),
        proxy_id=defaults.get("proxy_id", ""),
        proxy_url=defaults.get("proxy_url", ""),
        proxy_name=defaults.get("proxy_name", "default"),
        redirect_uri=redirect_uri,
        group_ids=[],
        group_name=defaults.get("group_name", "cc"),
        concurrency=defaults.get("concurrency", "10"),
    )
    return result["pending_session"].auth_url


def build_session_cookies(session_token: str) -> list[dict[str, object]]:
    """把超长 next-auth session token 按分片 cookie 形式写入浏览器。"""

    token = session_token.strip()
    if not token:
        return []

    cookie_url = "https://auth.openai.com"
    chunk_size = 3800
    cookie_names = [
        "__Secure-next-auth.session-token",
        "next-auth.session-token",
        "__Secure-authjs.session-token",
        "authjs.session-token",
    ]

    def make_cookie(name: str, value: str) -> dict[str, object]:
        return {
            "name": name,
            "value": value,
            "url": cookie_url,
            "secure": True,
        }

    if len(token) <= chunk_size:
        return [make_cookie(name, token) for name in cookie_names]

    cookies: list[dict[str, object]] = []
    chunks = [token[index : index + chunk_size] for index in range(0, len(token), chunk_size)]
    for base_name in cookie_names:
        for index, chunk in enumerate(chunks):
            cookies.append(make_cookie(f"{base_name}.{index}", chunk))
    return cookies


def find_last_oidc_authorize_url(events: list[dict[str, object]]) -> str:
    """从导航日志里找最后一条项目 OIDC authorize 请求。"""

    for item in reversed(events):
        url = str(item.get("url", ""))
        if "/application/o/openai-custom-oidc/authorize" in url:
            return url
    return ""


def wait_for_oidc_authorize_url(
    events: list[dict[str, object]],
    *,
    timeout_seconds: float = 60.0,
    interval_seconds: float = 0.5,
) -> str:
    """等待项目 OIDC authorize 请求真正出现在日志里。"""

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        matched = find_last_oidc_authorize_url(events)
        if matched:
            return matched
        time.sleep(interval_seconds)
    return find_last_oidc_authorize_url(events)


def wait_for_runtime_oidc_authorize_url(
    runtime_state: dict[str, str],
    *,
    timeout_seconds: float = 60.0,
    interval_seconds: float = 0.2,
) -> str:
    """优先从实时事件回调里等到 OIDC authorize URL。"""

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        matched = runtime_state.get("last_oidc_authorize_url", "").strip()
        if matched:
            return matched
        time.sleep(interval_seconds)
    return runtime_state.get("last_oidc_authorize_url", "").strip()


def call_internal_direct_authorize(
    *,
    authorize_url: str,
    email: str,
    full_name: str = "",
    oidc_env_path: str = "/opt/sub2api-standalone-source/oidc/.env",
) -> dict[str, object]:
    """调用项目 OIDC 内部直通接口，直接签发授权码。"""

    oidc_env = load_env(Path(oidc_env_path).resolve())
    bypass_key = oidc_env.get("GPTOIDC_INTERNAL_BYPASS_KEY", "").strip()
    if not bypass_key:
        raise RuntimeError("missing GPTOIDC_INTERNAL_BYPASS_KEY")

    parsed = urlsplit(authorize_url)
    endpoint = f"{parsed.scheme}://{parsed.netloc}/api/internal/direct-authorize"
    request_body = json.dumps(
        {
            "authorize_url": authorize_url,
            "email": email,
            "full_name": full_name,
        }
    ).encode("utf-8")
    request = Request(
        endpoint,
        data=request_body,
        headers={
            "Authorization": f"Bearer {bypass_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not bool(payload.get("ok")):
        raise RuntimeError(f"direct-authorize failed: {payload}")
    return payload


def main() -> int:
    if len(sys.argv) < 2:
        print(
            "usage: test_openai_oauth_browser.py <env_path> [auth_url] [redirect_uri]"
        )
        return 2

    env_path = Path(sys.argv[1]).resolve()
    auth_url = sys.argv[2].strip() if len(sys.argv) > 2 else ""
    redirect_uri = (
        sys.argv[3].strip()
        if len(sys.argv) > 3
        else "http://127.0.0.1:28463/oauth/callback"
    )
    env = load_env(env_path)
    auth_url = resolve_auth_url(env_path, auth_url, redirect_uri)

    session_token = env.get("OPENAI_SESSION_TOKEN", "").strip()
    login_email = os.getenv("OPENAI_LOGIN_EMAIL", "").strip()
    workspace_label = os.getenv("OPENAI_WORKSPACE_LABEL", "myWorkspace").strip()
    headless = os.getenv("PW_HEADLESS", "1").strip() not in {"0", "false", "False"}
    if not session_token:
        print(json.dumps({"ok": False, "error": "missing OPENAI_SESSION_TOKEN"}, ensure_ascii=False))
        return 1

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": f"import playwright failed: {exc}"}, ensure_ascii=False))
        return 1

    logs: list[dict[str, object]] = []
    final_payload: dict[str, object] = {"ok": False}
    direct_result_payload: dict[str, object] | None = None
    runtime_state: dict[str, str] = {"last_oidc_authorize_url": ""}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            context.add_cookies(build_session_cookies(session_token))

            warmup_page = context.new_page()
            warmup_page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=120000)
            time.sleep(5)
            logs.append(
                {
                    "type": "warmup",
                    "final_url": warmup_page.url,
                    "title": warmup_page.title(),
                }
            )
            warmup_page.close()

            page = context.new_page()
            page.on(
                "request",
                lambda request: (
                    logs.append(
                        {
                            "type": "request",
                            "method": request.method,
                            "resource_type": request.resource_type,
                            "url": request.url,
                        }
                    ),
                    runtime_state.__setitem__("last_oidc_authorize_url", request.url)
                    if "/application/o/openai-custom-oidc/authorize" in request.url
                    else None,
                )
                if request.resource_type == "document"
                else None,
            )
            page.on(
                "framenavigated",
                lambda frame: logs.append(
                    {
                        "type": "navigated",
                        "url": frame.url,
                    }
                )
                if frame == page.main_frame
                else None,
            )

            page.on(
                "response",
                lambda response: logs.append(
                    {
                        "type": "response",
                        "status": response.status,
                        "url": response.url,
                    }
                ),
            )

            page.goto(auth_url, wait_until="domcontentloaded", timeout=120000)
            if login_email:
                email_selectors = [
                    'input[type="email"]',
                    'input[name="email"]',
                    'input[autocomplete="email"]',
                    'input[id="email"]',
                ]
                filled = False
                for selector in email_selectors:
                    locator = page.locator(selector).first
                    if locator.count() <= 0:
                        continue
                    locator.fill(login_email)
                    filled = True
                    logs.append(
                        {
                            "type": "filled_email",
                            "selector": selector,
                            "email": login_email,
                        }
                    )
                    break
                if filled:
                    submit_selectors = [
                        'button[type="submit"]',
                        'button[data-testid="continue-button"]',
                        'button:has-text("Continue")',
                        'button:has-text("继续")',
                    ]
                    clicked = False
                    for selector in submit_selectors:
                        locator = page.locator(selector).first
                        if locator.count() <= 0:
                            continue
                        locator.click()
                        clicked = True
                        logs.append(
                            {
                                "type": "clicked_submit",
                                "selector": selector,
                            }
                        )
                        break
                    if not clicked:
                        page.keyboard.press("Enter")
                        logs.append({"type": "pressed_enter"})
                    time.sleep(10)
            if workspace_label:
                workspace_selectors = [
                    f'button:has-text("{workspace_label}")',
                    f'text="{workspace_label}"',
                ]
                for selector in workspace_selectors:
                    locator = page.locator(selector).first
                    if locator.count() <= 0:
                        continue
                    locator.click()
                    logs.append(
                        {
                            "type": "clicked_workspace",
                            "selector": selector,
                            "workspace_label": workspace_label,
                        }
                    )
                    time.sleep(20)
                    break
            time.sleep(10)
            authorize_url = wait_for_runtime_oidc_authorize_url(runtime_state) or wait_for_oidc_authorize_url(logs)
            logs.append(
                {
                    "type": "oidc_authorize_detected",
                    "authorize_url": authorize_url,
                }
            )
            if login_email and authorize_url:
                direct_result = call_internal_direct_authorize(
                    authorize_url=authorize_url,
                    email=login_email,
                )
                direct_result_payload = dict(direct_result)
                logs.append(
                    {
                        "type": "direct_authorize_result",
                        "redirect_url": direct_result.get("redirect_url", ""),
                        "email": direct_result.get("email", login_email),
                    }
                )
                redirect_url = str(direct_result.get("redirect_url", "")).strip()
                if redirect_url:
                    page.goto(redirect_url, wait_until="domcontentloaded", timeout=120000)
                    time.sleep(10)

            final_payload = {
                "ok": True,
                "auth_url": auth_url,
                "headless": headless,
                "final_url": page.url,
                "title": page.title(),
                "html_snippet": page.content()[:4000],
                "body_text_snippet": (page.locator("body").inner_text(timeout=5000) or "")[:2000],
                "direct_authorize_result": direct_result_payload,
                "events": logs,
            }

            browser.close()
    except Exception as exc:  # noqa: BLE001
        final_payload = {
            "ok": False,
            "auth_url": auth_url,
            "headless": headless,
            "error": str(exc),
            "direct_authorize_result": direct_result_payload,
            "events": logs,
        }

    print(json.dumps(final_payload, ensure_ascii=False, indent=2))
    return 0 if final_payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
