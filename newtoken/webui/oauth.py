"""OpenAI OAuth account creation actions for the WebUI."""

from __future__ import annotations

from typing import Any

from newtoken.sub2api.remote_oauth import (
    complete_openai_oauth_account_creation,
    create_openai_oauth_pending_session,
    load_openai_oauth_defaults,
    normalize_oauth_concurrency,
)
from newtoken.webui.config import WebState


def create_oauth_session(state: WebState, form: dict[str, str]) -> dict[str, Any]:
    defaults = load_openai_oauth_defaults(str(state.env_path))
    group_ids_text = form.get("group_ids") or defaults.get("group_ids", "")
    group_ids = []
    for part in group_ids_text.split(","):
        text = part.strip()
        if text:
            group_ids.append(int(text))
    result = create_openai_oauth_pending_session(
        base_url=form.get("base_url") or defaults.get("base_url", ""),
        admin_api_key=form.get("admin_api_key") or defaults.get("admin_api_key", ""),
        proxy_id=form.get("proxy_id") or defaults.get("proxy_id", ""),
        proxy_url=form.get("proxy_url") or defaults.get("proxy_url", ""),
        proxy_name=form.get("proxy_name") or defaults.get("proxy_name", "default"),
        redirect_uri=form.get("redirect_uri") or defaults.get("redirect_uri", ""),
        account_name=form.get("account_name") or "",
        group_ids=group_ids,
        group_name=form.get("group_name") or defaults.get("group_name", "cc"),
        concurrency=normalize_oauth_concurrency(
            form.get("concurrency") or defaults.get("concurrency", "")
        ),
    )
    pending = result["pending_session"]
    state.last_oauth_session = {
        "remote_config": result["remote_config"],
        "pending_session": pending,
    }
    return {
        "auth_url": pending.auth_url,
        "session_id": pending.session_id,
        "state": pending.state,
        "account_name": pending.account_name,
        "proxy_name": pending.proxy_name,
        "proxy_id": pending.proxy_id,
        "group_ids": pending.group_ids,
    }


def complete_oauth_session(state: WebState, auth_input: str) -> dict[str, Any]:
    if not state.last_oauth_session:
        raise RuntimeError("请先生成 OAuth 授权链接")
    return complete_openai_oauth_account_creation(
        remote_config=state.last_oauth_session["remote_config"],
        pending_session=state.last_oauth_session["pending_session"],
        auth_input=auth_input,
    )
