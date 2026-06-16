"""用浏览器环境验证 OPENAI_SESSION_TOKEN 是否能拿到网页登录态。"""

from __future__ import annotations

import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

from tools.test_openai_oauth_browser import build_session_cookies, load_env


def main() -> int:
    env_path = Path(os.getenv("ENV_PATH", ".env")).resolve()
    env = load_env(env_path)
    session_token = env.get("OPENAI_SESSION_TOKEN", "").strip()
    if not session_token:
        print(json.dumps({"ok": False, "error": "missing OPENAI_SESSION_TOKEN"}, ensure_ascii=False))
        return 1

    headless = os.getenv("PW_HEADLESS", "1").strip() not in {"0", "false", "False"}
    target_url = os.getenv("TARGET_URL", "https://auth.openai.com/log-in").strip()
    wait_seconds = int(os.getenv("WAIT_SECONDS", "5").strip() or "5")
    logs: list[dict[str, object]] = []

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
                "Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0"
            )
        )
        cookie_targets = [
            "https://auth.openai.com",
            "https://chatgpt.com",
            "https://chat.openai.com",
        ]
        all_cookies: list[dict[str, object]] = []
        for target in cookie_targets:
            for cookie in build_session_cookies(session_token):
                copied = dict(cookie)
                copied["url"] = target
                all_cookies.append(copied)
        context.add_cookies(all_cookies)
        auth_cookies = context.cookies("https://auth.openai.com")

        page = context.new_page()
        page.on(
            "response",
            lambda response: logs.append(
                {
                    "status": response.status,
                    "url": response.url,
                }
            )
            if "session" in response.url or "auth" in response.url
            else None,
        )

        page.goto(target_url, wait_until="domcontentloaded", timeout=120000)
        if wait_seconds > 0:
            page.wait_for_timeout(wait_seconds * 1000)
        payload = {
            "ok": True,
            "headless": headless,
            "target_url": target_url,
            "wait_seconds": wait_seconds,
            "auth_cookie_names": [item.get("name", "") for item in auth_cookies],
            "auth_cookie_count": len(auth_cookies),
            "final_url": page.url,
            "title": page.title(),
            "html_snippet": page.content()[:3000],
            "events": logs,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
