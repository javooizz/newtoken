"""走自然 OIDC/WorkOS 浏览器链路，把新号导进 Sub2API。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

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
    locator.click()
    return True


def write_state(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def wait_for_workspace(page, label: str, timeout_seconds: float = 45.0) -> str:
    deadline = time.time() + timeout_seconds
    selectors = (f'button:has-text("{label}")', f'text="{label}"')
    while time.time() < deadline:
        for selector in selectors:
            locator = page.locator(selector).first
            if locator.count() > 0 and locator.is_visible():
                return selector
        text_locator = page.get_by_text(label).first
        if text_locator.count() > 0 and text_locator.is_visible():
            return f"get_by_text:{label}"
        page.wait_for_timeout(1000)
    return ""


def resolve_cloudflare_challenge(page, timeout_seconds: float = 60.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        body_text = page.locator("body").inner_text(timeout=5000)
        if "Performing security verification" not in body_text and "security verification" not in body_text.lower():
            return
        for frame in page.frames:
            if "challenges.cloudflare.com" not in frame.url:
                continue
            for selector in ('input[type="checkbox"]', '[role="checkbox"]'):
                locator = frame.locator(selector).first
                if locator.count() <= 0:
                    continue
                try:
                    if locator.is_visible():
                        locator.click(timeout=3000)
                        page.wait_for_timeout(5000)
                        break
                except Exception:
                    continue
        page.wait_for_timeout(3000)


def describe_frames(page) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for frame in page.frames:
        summary: dict[str, object] = {"url": frame.url}
        for selector in ('input[type="checkbox"]', '[role="checkbox"]', 'button', 'label', 'iframe'):
            try:
                summary[selector] = frame.locator(selector).count()
            except Exception as exc:  # noqa: BLE001
                summary[f'{selector}_error'] = str(exc)
        items.append(summary)
    return items


def main() -> int:
    from playwright.sync_api import sync_playwright

    env_path = Path(os.getenv("ENV_PATH", "/opt/sub2api-standalone-source/.env")).resolve()
    state_file = Path(os.getenv("STATE_FILE", "/tmp/run_openai_native_oidc_import_state.json")).resolve()
    redirect_uri = os.getenv("REDIRECT_URI", "http://localhost:1455/auth/callback").strip()
    login_email = os.getenv("OPENAI_LOGIN_EMAIL", "user@example.com").strip().lower()
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
        "stage": "init",
        "auth_url": pending_session.auth_url,
        "callback_url": "",
        "current_page_url": "",
        "current_body_text": "",
    }
    logs: list[dict[str, object]] = []
    write_state(state_file, {"state": state, "logs": logs})

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

            warmup_page = context.new_page()
            warmup_page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=120000)
            warmup_page.wait_for_timeout(5000)
            logs.append({"type": "warmup", "url": warmup_page.url, "title": warmup_page.title()})
            warmup_page.close()
            state["stage"] = "warmup_done"
            write_state(state_file, {"state": state, "logs": logs})

            page.goto(pending_session.auth_url, wait_until="domcontentloaded", timeout=120000)
            state["stage"] = "auth_page_loaded"
            page.wait_for_timeout(20000)
            state["frame_descriptions"] = describe_frames(page)
            resolve_cloudflare_challenge(page)
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
            state["current_body_text"] = page.locator("body").inner_text(timeout=5000)[:2000]
            write_state(state_file, {"state": state, "logs": logs})

            selector = wait_for_workspace(page, workspace_label)
            if not selector:
                raise RuntimeError(f"workspace button not found, page={page.url}")
            workspace_locator = page.get_by_text(workspace_label).first if selector.startswith("get_by_text:") else page.locator(selector).first
            if not maybe_click(workspace_locator):
                raise RuntimeError(f"workspace click failed, page={page.url}")
            logs.append({"type": "clicked_workspace", "selector": selector, "workspace_label": workspace_label})
            state["stage"] = "workspace_clicked"
            write_state(state_file, {"state": state, "logs": logs})

            consent_clicked = False
            last_state_write = 0.0
            deadline = time.time() + 240
            while time.time() < deadline:
                callback_url = str(state.get("callback_url", "")).strip()
                if callback_url:
                    break
                current_url = page.url
                state["current_page_url"] = current_url
                if not consent_clicked and (
                    "signin-consent" in current_url or "sign-in-with-chatgpt" in current_url or "/consent" in current_url
                ):
                    for selector in (
                        'button[type="submit"]',
                        'button:has-text("Approve sign-in")',
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
        print(json.dumps({"ok": False, "error": str(exc), "state": state, "logs": logs}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps({"ok": True, "state": state, "logs": logs, "import_result": import_result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
