"""Small WebUI formatting and JSON helpers."""

from __future__ import annotations

import html
from dataclasses import asdict
from typing import Any

from newtoken.sub2api.remote import mask_secret_value
from newtoken.common.http_client import mask_proxy_url

def redact_config(values: dict[str, str]) -> dict[str, str]:
    """Return config values safe enough for display."""

    result = dict(values)
    for key in (
        "SUB2API_ADMIN_API_KEY",
        "OPENAI_ACCESS_TOKEN",
        "OPENAI_SESSION_TOKEN",
        "OPENAI_DEVICE_ID",
        "SUB2API_WEB_SECRET",
    ):
        if result.get(key):
            result[f"{key}_MASKED"] = mask_secret_value(result[key])
    proxy_url = result.get("SUB2API_OUTBOUND_PROXY_URL", "")
    result["SUB2API_OUTBOUND_PROXY_URL_MASKED"] = mask_proxy_url(proxy_url)
    return result


def html_escape(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def json_safe(value: Any) -> Any:
    """Convert common dataclass-ish values into JSON serializable objects."""

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if hasattr(value, "__dataclass_fields__"):
        return json_safe(asdict(value))
    return str(value)


def parse_bool_text(value: Any, default: bool = False) -> bool:
    """Parse common text booleans used by .env and browser forms."""

    text = str(value or "").strip().lower()
    if not text:
        return bool(default)
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def parse_positive_int(value: Any, default: int, *, minimum: int = 1, maximum: int = 200) -> int:
    """Parse bounded positive int values from config or form text."""

    try:
        parsed = int(str(value or "").strip())
    except (TypeError, ValueError):
        return int(default)
    return max(int(minimum), min(int(maximum), parsed))
