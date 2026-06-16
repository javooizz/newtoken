"""用 HTTP 跑完 WorkOS 前半段，再用浏览器完成 OpenAI callback 和导入。"""

from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

import requests

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


def build_auth_openai_callback_url(
    *,
    login_email: str,
    full_name: str,
    oidc_env_path: Path,
) -> tuple[str, dict[str, object], str]:
    client = requests.Session()
    external_state = f"{uuid.uuid4()}|False"
    authorize_response = client.get(
        "https://external.auth.openai.com/sso/authorize",
        params={
            "client_id": "client_01H89S896C9YTVBWZVZWANQPDK",
            "redirect_uri": "https://auth.openai.com/api/accounts/callback/workos",
            "response_type": "code",
            "connection": "conn_01KV28WJ01A1P0PTYT406BC88F",
            "state": external_state,
        },
        allow_redirects=False,
        timeout=60,
    )
    oidc_authorize_url = str(authorize_response.headers.get("location", "")).strip()
    if not oidc_authorize_url:
        raise RuntimeError("external auth authorize did not return OIDC authorize url")

    direct_result = call_internal_direct_authorize(
        authorize_url=oidc_authorize_url,
        email=login_email,
        full_name=full_name,
        oidc_env_path=oidc_env_path,
    )

    consent_page = client.get(
        str(direct_result.get("redirect_url", "")).strip(),
        allow_redirects=True,
        timeout=60,
    )
    interstitial_token = re.search(
        r'name="interstitial_token" value="([^"]+)"', consent_page.text
    )
    csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', consent_page.text)
    if not interstitial_token or not csrf_token:
        raise RuntimeError("workos signin-consent form fields not found")

    confirm_response = client.post(
        urljoin(consent_page.url, "/sso/interstitial"),
        data={
            "interstitial_token": interstitial_token.group(1),
            "action": "confirm",
            "csrf_token": csrf_token.group(1),
        },
        allow_redirects=False,
        timeout=60,
    )
    auth_callback_url = str(confirm_response.headers.get("location", "")).strip()
    if not auth_callback_url:
        raise RuntimeError("workos interstitial confirm did not return auth.openai callback")
    return auth_callback_url, direct_result, oidc_authorize_url


def maybe_click(locator) -> bool:
    if locator.count() <= 0 or not locator.is_visible():
        return False
    locator.click()
    return True


def write_state(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    from playwright.sync_api import sync_playwright

    env_path = Path(os.getenv("ENV_PATH", "/opt/sub2api-standalone-source/.env")).resolve()
    oidc_env_path = Path(
        os.getenv("OIDC_ENV_PATH", "/opt/sub2api-standalone-source/oidc/.env")
    ).resolve()
    redirect_uri = os.getenv("REDIRECT_URI", "http://localhost:1455/auth/callback").strip()
    login_email = os.getenv("OPENAI_LOGIN_EMAIL", "user@example.com").strip().lower()
    full_name = os.getenv("OPENAI_FULL_NAME", "").strip()
    target_status = os.getenv("SUB2API_TARGET_STATUS", "inactive").strip().lower() or "inactive"
    headless = os.getenv("PW_HEADLESS", "0").strip() in {"1", "true", "True"}
    state_file = Path(os.getenv("STATE_FILE", "/tmp/run_openai_workos_callback_import_state.json")).resolve()

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

    logs: list[dict[str, object]] = []
    state: dict[str, object] = {
        "stage": "init",
        "auth_openai_callback_url": "",
        "oidc_authorize_url": "",
        "direct_authorize_result": None,
        "callback_url": "",
        "current_page_url": "",
        "current_body_text": "",
    }
    write_state(state_file, {"state": state, "logs": logs})

    try:
        auth_callback_url, direct_result, oidc_authorize_url = build_auth_openai_callback_url(
            login_email=login_email,
            full_name=full_name,
            oidc_env_path=oidc_env_path,
        )
        state["stage"] = "workos_chain_ready"
        state["auth_openai_callback_url"] = auth_callback_url
        state["oidc_authorize_url"] = oidc_authorize_url
        state["direct_authorize_result"] = direct_result
        logs.append({"type": "oidc_authorize_url", "url": oidc_authorize_url})
        logs.append({"type": "workos_callback_url", "url": auth_callback_url})
        write_state(state_file, {"state": state, "logs": logs})

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=headless,
                args=["--disable-dev-shm-usage", "--no-sandbox"],
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

            def handle_localhost_callback(route, request) -> None:
                state["callback_url"] = request.url
                state["stage"] = "localhost_callback_captured"
                logs.append({"type": "localhost_callback", "url": request.url})
                write_state(state_file, {"state": state, "logs": logs})
                route.fulfill(status=200, content_type="text/plain", body="callback captured")

            context.route("http://localhost:1455/**", handle_localhost_callback)

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
            state["stage"] = "auth_session_seeded"
            state["current_page_url"] = page.url
            state["current_body_text"] = page.locator("body").inner_text(timeout=5000)[:2000]
            write_state(state_file, {"state": state, "logs": logs})

            page.goto(auth_callback_url, wait_until="domcontentloaded", timeout=120000)
            state["stage"] = "auth_openai_callback_loaded"
            state["current_page_url"] = page.url
            state["current_body_text"] = page.locator("body").inner_text(timeout=5000)[:2000]
            write_state(state_file, {"state": state, "logs": logs})
            deadline = time.time() + 180
            consent_clicked = False
            last_state_write = 0.0
            while time.time() < deadline:
                callback_url = str(state.get("callback_url", "")).strip()
                if callback_url:
                    break
                current_url = page.url
                state["current_page_url"] = current_url
                if not consent_clicked and (
                    "sign-in-with-chatgpt" in current_url or "/consent" in current_url
                ):
                    for selector in (
                        'button[type="submit"]',
                        'button:has-text("Continue")',
                        'button:has-text("Authorize")',
                        'button:has-text("Allow")',
                        'button:has-text("同意")',
                        'button:has-text("继续")',
                    ):
                        if maybe_click(page.locator(selector).first):
                            consent_clicked = True
                            state["stage"] = "consent_clicked"
                            logs.append({"type": "clicked_consent", "selector": selector})
                            write_state(state_file, {"state": state, "logs": logs})
                            break
                now = time.time()
                if now - last_state_write >= 3:
                    state["current_body_text"] = page.locator("body").inner_text(timeout=5000)[:2000]
                    write_state(state_file, {"state": state, "logs": logs})
                    last_state_write = now
                page.wait_for_timeout(1000)

            callback_url = str(state.get("callback_url", "")).strip()
            if not callback_url:
                state["stage"] = "callback_not_captured"
                state["current_page_url"] = page.url
                state["current_body_text"] = page.locator("body").inner_text(timeout=5000)[:2000]
                write_state(state_file, {"state": state, "logs": logs})
                raise RuntimeError(f"callback url not captured, final page={page.url}")

            import_result = complete_openai_oauth_account_creation(
                remote_config=remote_config,
                pending_session=pending_session,
                auth_input=callback_url,
                target_status=target_status,
            )
            state["stage"] = "import_completed"
            write_state(state_file, {"state": state, "logs": logs, "import_result": import_result})
            browser.close()
    except Exception as exc:  # noqa: BLE001
        state["stage"] = "error"
        state["error"] = str(exc)
        write_state(state_file, {"state": state, "logs": logs})
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
                "callback_url": state["callback_url"],
                "state": state,
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
