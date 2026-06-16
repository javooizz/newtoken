"""用 Camoufox 跑完整 OpenAI SSO 链并导入 Sub2API。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from newtoken.common.camoufox_runtime import Camoufox, build_camoufox_context_options, build_camoufox_launch_options
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


def maybe_click(locator) -> bool:
    if locator.count() <= 0 or not locator.is_visible():
        return False
    try:
        locator.click(no_wait_after=True)
    except Exception:
        locator.click(force=True, no_wait_after=True)
    return True


def split_email(email: str) -> tuple[str, str]:
    parts = email.strip().lower().split("@", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise RuntimeError(f"invalid login email: {email}")
    return parts[0], parts[1]


def handle_sso_bypass(page, login_email: str, bypass_key: str, logs: list[dict[str, object]]) -> bool:
    if "/sso" not in page.url:
        return False
    if not bypass_key:
        raise RuntimeError("missing OIDC SSO bypass key for /sso flow")

    email_prefix, email_domain = split_email(login_email)
    prefix_input = page.locator('input[name="email_prefix"]').first
    card_input = page.locator('input[name="card_key"]').first
    if prefix_input.count() <= 0 or card_input.count() <= 0:
        return False

    prefix_input.fill(email_prefix)
    domain_select = page.locator('select[name="email_domain"]').first
    if domain_select.count() > 0:
        try:
            domain_select.select_option(value=email_domain)
        except Exception:
            logs.append({"type": "sso_domain_select_miss", "domain": email_domain})
    card_input.fill(bypass_key)

    full_name_input = page.locator('input[name="full_name"]').first
    if full_name_input.count() > 0:
        full_name_input.fill("")

    submit_locator = page.locator('button[type="submit"], button:has-text("继续")').first
    if maybe_click(submit_locator):
        logs.append({"type": "sso_bypass_submitted", "email": login_email})
    else:
        page.keyboard.press("Enter")
        logs.append({"type": "sso_bypass_enter_submitted", "email": login_email})
    page.wait_for_timeout(3500)
    return True


def wait_for_workspace(page, label: str, timeout_seconds: float = 90.0) -> tuple[str, str] | None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        for selector in (f'button:has-text("{label}")', f'text="{label}"'):
            locator = page.locator(selector).first
            if locator.count() > 0 and locator.is_visible():
                return ("locator", selector)
        text_locator = page.get_by_text(label).first
        if text_locator.count() > 0 and text_locator.is_visible():
            return ("text", label)
        page.wait_for_timeout(1000)
    return None


def write_state(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    env_path = Path(os.getenv("ENV_PATH", "/opt/sub2api-standalone-source/.env")).resolve()
    oidc_env_path = Path(os.getenv("OIDC_ENV_PATH", "/opt/sub2api-standalone-source/oidc/.env")).resolve()
    state_file = Path(os.getenv("STATE_FILE", "/tmp/run_openai_camoufox_import_state.json")).resolve()
    redirect_uri = os.getenv("REDIRECT_URI", "http://localhost:1455/auth/callback").strip()
    login_email = os.getenv("OPENAI_LOGIN_EMAIL", "user@example.com").strip().lower()
    workspace_label = os.getenv("OPENAI_WORKSPACE_LABEL", "myWorkspace").strip()
    target_status = os.getenv("SUB2API_TARGET_STATUS", "inactive").strip().lower() or "inactive"
    headless = os.getenv("PW_HEADLESS", "0").strip() in {"1", "true", "True"}

    env = load_env(env_path)
    oidc_env = load_env(oidc_env_path)
    session_token = env.get("OPENAI_SESSION_TOKEN", "").strip()
    sso_bypass_key = os.getenv("OIDC_SSO_BYPASS_KEY", oidc_env.get("GPTOIDC_SSO_BYPASS_KEY", "")).strip()
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
        "stage": "init",
        "auth_url": pending_session.auth_url,
        "callback_url": "",
        "current_page_url": "",
        "current_body_text": "",
    }
    logs: list[dict[str, object]] = []
    write_state(state_file, {"state": state, "logs": logs})

    try:
        with Camoufox(**build_camoufox_launch_options(headless=headless)) as browser:
            context = browser.new_context(**build_camoufox_context_options())
            if session_token:
                context.add_cookies(build_session_cookies(session_token))

            def handle_localhost(route, request) -> None:
                state["callback_url"] = request.url
                state["stage"] = "localhost_callback_captured"
                logs.append({"type": "localhost_callback", "url": request.url})
                write_state(state_file, {"state": state, "logs": logs})
                route.fulfill(status=200, content_type="text/plain", body="callback captured")

            context.route("http://localhost:1455/**", handle_localhost)

            page = context.new_page()
            page.on(
                "request",
                lambda request: logs.append(
                    {
                        "type": "request",
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
            page.wait_for_timeout(15000)
            state["stage"] = "auth_loaded"
            state["current_page_url"] = page.url
            state["current_body_text"] = page.locator("body").inner_text(timeout=5000)[:3000]
            write_state(state_file, {"state": state, "logs": logs})

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
            state["stage"] = "email_submitted"
            state["current_page_url"] = page.url
            state["current_body_text"] = page.locator("body").inner_text(timeout=5000)[:3000]
            if handle_sso_bypass(page, login_email, sso_bypass_key, logs):
                state["stage"] = "sso_bypass_submitted"
                state["current_page_url"] = page.url
                state["current_body_text"] = page.locator("body").inner_text(timeout=5000)[:3000]
            write_state(state_file, {"state": state, "logs": logs})

            workspace = wait_for_workspace(page, workspace_label, timeout_seconds=30.0)
            if workspace:
                workspace_locator = page.locator(workspace[1]).first if workspace[0] == "locator" else page.get_by_text(workspace[1]).first
                if not maybe_click(workspace_locator):
                    raise RuntimeError(f"workspace click failed, page={page.url}")
                logs.append({"type": "clicked_workspace", "selector": workspace[1]})
                state["stage"] = "workspace_clicked"
                write_state(state_file, {"state": state, "logs": logs})
            elif "/sso" not in page.url and all(marker not in page.url for marker in ("signin-consent", "sign-in-with-chatgpt", "/consent", "/sso/interstitial", "/callback/workos", "/add-phone")):
                raise RuntimeError(f"workspace button not found, page={page.url}")

            consent_clicked = False
            deadline = time.time() + 300
            last_write = 0.0
            while time.time() < deadline:
                if state["callback_url"]:
                    break
                state["current_page_url"] = page.url
                state["current_body_text"] = page.locator("body").inner_text(timeout=5000)[:3000]
                if "/sso" in page.url:
                    handle_sso_bypass(page, login_email, sso_bypass_key, logs)
                    state["stage"] = "sso_bypass_submitted"
                if not consent_clicked and (
                    "signin-consent" in page.url
                    or "sign-in-with-chatgpt" in page.url
                    or "/consent" in page.url
                    or "/sso/interstitial" in page.url
                ):
                    for selector in (
                        'button:has-text("Approve sign-in")',
                        'button[type="submit"]',
                        'button:has-text("Continue")',
                        'button:has-text("Allow")',
                        'button:has-text("Authorize")',
                        'button:has-text("继续")',
                        'button:has-text("同意")',
                    ):
                        if maybe_click(page.locator(selector).first):
                            logs.append({"type": "clicked_consent", "selector": selector})
                            consent_clicked = True
                            state["stage"] = "consent_clicked"
                            write_state(state_file, {"state": state, "logs": logs})
                            break
                now = time.time()
                if now - last_write >= 3:
                    write_state(state_file, {"state": state, "logs": logs})
                    last_write = now
                page.wait_for_timeout(1000)

            if not state["callback_url"]:
                raise RuntimeError(f"callback url not captured, final page={page.url}")

            result = complete_openai_oauth_account_creation(
                remote_config=remote_config,
                pending_session=pending_session,
                auth_input=str(state["callback_url"]),
                target_status=target_status,
            )
            state["stage"] = "import_completed"
            write_state(state_file, {"state": state, "logs": logs, "result": result})
            print(json.dumps({"ok": True, "state": state, "result": result, "logs": logs}, ensure_ascii=False, indent=2))
            browser.close()
    except Exception as exc:  # noqa: BLE001
        state["stage"] = "error"
        state["error"] = str(exc)
        write_state(state_file, {"state": state, "logs": logs})
        print(json.dumps({"ok": False, "error": str(exc), "state": state, "logs": logs}, ensure_ascii=False, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
