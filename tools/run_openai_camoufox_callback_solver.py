"""专门测试并推进 auth.openai callback/workos 的最后一层挑战。"""

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


def write_state(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def maybe_click(locator) -> bool:
    if locator.count() <= 0 or not locator.is_visible():
        return False
    try:
        locator.click(no_wait_after=True)
    except Exception:
        locator.click(force=True, no_wait_after=True)
    return True


def is_localhost_callback_url(url: str, redirect_uri: str) -> bool:
    normalized = str(url or "").strip()
    target = str(redirect_uri or "").strip()
    return bool(normalized) and bool(target) and normalized.startswith(target)


def safe_click(page, selector: str) -> bool:
    try:
        page.locator(selector).first.click(timeout=1000)
        return True
    except Exception:
        return False


def click_iframe_center(page, selector: str) -> bool:
    try:
        locator = page.locator(selector).first
        if locator.count() <= 0 or not locator.is_visible():
            return False
        box = locator.bounding_box()
        if not box:
            return False
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        return True
    except Exception:
        return False


def click_host_div_center(page) -> bool:
    for selector in ("#BbLB6", "div[id='BbLB6']", "input[name='cf-turnstile-response']"):
        try:
            locator = page.locator(selector).first
            if locator.count() <= 0:
                continue
            box = locator.bounding_box()
            if not box:
                continue
            page.mouse.click(box["x"] + max(box["width"] / 2, 20), box["y"] + max(box["height"] / 2, 20))
            return True
        except Exception:
            continue
    return False


def click_challenge_frame_center(page) -> bool:
    for _ in range(4):
        try:
            for frame in page.frames:
                if "challenges.cloudflare.com" not in (frame.url or ""):
                    continue
                frame_element = frame.frame_element()
                if not frame_element:
                    continue
                box = frame_element.bounding_box()
                # Turnstile checkbox usually lives on the left side of the 300x65 iframe.
                for x_offset in (35, 45, 60):
                    y_offset = 32
                    try:
                        frame_element.click(
                            position={"x": x_offset, "y": y_offset},
                            force=True,
                            timeout=1500,
                        )
                    except Exception:
                        if box:
                            target_x = box["x"] + min(x_offset, box["width"] - 5)
                            target_y = box["y"] + min(y_offset, box["height"] - 5)
                            page.mouse.move(target_x, target_y)
                            page.mouse.click(target_x, target_y)
                    time.sleep(0.6)
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def click_closed_shadow_root(page) -> str:
    try:
        return str(
            page.evaluate(
                """
                () => {
                  const root = window.__lastClosedShadowRoot;
                  if (!root) {
                    return '';
                  }
                  const selectors = [
                    'input[type="checkbox"]',
                    '[role="checkbox"]',
                    'button',
                    'label',
                    'iframe',
                    '.cf-turnstile',
                    '[data-sitekey]',
                  ];
                  for (const selector of selectors) {
                    const node = root.querySelector(selector);
                    if (!node) {
                      continue;
                    }
                    if (selector === 'iframe') {
                      const rect = node.getBoundingClientRect();
                      node.ownerDocument.defaultView.scrollTo(rect.left, rect.top);
                    }
                    if (typeof node.click === 'function') {
                      node.click();
                      return `closed_shadow:${selector}`;
                    }
                  }
                  return '';
                }
                """
            )
        ).strip()
    except Exception:
        return ""


def extract_turnstile_sitekey(page) -> str:
    try:
        html = page.locator("body").evaluate("node => node.innerHTML")
    except Exception:
        return ""
    match = re.search(r"0x4[A-Za-z0-9_-]{10,}", str(html))
    return match.group(0) if match else ""


def inject_turnstile_widget(page, sitekey: str) -> str:
    if not sitekey:
        return ""
    try:
        return str(
            page.evaluate(
                """
                ({sitekey}) => {
                  let tokenInput = document.querySelector('input[name="cf-turnstile-response"]');
                  if (!tokenInput) {
                    tokenInput = document.createElement('input');
                    tokenInput.type = 'hidden';
                    tokenInput.name = 'cf-turnstile-response';
                    document.body.appendChild(tokenInput);
                  }

                  window._turnstileTokenCallback = function(token) {
                    tokenInput.value = token;
                  };

                  let widget = document.querySelector('.cf-turnstile[data-opencode="1"]');
                  if (!widget) {
                    widget = document.createElement('div');
                    widget.className = 'cf-turnstile';
                    widget.setAttribute('data-opencode', '1');
                    widget.setAttribute('data-sitekey', sitekey);
                    widget.style.position = 'fixed';
                    widget.style.top = '24px';
                    widget.style.left = '24px';
                    widget.style.zIndex = '999999';
                    widget.style.background = 'white';
                    widget.style.padding = '12px';
                    widget.style.border = '2px solid #2563eb';
                    widget.style.borderRadius = '8px';
                    document.body.appendChild(widget);
                  }

                  const renderWidget = () => {
                    if (!window.turnstile || !window.turnstile.render) {
                      return 'turnstile_api_missing';
                    }
                    try {
                      window.turnstile.render(widget, {
                        sitekey,
                        callback: function(token) {
                          window._turnstileTokenCallback(token);
                        },
                        'error-callback': function(error) {
                          console.log('turnstile error', error);
                        }
                      });
                      return 'turnstile_rendered';
                    } catch (error) {
                      return `turnstile_render_error:${error}`;
                    }
                  };

                  if (window.turnstile) {
                    return renderWidget();
                  }

                  const script = document.createElement('script');
                  script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js';
                  script.async = true;
                  script.defer = true;
                  script.onload = () => renderWidget();
                  document.head.appendChild(script);
                  return 'turnstile_script_injected';
                }
                """,
                {"sitekey": sitekey},
            )
        ).strip()
    except Exception:
        return ""


def find_and_click_checkbox(page) -> bool:
    for selector in (
        'iframe[src*="challenges.cloudflare.com"]',
        'iframe[src*="turnstile"]',
        'iframe[title*="widget"]',
    ):
        try:
            iframe_locator = page.locator(selector).first
            if iframe_locator.count() <= 0:
                continue
            iframe_element = iframe_locator.element_handle()
            frame = iframe_element.content_frame() if iframe_element else None
            if frame:
                for cb_selector in (
                    'input[type="checkbox"]',
                    '.cb-lb input[type="checkbox"]',
                    'label input[type="checkbox"]',
                ):
                    try:
                        checkbox = frame.locator(cb_selector).first
                        checkbox.click(timeout=2000)
                        return True
                    except Exception:
                        continue
            if click_iframe_center(page, selector):
                return True
        except Exception:
            continue
    return False


def try_click_strategies(page) -> str:
    strategies: list[tuple[str, callable]] = [
        ("closed_shadow", lambda: click_closed_shadow_root(page)),
        ("widget_iframe", lambda: safe_click(page, "iframe[id^='cf-chl-widget-']")),
        ("frame_hotspot", lambda: click_challenge_frame_center(page)),
        ("checkbox", lambda: find_and_click_checkbox(page)),
        ("host_div", lambda: click_host_div_center(page)),
        ("cf_turnstile", lambda: safe_click(page, ".cf-turnstile")),
        ("data_sitekey", lambda: safe_click(page, "[data-sitekey]")),
        ("turnstile_class", lambda: safe_click(page, "*[class*='turnstile']")),
        ("turnstile_iframe", lambda: safe_click(page, 'iframe[src*="turnstile"]')),
        ("turnstile_js", lambda: page.evaluate("document.querySelector('.cf-turnstile')?.click(); true")),
    ]
    for name, strategy in strategies:
        try:
            result = strategy()
            if isinstance(result, str) and result:
                return result
            if result is True or result is None:
                return name
        except Exception:
            continue
    return ""


def build_auth_callback_url(email: str, oidc_env_path: Path) -> tuple[str, dict[str, object], str]:
    oidc_env = load_env(oidc_env_path)
    client = requests.Session()
    state = f"{uuid.uuid4()}|False"
    authorize_resp = client.get(
        "https://external.auth.openai.com/sso/authorize",
        params={
            "client_id": "client_01H89S896C9YTVBWZVZWANQPDK",
            "redirect_uri": "https://auth.openai.com/api/accounts/callback/workos",
            "response_type": "code",
            "connection": "conn_01KV28WJ01A1P0PTYT406BC88F",
            "state": state,
        },
        allow_redirects=False,
        timeout=60,
    )
    oidc_authorize_url = str(authorize_resp.headers.get("location", "")).strip()
    if not oidc_authorize_url:
        raise RuntimeError("external auth authorize did not return OIDC authorize url")

    endpoint = f"{urlsplit(oidc_authorize_url).scheme}://{urlsplit(oidc_authorize_url).netloc}/api/internal/direct-authorize"
    body = json.dumps(
        {
            "authorize_url": oidc_authorize_url,
            "email": email,
            "full_name": "",
        }
    ).encode("utf-8")
    req = Request(
        endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {oidc_env['GPTOIDC_INTERNAL_BYPASS_KEY']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(req, timeout=30) as response:
        direct_result = json.loads(response.read().decode("utf-8"))

    consent_page = client.get(str(direct_result.get("redirect_url", "")).strip(), allow_redirects=True, timeout=60)
    interstitial_token = re.search(r'name="interstitial_token" value="([^"]+)"', consent_page.text)
    csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', consent_page.text)
    if not interstitial_token or not csrf_token:
        raise RuntimeError("workos interstitial form fields not found")
    confirm = client.post(
        urljoin(consent_page.url, "/sso/interstitial"),
        data={
            "interstitial_token": interstitial_token.group(1),
            "action": "confirm",
            "csrf_token": csrf_token.group(1),
        },
        allow_redirects=False,
        timeout=60,
    )
    callback_url = str(confirm.headers.get("location", "")).strip()
    if not callback_url:
        raise RuntimeError("workos interstitial confirm did not return auth.openai callback")
    return callback_url, direct_result, oidc_authorize_url


def main() -> int:
    env_path = Path(os.getenv("ENV_PATH", "/opt/sub2api-standalone-source/.env")).resolve()
    oidc_env_path = Path(os.getenv("OIDC_ENV_PATH", "/opt/sub2api-standalone-source/oidc/.env")).resolve()
    state_file = Path(os.getenv("STATE_FILE", "/tmp/run_openai_camoufox_callback_solver_state.json")).resolve()
    redirect_uri = os.getenv("REDIRECT_URI", "http://localhost:1455/auth/callback").strip()
    login_email = os.getenv("OPENAI_LOGIN_EMAIL", "user@example.com").strip().lower()
    account_name = os.getenv("OPENAI_ACCOUNT_NAME", login_email).strip() or login_email
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
        account_name=account_name,
        group_ids=[],
        group_name=defaults.get("group_name", "cc"),
        concurrency=defaults.get("concurrency", "10"),
    )
    pending_session = pending_result["pending_session"]
    remote_config = pending_result["remote_config"]

    state: dict[str, object] = {
        "stage": "init",
        "auth_url": pending_session.auth_url,
        "auth_callback_url": "",
        "oidc_authorize_url": "",
        "direct_authorize_result": None,
        "callback_url": "",
        "current_page_url": "",
        "current_body_text": "",
    }
    logs: list[dict[str, object]] = []
    write_state(state_file, {"state": state, "logs": logs})

    try:
        auth_callback_url, direct_result, oidc_authorize_url = build_auth_callback_url(login_email, oidc_env_path)
        state["auth_callback_url"] = auth_callback_url
        state["direct_authorize_result"] = direct_result
        state["oidc_authorize_url"] = oidc_authorize_url
        logs.append({"type": "workos_callback_url", "url": auth_callback_url})
        write_state(state_file, {"state": state, "logs": logs})

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
            page.add_init_script(
                """
                (() => {
                  const originalAttachShadow = Element.prototype.attachShadow;
                  Element.prototype.attachShadow = function(init) {
                    const shadow = originalAttachShadow.call(this, init);
                    if (init && init.mode === 'closed') {
                      window.__lastClosedShadowRoot = shadow;
                    }
                    return shadow;
                  };
                })();
                """
            )
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
            page.wait_for_timeout(12000)
            state["stage"] = "auth_session_seeded"
            state["current_page_url"] = page.url
            state["current_body_text"] = page.locator("body").inner_text(timeout=5000)[:2000]
            write_state(state_file, {"state": state, "logs": logs})

            page.goto(auth_callback_url, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(10000)
            state["stage"] = "workos_callback_loaded"
            state["current_page_url"] = page.url
            state["current_body_text"] = page.locator("body").inner_text(timeout=5000)[:2000]
            sitekey = extract_turnstile_sitekey(page)
            state["turnstile_sitekey"] = sitekey
            if sitekey:
                inject_result = inject_turnstile_widget(page, sitekey)
                logs.append({"type": "injected_turnstile", "sitekey": sitekey, "result": inject_result})
                page.wait_for_timeout(5000)
            write_state(state_file, {"state": state, "logs": logs})

            last_write = 0.0
            deadline = time.time() + 300
            while time.time() < deadline:
                if state["callback_url"]:
                    break
                state["current_page_url"] = page.url
                state["current_body_text"] = page.locator("body").inner_text(timeout=5000)[:3000]
                if "security verification" in state["current_body_text"].lower():
                    strategy = try_click_strategies(page)
                    if strategy:
                        logs.append({"type": "clicked_challenge", "strategy": strategy})
                else:
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
                            break
                now = time.time()
                if now - last_write >= 3:
                    write_state(state_file, {"state": state, "logs": logs})
                    last_write = now
                page.wait_for_timeout(3000)

            if not state["callback_url"] and is_localhost_callback_url(page.url, redirect_uri):
                state["callback_url"] = page.url
                state["stage"] = "localhost_callback_detected_from_page_url"
                logs.append({"type": "localhost_callback_from_page_url", "url": page.url})
                write_state(state_file, {"state": state, "logs": logs})

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
