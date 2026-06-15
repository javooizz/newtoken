"""One-step OpenAI OAuth account creation actions for the WebUI."""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlsplit

from newtoken.sub2api.remote_oauth import (
    DEFAULT_OAUTH_REDIRECT_URI,
    complete_openai_oauth_account_creation,
    create_openai_oauth_pending_session,
    load_openai_oauth_defaults,
    normalize_oauth_concurrency,
)
from newtoken.webui.config import WebState

OAUTH_CALLBACK_PATH = "/oauth/callback"


def build_public_oauth_redirect_uri(state: WebState, form: dict[str, str]) -> str:
    """Resolve the browser-reachable WebUI OAuth callback URL."""

    explicit = (form.get("redirect_uri") or "").strip()
    if explicit and explicit != DEFAULT_OAUTH_REDIRECT_URI:
        parsed = urlsplit(explicit)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return explicit
    public_base = (
        form.get("public_base_url")
        or state.load_config().get("SUB2API_WEB_PUBLIC_BASE_URL", "")
        or ""
    ).strip()
    if public_base:
        base = public_base.rstrip("/")
    else:
        values = state.load_config()
        host = values.get("SUB2API_WEB_HOST", "127.0.0.1").strip() or "127.0.0.1"
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1"
        port = values.get("SUB2API_WEB_PORT", "28463").strip() or "28463"
        base = f"http://{host}:{port}"
    return f"{base}{OAUTH_CALLBACK_PATH}"


def start_oauth_flow(state: WebState, form: dict[str, str]) -> dict[str, Any]:
    """Create one pending OAuth flow and return the login URL."""

    defaults = load_openai_oauth_defaults(str(state.env_path))
    group_ids = _parse_group_ids(form.get("group_ids") or defaults.get("group_ids", ""))
    redirect_uri = build_public_oauth_redirect_uri(state, form)
    result = create_openai_oauth_pending_session(
        base_url=form.get("base_url") or defaults.get("base_url", ""),
        admin_api_key=form.get("admin_api_key") or defaults.get("admin_api_key", ""),
        proxy_id=form.get("proxy_id") or defaults.get("proxy_id", ""),
        proxy_url=form.get("proxy_url") or defaults.get("proxy_url", ""),
        proxy_name=form.get("proxy_name") or defaults.get("proxy_name", "default"),
        redirect_uri=redirect_uri,
        account_name=form.get("account_name") or "",
        group_ids=group_ids,
        group_name=form.get("group_name") or defaults.get("group_name", "cc"),
        concurrency=normalize_oauth_concurrency(
            form.get("concurrency") or defaults.get("concurrency", "")
        ),
    )
    pending = result["pending_session"]
    session = {
        "remote_config": result["remote_config"],
        "pending_session": pending,
        "status": "waiting_callback",
        "error": "",
        "result": None,
        "callback_url": "",
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    with state.oauth_lock:
        state.last_oauth_session = session
    return build_oauth_status(state, include_auth_url=True)


def _parse_group_ids(group_ids_text: str) -> list[int]:
    group_ids: list[int] = []
    for part in group_ids_text.split(","):
        text = part.strip()
        if not text:
            continue
        try:
            gid = int(text)
        except ValueError:
            continue
        if gid > 0:
            group_ids.append(gid)
    return group_ids


def complete_oauth_from_callback(state: WebState, callback_url: str) -> dict[str, Any]:
    """Complete the pending OAuth flow from the browser callback URL."""

    return _complete_pending_oauth(state, callback_url, source="callback")


def complete_oauth_manually(state: WebState, auth_input: str) -> dict[str, Any]:
    """Manual fallback when the public callback cannot reach the WebUI."""

    return _complete_pending_oauth(state, auth_input, source="manual")


def _complete_pending_oauth(state: WebState, auth_input: str, *, source: str) -> dict[str, Any]:
    auth_input = str(auth_input or "").strip()
    if not auth_input:
        raise RuntimeError("请粘贴回调链接或 Code")
    with state.oauth_lock:
        session = state.last_oauth_session
        if not session:
            raise RuntimeError("当前没有等待中的 OAuth 授权流程")
        current_status = str(session.get("status") or "")
        if current_status == "creating_account":
            return _build_oauth_status_from_session(session, include_auth_url=False)
        if current_status == "done":
            return _build_oauth_status_from_session(session, include_auth_url=False)
        session["status"] = "creating_account"
        session["callback_url"] = auth_input
        session["updated_at"] = time.time()

    try:
        result = complete_openai_oauth_account_creation(
            remote_config=session["remote_config"],
            pending_session=session["pending_session"],
            auth_input=auth_input,
        )
    except Exception as exc:  # noqa: BLE001
        with state.oauth_lock:
            session["status"] = "error"
            session["error"] = str(exc)
            session["updated_at"] = time.time()
        raise

    with state.oauth_lock:
        session["status"] = "done"
        session["result"] = result
        session["source"] = source
        session["updated_at"] = time.time()
    return _build_oauth_status_from_session(session, include_auth_url=False)


def build_oauth_status(state: WebState, *, include_auth_url: bool = False) -> dict[str, Any]:
    with state.oauth_lock:
        session = dict(state.last_oauth_session or {})
    return _build_oauth_status_from_session(session, include_auth_url=include_auth_url)


def _build_oauth_status_from_session(
    session: dict[str, Any],
    *,
    include_auth_url: bool = False,
) -> dict[str, Any]:
    if not session:
        return {"status": "idle"}
    pending = session.get("pending_session")
    result = session.get("result") if isinstance(session.get("result"), dict) else None
    payload = {
        "status": session.get("status") or "idle",
        "error": session.get("error") or "",
        "callback_url": session.get("callback_url") or "",
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
    }
    if pending is not None:
        payload.update(
            {
                "session_id": pending.session_id,
                "state": pending.state,
                "account_name": pending.account_name,
                "proxy_name": pending.proxy_name,
                "proxy_id": pending.proxy_id,
                "group_ids": pending.group_ids,
                "redirect_uri": pending.redirect_uri,
            }
        )
        if include_auth_url:
            payload["auth_url"] = pending.auth_url
    if result:
        payload["account_id"] = result.get("account_id")
        payload["account_name"] = result.get("account_name")
        payload["account_email"] = result.get("account_email")
        payload["post_update_error"] = result.get("post_update_error") or ""
    return payload
