"""Remote Sub2API account actions for the WebUI."""

from __future__ import annotations

from typing import Any

from sub2api_converter_remote import (
    delete_dead_remote_accounts,
    scan_remote_accounts,
    select_remote_accounts_with_auth_error,
    select_remote_accounts_without_quota,
)
from sub2api_webui_config import WebState


def build_remote_summary(state: WebState) -> dict[str, Any]:
    config = state.build_remote_config()
    result = scan_remote_accounts(config)
    state.last_remote_scan = result
    return result


def delete_selected_remote_items(state: WebState, selector: str) -> dict[str, Any]:
    if not state.last_remote_scan:
        raise RuntimeError("请先刷新远程账号状态")
    if selector == "no_quota":
        items = select_remote_accounts_without_quota(
            state.last_remote_scan.get("no_quota_items")
            or state.last_remote_scan.get("dead_items")
            or []
        )
    elif selector == "auth_error":
        items = select_remote_accounts_with_auth_error(
            state.last_remote_scan.get("dead_items") or []
        )
    else:
        items = state.last_remote_scan.get("dead_items") or []
    if not items:
        return {"deleted": 0, "failed": 0, "items": []}
    return delete_dead_remote_accounts(state.build_remote_config(), items)
