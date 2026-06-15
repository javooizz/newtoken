"""OIDC API client -- WebUI programmatic access to the GPT OIDC card system.

The OIDC system runs on its own domain.  WebUI calls its REST API with a
shared Bearer token to generate/lookup cards for the auto-maintenance pipeline.
"""

from __future__ import annotations

from typing import Any

from newtoken.common.http_client import request_json

_oidc_cache: dict[str, str] | None = None


def _oidc_config(config: dict[str, str] | None = None) -> tuple[str, str]:
    global _oidc_cache
    if _oidc_cache is not None:
        return _oidc_cache["api_url"], _oidc_cache["api_key"]
    if config is not None:
        api_url = str(config.get("SUB2API_OIDC_API_URL") or "").strip().rstrip("/")
        api_key = str(config.get("SUB2API_OIDC_API_KEY") or "").strip()
        _oidc_cache = {"api_url": api_url, "api_key": api_key}
        return api_url, api_key
    from newtoken.webui.config import ENV_PATH, read_env_file
    values = read_env_file(ENV_PATH)
    api_url = str(values.get("SUB2API_OIDC_API_URL") or "").strip().rstrip("/")
    api_key = str(values.get("SUB2API_OIDC_API_KEY") or "").strip()
    _oidc_cache = {"api_url": api_url, "api_key": api_key}
    return api_url, api_key


def invalidate_oidc_cache() -> None:
    global _oidc_cache
    _oidc_cache = None


def _oidc_request(method: str, path: str, *,
                  body: dict[str, Any] | None = None,
                  config: dict[str, str] | None = None) -> dict[str, Any]:
    api_url, api_key = _oidc_config(config)
    if not api_url or not api_key:
        return {"ok": False, "error": "OIDC not configured (missing SUB2API_OIDC_API_URL or SUB2API_OIDC_API_KEY)"}
    url = f"{api_url}{path}"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        status, text, data = request_json(url, method=method, headers=headers, json_body=body, timeout=15)
        if isinstance(data, dict):
            return data
        return {"ok": False, "error": f"unexpected response type: {type(data).__name__}", "status": status, "text": text}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def oidc_status(config: dict[str, str] | None = None) -> dict[str, Any]:
    return _oidc_request("GET", "/api/status", config=config)


def oidc_generate_cards(count: int = 5, expires_days: int = 30, note: str = "",
                        config: dict[str, str] | None = None) -> dict[str, Any]:
    return _oidc_request("POST", "/api/cards/generate", body={
        "count": count, "expires_days": expires_days, "note": note,
    }, config=config)


def oidc_lookup_card(card: str, config: dict[str, str] | None = None) -> dict[str, Any]:
    return _oidc_request("POST", "/api/cards/lookup", body={"card": card}, config=config)
