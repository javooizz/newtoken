"""自动跑通 OpenAI OAuth 到 Sub2API 导入。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from newtoken.sub2api.remote_oauth import (
    complete_openai_oauth_account_creation,
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


def build_session_cookies(session_token: str) -> list[dict[str, object]]:
    token = session_token.strip()
    if not token:
        return []
    names = [
        "__Secure-next-auth.session-token",
        "next-auth.session-token",
        "__Secure-authjs.session-token",
        "authjs.session-token",
    ]
    chunks = [token[index : index + 3800] for index in range(0, len(token), 3800)]
    cookies: list[dict[str, object]] = []
    for name in names:
        if len(chunks) == 1:
            cookies.append(
                {
                    "name": name,
                    "value": chunks[0],
                    "url": "https://auth.openai.com",
                    "secure": True,
                }
            )
            continue
        for index, chunk in enumerate(chunks):
            cookies.append(
                {
                    "name": f"{name}.{index}",
                    "value": chunk,
                    "url": "https://auth.openai.com",
                    "secure": True,
                }
            )
    return cookies


def call_internal_direct_authorize(
    *,
    authorize_url: str,
    email: str,
    full_name: str,
    oidc_env_path: Path,
) -> dict[str, object]:
    oidc_env = load_env(oidc_env_path)
    bypass_key = oidc_env.get("GPTOIDC_INTERNAL_BYPASS_KEY", "").strip()
    if not bypass_key:
        raise RuntimeError("missing GPTOIDC_INTERNAL_BYPASS_KEY")

    parsed = urlsplit(authorize_url)
    endpoint = f"{parsed.scheme}://{parsed.netloc}/api/internal/direct-authorize"
    body = json.dumps(
        {
            "authorize_url": authorize_url,
            "email": email,
            "full_name": full_name,
        }
    ).encode("utf-8")
    request = Request(
        endpoint,
        data=body,
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


def wait_for_redirect_url(state: dict[str, object], timeout_seconds: float = 60.0) -> str:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        redirect_url = str(state.get("redirect_url", "")).strip()
        if redirect_url:
            return redirect_url
        time.sleep(0.2)
    return str(state.get("redirect_url", "")).strip()


def wait_for_workspace(page, workspace_label: str, timeout_seconds: float = 45.0) -> str:
    deadline = time.time() + timeout_seconds
    selectors = (
        f'button:has-text("{workspace_label}")',
        f'text="{workspace_label}"',
    )
    while time.time() < deadline:
        for selector in selectors:
            locator = page.locator(selector).first
            if locator.count() <= 0:
                continue
            if not locator.is_visible():
                continue
            return selector
        text_locator = page.get_by_text(workspace_label).first
        if text_locator.count() > 0 and text_locator.is_visible():
            return f"get_by_text:{workspace_label}"
        page.wait_for_timeout(1000)
    return ""


def maybe_click(locator) -> bool:
    if locator.count() <= 0:
        return False
    if not locator.is_visible():
        return False
    locator.click()
    return True


def main() -> int:
    from playwright.sync_api import sync_playwright

    env_path = Path(os.getenv("ENV_PATH", "/opt/sub2api-standalone-source/.env")).resolve()
    oidc_env_path = Path(
        os.getenv("OIDC_ENV_PATH", "/opt/sub2api-standalone-source/oidc/.env")
    ).resolve()
    redirect_uri = os.getenv("REDIRECT_URI", "http://localhost:1455/auth/callback").strip()
    login_email = os.getenv("OPENAI_LOGIN_EMAIL", "user@example.com").strip().lower()
    full_name = os.getenv("OPENAI_FULL_NAME", "").strip()
    workspace_label = os.getenv("OPENAI_WORKSPACE_LABEL", "myWorkspace").strip()
    target_status = os.getenv("SUB2API_TARGET_STATUS", "inactive").strip().lower() or "inactive"
    headless = os.getenv("PW_HEADLESS", "0").strip() in {"1", "true", "True"}
    env = load_env(env_path)
    session_token = env.get("OPENAI_SESSION_TOKEN", "").strip()

    defaults = load_openai_oauth_defaults(str(env_path))
    pending_result = create_openai_oauth_pending_session(
        base_url=defaults.get("base_url", ""),
        admin_api_key=defaults.get("admin_api_key", ""),
        proxy_id=defaults.get("proxy_id", ""),
        proxy_url=defaults.get("proxy_url", ""),
        proxy_name=defaults.get("proxy_name", "default"),
        redirect_uri=redirect_uri,
        account_name=login_email,
        group_ids=[],
        group_name=defaults.get("group_name", "cc"),
        concurrency=defaults.get("concurrency", "10"),
    )
    pending_session = pending_result["pending_session"]
    remote_config = pending_result["remote_config"]

    state: dict[str, object] = {
        "auth_url": pending_session.auth_url,
        "oidc_authorize_url": "",
        "redirect_url": "",
        "direct_authorize_result": None,
        "callback_url": "",
        "last_page_url": "",
        "last_body_text": "",
    }
    logs: list[dict[str, object]] = []

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=headless,
                args=[
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
            if session_token:
                context.add_cookies(build_session_cookies(session_token))

            def handle_oidc_authorize(route, request) -> None:
                if state.get("redirect_url"):
                    route.abort()
                    return
                authorize_url = request.url
                state["oidc_authorize_url"] = authorize_url
                logs.append({"type": "oidc_authorize_request", "url": authorize_url})
                direct_result = call_internal_direct_authorize(
                    authorize_url=authorize_url,
                    email=login_email,
                    full_name=full_name,
                    oidc_env_path=oidc_env_path,
                )
                state["direct_authorize_result"] = direct_result
                state["redirect_url"] = str(direct_result.get("redirect_url", "")).strip()
                logs.append(
                    {
                        "type": "direct_authorize_result",
                        "redirect_url": state["redirect_url"],
                        "email": direct_result.get("email", login_email),
                    }
                )
                route.abort()

            def handle_localhost_callback(route, request) -> None:
                state["callback_url"] = request.url
                logs.append({"type": "localhost_callback", "url": request.url})
                route.fulfill(status=200, content_type="text/plain", body="callback captured")

            context.route("**/application/o/openai-custom-oidc/authorize*", handle_oidc_authorize)
            context.route("http://localhost:1455/**", handle_localhost_callback)

            warmup_page = context.new_page()
            warmup_page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=120000)
            warmup_page.wait_for_timeout(5000)
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
                lambda request: logs.append(
                    {
                        "type": "request",
                        "method": request.method,
                        "resource_type": request.resource_type,
                        "url": request.url,
                    }
                )
                if request.resource_type == "document"
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
            page.on(
                "framenavigated",
                lambda frame: logs.append({"type": "navigated", "url": frame.url})
                if frame == page.main_frame
                else None,
            )

            page.goto(pending_session.auth_url, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(5000)

            email_locator = page.locator('input[type="email"], input[name="email"], input[autocomplete="email"]').first
            if email_locator.count() > 0:
                email_locator.fill(login_email)
                logs.append({"type": "filled_email", "email": login_email})
                submit_locator = page.locator('button[type="submit"], button:has-text("Continue"), button:has-text("继续")').first
                if maybe_click(submit_locator):
                    logs.append({"type": "clicked_submit"})
                else:
                    page.keyboard.press("Enter")
                    logs.append({"type": "pressed_enter"})
            page.wait_for_timeout(10000)
            state["last_page_url"] = page.url
            state["last_body_text"] = page.locator("body").inner_text(timeout=5000)[:2000]
            logs.append(
                {
                    "type": "post_submit_page",
                    "url": state["last_page_url"],
                    "body_text": state["last_body_text"],
                }
            )
            selector = wait_for_workspace(page, workspace_label)
            workspace_clicked = False
            for selector in (selector,) if selector else ():
                workspace_locator = (
                    page.get_by_text(workspace_label).first
                    if selector.startswith("get_by_text:")
                    else page.locator(selector).first
                )
                if not maybe_click(workspace_locator):
                    continue
                logs.append(
                    {
                        "type": "clicked_workspace",
                        "workspace_label": workspace_label,
                        "selector": selector,
                    }
                )
                workspace_clicked = True
                break
            if not workspace_clicked:
                state["last_page_url"] = page.url
                state["last_body_text"] = page.locator("body").inner_text(timeout=5000)[:2000]
                raise RuntimeError(
                    f"workspace button not found: {workspace_label}, page={page.url}"
                )

            redirect_url = wait_for_redirect_url(state)
            if not redirect_url:
                raise RuntimeError("did not capture direct-authorize redirect_url")

            page.goto(redirect_url, wait_until="domcontentloaded", timeout=120000)

            consent_clicked = False
            deadline = time.time() + 180
            while time.time() < deadline:
                callback_url = str(state.get("callback_url", "")).strip()
                if callback_url:
                    break
                current_url = page.url
                if not consent_clicked and (
                    "sign-in-with-chatgpt" in current_url or "/consent" in current_url
                ):
                    consent_selectors = [
                        'button[type="submit"]',
                        'button:has-text("Continue")',
                        'button:has-text("Authorize")',
                        'button:has-text("Allow")',
                        'button:has-text("同意")',
                        'button:has-text("继续")',
                    ]
                    for selector in consent_selectors:
                        locator = page.locator(selector).first
                        if maybe_click(locator):
                            consent_clicked = True
                            logs.append({"type": "clicked_consent", "selector": selector})
                            break
                page.wait_for_timeout(1000)

            callback_url = str(state.get("callback_url", "")).strip()
            if not callback_url:
                raise RuntimeError(f"callback url not captured, final page={page.url}")

            import_result = complete_openai_oauth_account_creation(
                remote_config=remote_config,
                pending_session=pending_session,
                auth_input=callback_url,
                target_status=target_status,
            )

            browser.close()
    except Exception as exc:  # noqa: BLE001
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "state": state,
                    "logs": logs,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "auth_url": pending_session.auth_url,
                "callback_url": state.get("callback_url", ""),
                "direct_authorize_result": state.get("direct_authorize_result"),
                "import_result": import_result,
                "logs": logs,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
