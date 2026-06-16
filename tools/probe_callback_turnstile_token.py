"""探测 auth.openai callback/workos 页上的 Turnstile token 是否会产出。"""

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
from newtoken.sub2api.remote_oauth import create_openai_oauth_pending_session, load_openai_oauth_defaults


DEFAULT_CALLBACK_TURNSTILE_SITEKEY = "0x4AAAAAAADnPIDROrmt1Wwj"


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


def build_auth_callback_url(email: str, oidc_env_path: Path) -> tuple[str, str, dict[str, object]]:
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
    return callback_url, oidc_authorize_url, direct_result


def extract_turnstile_sitekey(html: str) -> str:
    match = re.search(r"0x4[A-Za-z0-9_-]{10,}", html)
    return match.group(0) if match else ""


def extract_turnstile_sitekey_from_frames(page) -> str:
    for frame in page.frames:
        url = str(frame.url or "")
        if "challenges.cloudflare.com" not in url:
            continue
        match = re.search(r"/((0x4[A-Za-z0-9_-]+))/", url)
        if match:
            return match.group(1)
    return ""


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
                  let widget = document.querySelector('.cf-turnstile[data-probe="1"]');
                  if (!widget) {
                    widget = document.createElement('div');
                    widget.className = 'cf-turnstile';
                    widget.setAttribute('data-probe', '1');
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
                  const render = () => {
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
                    return render();
                  }
                  const script = document.createElement('script');
                  script.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js';
                  script.async = true;
                  script.defer = true;
                  script.onload = render;
                  document.head.appendChild(script);
                  return 'turnstile_script_injected';
                }
                """,
                {"sitekey": sitekey},
            )
        ).strip()
    except Exception:
        return ""


def click_injected_widget(page) -> str:
    try:
        locator = page.locator('.cf-turnstile[data-probe="1"]').first
        if locator.count() > 0 and locator.is_visible():
            box = locator.bounding_box()
            if box:
                page.mouse.click(box["x"] + 40, box["y"] + 40)
                return "probe_widget_div"
    except Exception:
        pass
    try:
        iframe = page.locator("iframe[id^='cf-chl-widget-']").last
        if iframe.count() > 0 and iframe.is_visible():
            box = iframe.bounding_box()
            if box:
                page.mouse.click(box["x"] + 40, box["y"] + box["height"] / 2)
                return "probe_widget_iframe"
    except Exception:
        pass
    return ""


def write_state(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    env_path = Path(os.getenv("ENV_PATH", "/opt/sub2api-standalone-source/.env")).resolve()
    oidc_env_path = Path(os.getenv("OIDC_ENV_PATH", "/opt/sub2api-standalone-source/oidc/.env")).resolve()
    state_file = Path(os.getenv("STATE_FILE", "/tmp/probe_callback_turnstile_token_state.json")).resolve()
    redirect_uri = os.getenv("REDIRECT_URI", "http://localhost:1455/auth/callback").strip()
    login_email = os.getenv("OPENAI_LOGIN_EMAIL", "user@example.com").strip().lower()
    headless = os.getenv("PW_HEADLESS", "0").strip() in {"1", "true", "True"}

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
        group_ids=[],
        group_name=defaults.get("group_name", "cc"),
        concurrency=defaults.get("concurrency", "10"),
    )["pending_session"]

    state: dict[str, object] = {
        "stage": "init",
        "auth_url": pending_session.auth_url,
        "auth_callback_url": "",
        "oidc_authorize_url": "",
        "direct_authorize_result": None,
        "turnstile_sitekey": "",
        "inject_result": "",
        "token": "",
        "frame_urls": [],
        "current_page_url": "",
        "current_body_text": "",
        "snapshots": [],
    }
    write_state(state_file, {"state": state})

    try:
        auth_callback_url, oidc_authorize_url, direct_result = build_auth_callback_url(login_email, oidc_env_path)
        state["auth_callback_url"] = auth_callback_url
        state["oidc_authorize_url"] = oidc_authorize_url
        state["direct_authorize_result"] = direct_result
        state["stage"] = "callback_ready"
        write_state(state_file, {"state": state})

        with Camoufox(**build_camoufox_launch_options(headless=headless)) as browser:
            context = browser.new_context(**build_camoufox_context_options())
            if session_token:
                context.add_cookies(build_session_cookies(session_token))
            page = context.new_page()
            
            page.goto(pending_session.auth_url, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(12000)
            page.goto(auth_callback_url, wait_until="domcontentloaded", timeout=120000)
            page.wait_for_timeout(6000)

            state["frame_urls"] = [str(frame.url or "") for frame in page.frames]
            full_html = page.content()
            state["turnstile_sitekey"] = (
                extract_turnstile_sitekey(full_html)
                or extract_turnstile_sitekey_from_frames(page)
                or DEFAULT_CALLBACK_TURNSTILE_SITEKEY
            )
            state["page_html_prefix"] = full_html[:6000]
            state["inject_result"] = inject_turnstile_widget(page, str(state["turnstile_sitekey"]))
            state["stage"] = "turnstile_injected"
            write_state(state_file, {"state": state})

            for index in range(12):
                page.wait_for_timeout(5000)
                click_result = click_injected_widget(page)
                if click_result:
                    state["last_click_result"] = click_result
                state["frame_urls"] = [str(frame.url or "") for frame in page.frames]
                try:
                    state["widget_iframe_count"] = page.locator("iframe[id^='cf-chl-widget-']").count()
                except Exception:
                    state["widget_iframe_count"] = -1
                state["current_page_url"] = page.url
                state["current_body_text"] = page.locator("body").inner_text(timeout=5000)[:1200]
                token = ""
                try:
                    token_locator = page.locator('input[name="cf-turnstile-response"]').first
                    if token_locator.count() > 0:
                        token = token_locator.input_value(timeout=1000)
                except Exception:
                    token = ""
                snapshot = {
                    "step": index + 1,
                    "url": state["current_page_url"],
                    "body": state["current_body_text"],
                    "token_prefix": token[:24],
                }
                cast = state["snapshots"]
                if isinstance(cast, list):
                    cast.append(snapshot)
                if token:
                    state["token"] = token
                    state["stage"] = "token_captured"
                    write_state(state_file, {"state": state})
                    break
                write_state(state_file, {"state": state})

            browser.close()
    except Exception as exc:  # noqa: BLE001
        state["stage"] = "error"
        state["error"] = str(exc)
        write_state(state_file, {"state": state})
        print(json.dumps({"ok": False, "error": str(exc), "state": state}, ensure_ascii=False, indent=2))
        return 1

    print(json.dumps({"ok": True, "state": state}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
