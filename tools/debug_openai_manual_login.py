"""抓手动邮箱登录链路里的控制台和 XHR 异常。"""

from __future__ import annotations

import json
import os
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
            cookies.append({"name": name, "value": chunks[0], "url": "https://auth.openai.com", "secure": True})
            continue
        for index, chunk in enumerate(chunks):
            cookies.append({
                "name": f"{name}.{index}",
                "value": chunk,
                "url": "https://auth.openai.com",
                "secure": True,
            })
    return cookies


def main() -> int:
    env_path = Path(os.getenv("ENV_PATH", "/opt/sub2api-standalone-source/.env")).resolve()
    state_file = Path(os.getenv("STATE_FILE", "/tmp/debug_openai_manual_login.json")).resolve()
    redirect_uri = os.getenv("REDIRECT_URI", "http://localhost:1455/auth/callback").strip()
    login_email = os.getenv("OPENAI_LOGIN_EMAIL", "user@example.com").strip().lower()
    headless = os.getenv("PW_HEADLESS", "1").strip() not in {"0", "false", "False"}

    env = load_env(env_path)
    session_token = env.get("OPENAI_SESSION_TOKEN", "").strip()
    defaults = load_openai_oauth_defaults(str(env_path))
    pending = create_openai_oauth_pending_session(
        base_url=defaults.get("base_url", ""),
        admin_api_key=defaults.get("admin_api_key", ""),
        proxy_id=defaults.get("proxy_id", ""),
        proxy_url=defaults.get("proxy_url", ""),
        proxy_name=defaults.get("proxy_name", "default"),
        redirect_uri=redirect_uri,
        group_ids=[],
        group_name=defaults.get("group_name", "cc"),
        concurrency=defaults.get("concurrency", "10"),
    )["pending_session"]

    output: dict[str, object] = {
        "auth_url": pending.auth_url,
        "events": [],
    }

    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=headless, args=["--disable-dev-shm-usage", "--no-sandbox"])
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            if session_token:
                context.add_cookies(build_session_cookies(session_token))
            page = context.new_page()
            def record(kind: str, payload: dict[str, object]) -> None:
                payload["kind"] = kind
                events = output.get("events")
                if isinstance(events, list):
                    events.append(payload)

            page.on("console", lambda msg: record("console", {"type": msg.type, "text": msg.text}))
            page.on("pageerror", lambda exc: record("pageerror", {"text": str(exc)}))
            page.on(
                "requestfailed",
                lambda req: record(
                    "requestfailed",
                    {"url": req.url, "method": req.method, "resource_type": req.resource_type, "failure": req.failure},
                ),
            )

            def on_response(response) -> None:
                if response.request.resource_type not in {"document", "fetch", "xhr"}:
                    return
                item: dict[str, object] = {
                    "url": response.url,
                    "status": response.status,
                    "resource_type": response.request.resource_type,
                }
                try:
                    content_type = response.headers.get("content-type", "")
                    item["content_type"] = content_type
                    if "application/json" not in content_type.lower():
                        item["body_prefix"] = response.text()[:500]
                except Exception as exc:  # noqa: BLE001
                    item["body_error"] = str(exc)
                record("response", item)

            page.on("response", on_response)

            page.goto(pending.auth_url, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(12000)
            output["after_goto_url"] = page.url
            output["after_goto_body"] = page.locator("body").inner_text(timeout=5000)[:2000]

            email_locator = page.locator('input[type="email"], input[name="email"], input[autocomplete="email"]').first
            if email_locator.count() > 0:
                email_locator.fill(login_email)
                submit = page.locator('button[type="submit"], button:has-text("Continue")').first
                if submit.count() > 0:
                    submit.click()
                else:
                    page.keyboard.press("Enter")

            page.wait_for_timeout(15000)
            output["after_submit_url"] = page.url
            output["after_submit_body"] = page.locator("body").inner_text(timeout=5000)[:2000]
            browser.close()
    except Exception as exc:  # noqa: BLE001
        output["error"] = str(exc)
        state_file.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 1

    state_file.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
