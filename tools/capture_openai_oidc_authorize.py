"""只跑到项目 OIDC authorize URL，然后立刻返回。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from newtoken.sub2api.remote_oauth import create_openai_oauth_pending_session, load_openai_oauth_defaults


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


def wait_for_workspace(page, workspace_label: str, timeout_seconds: float = 45.0) -> str:
    deadline = time.time() + timeout_seconds
    selectors = (
        f'button:has-text("{workspace_label}")',
        f'text="{workspace_label}"',
    )
    while time.time() < deadline:
        for selector in selectors:
            locator = page.locator(selector).first
            if locator.count() <= 0 or not locator.is_visible():
                continue
            return selector
        text_locator = page.get_by_text(workspace_label).first
        if text_locator.count() > 0 and text_locator.is_visible():
            return f"get_by_text:{workspace_label}"
        page.wait_for_timeout(1000)
    return ""


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
    redirect_uri = os.getenv("REDIRECT_URI", "http://localhost:1455/auth/callback").strip()
    login_email = os.getenv("OPENAI_LOGIN_EMAIL", "user@example.com").strip().lower()
    workspace_label = os.getenv("OPENAI_WORKSPACE_LABEL", "myWorkspace").strip()
    headless = os.getenv("PW_HEADLESS", "0").strip() in {"1", "true", "True"}
    state_file = Path(os.getenv("STATE_FILE", "/tmp/capture_openai_oidc_authorize_state.json")).resolve()

    env = load_env(env_path)
    session_token = env.get("OPENAI_SESSION_TOKEN", "").strip()
    defaults = load_openai_oauth_defaults(str(env_path))
    pending_session = create_openai_oauth_pending_session(
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
    )["pending_session"]

    logs: list[dict[str, object]] = []
    state = {"stage": "init", "oidc_authorize_url": ""}
    write_state(state_file, {"state": state, "logs": logs})

    try:
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

            def handle_oidc_authorize(route, request) -> None:
                state["oidc_authorize_url"] = request.url
                state["stage"] = "oidc_authorize_captured"
                logs.append({"type": "oidc_authorize_request", "url": request.url})
                write_state(state_file, {"state": state, "logs": logs})
                route.abort()

            context.route("**/application/o/openai-custom-oidc/authorize*", handle_oidc_authorize)

            warmup_page = context.new_page()
            warmup_page.goto("https://chatgpt.com/", wait_until="domcontentloaded", timeout=120000)
            warmup_page.wait_for_timeout(5000)
            state["stage"] = "warmup_done"
            logs.append({"type": "warmup", "url": warmup_page.url, "title": warmup_page.title()})
            write_state(state_file, {"state": state, "logs": logs})
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
                "framenavigated",
                lambda frame: logs.append({"type": "navigated", "url": frame.url})
                if frame == page.main_frame
                else None,
            )

            page.goto(pending_session.auth_url, wait_until="domcontentloaded", timeout=120000)
            state["stage"] = "auth_page_loaded"
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
            state["stage"] = "email_submitted"
            write_state(state_file, {"state": state, "logs": logs})

            page.wait_for_timeout(10000)
            logs.append(
                {
                    "type": "post_submit_page",
                    "url": page.url,
                    "body_text": page.locator("body").inner_text(timeout=5000)[:2000],
                }
            )
            state["stage"] = "post_submit_ready"
            write_state(state_file, {"state": state, "logs": logs})

            selector = wait_for_workspace(page, workspace_label)
            if not selector:
                state["stage"] = "workspace_not_found"
                write_state(state_file, {"state": state, "logs": logs})
                raise RuntimeError(f"workspace button not found, page={page.url}")

            workspace_locator = (
                page.get_by_text(workspace_label).first
                if selector.startswith("get_by_text:")
                else page.locator(selector).first
            )
            if not maybe_click(workspace_locator):
                state["stage"] = "workspace_click_failed"
                write_state(state_file, {"state": state, "logs": logs})
                raise RuntimeError(f"workspace click failed, page={page.url}")
            logs.append({"type": "clicked_workspace", "selector": selector, "workspace_label": workspace_label})
            state["stage"] = "workspace_clicked"
            write_state(state_file, {"state": state, "logs": logs})

            deadline = time.time() + 90
            while time.time() < deadline:
                if state["oidc_authorize_url"]:
                    break
                page.wait_for_timeout(500)

            state["stage"] = "finished_wait"
            write_state(state_file, {"state": state, "logs": logs})

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
                    "auth_url": pending_session.auth_url,
                    "oidc_authorize_url": state["oidc_authorize_url"],
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
                "ok": bool(state["oidc_authorize_url"]),
                "auth_url": pending_session.auth_url,
                "oidc_authorize_url": state["oidc_authorize_url"],
                "logs": logs,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if state["oidc_authorize_url"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
