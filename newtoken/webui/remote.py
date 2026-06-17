"""Remote Sub2API account actions for the WebUI."""

from __future__ import annotations

from typing import Any

import newtoken.acc.seat_client as seat_core
from newtoken.sub2api.remote import (
    delete_dead_remote_accounts,
    scan_remote_accounts,
    select_remote_accounts_with_auth_error,
    select_remote_accounts_without_quota,
)
from newtoken.sub2api.usage_bridge import Sub2APIUsageSnapshot, normalize_email
from newtoken.webui.acc import delete_invalidated_accounts
from newtoken.webui.config import WebState
from newtoken.webui.policy_runner import record_policy_events


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
    if selector == "auth_error":
        client = state.build_seat_client()
        users_by_email = {
            normalize_email(user.get("email")): user
            for user in seat_core.list_all_users(client)
            if normalize_email(user.get("email"))
        }
        snapshots_by_account_id = {
            int(item.get("account_id") or 0): Sub2APIUsageSnapshot(
                account_id=int(item.get("account_id") or 0),
                name=str(item.get("name") or ""),
                email=str(item.get("email") or ""),
                quota_5h_text="--",
                quota_7d_text="--",
                usage_updated_at="",
            )
            for item in items
            if int(item.get("account_id") or 0) > 0
        }
        result = delete_invalidated_accounts(
            client,
            users_by_email,
            snapshots_by_account_id,
            sorted(snapshots_by_account_id),
            remote_config=state.build_remote_config(),
            block_promotion=state.block_promotion_permanently,
        )
        record_policy_events(
            state.policy_events,
            {"invalidated_result": result},
        )
        return result
    return delete_dead_remote_accounts(state.build_remote_config(), items)
