"""Observable wrapper around the ACC quota policy."""

from __future__ import annotations

import time
from typing import Any

from newtoken.webui.acc import enforce_acc_low_quota_policy
from newtoken.webui.event_log import PolicyEventStore
from newtoken.webui.notifications import is_acc_credential_error


def record_policy_events(
    store: PolicyEventStore,
    result: dict[str, Any],
    *,
    created_at: float | None = None,
) -> None:
    """Convert one policy result into durable user-facing events."""

    timestamp = float(created_at if created_at is not None else time.time())
    for item in result.get("changed_members") or []:
        store.append(
            action="demote_codex",
            email=item.get("email", ""),
            account_id=item.get("account_id"),
            reason="额度低于阈值",
            result="success",
            details={
                "quota_5h": item.get("quota_5h", ""),
                "quota_7d": item.get("quota_7d", ""),
                "cooldown_until": item.get("cooldown_until"),
            },
            created_at=timestamp,
        )
    for item in result.get("limit_changed_members") or []:
        store.append(
            action="demote_codex",
            email=item.get("email", ""),
            reason="ChatGPT 席位超过上限",
            result="success",
            details={"user_id": item.get("user_id", "")},
            created_at=timestamp,
        )
    for item in result.get("protected_mother_members") or []:
        store.append(
            action="demote_codex",
            email=item.get("email", ""),
            reason=item.get("reason", "母号不能占用 ChatGPT 席位"),
            result="success",
            details={"user_id": item.get("user_id", "")},
            created_at=timestamp,
        )
    for item in result.get("promoted_members") or []:
        store.append(
            action="promote_chatgpt",
            email=item.get("email", ""),
            account_id=item.get("account_id"),
            reason="自动补足 ChatGPT 席位",
            result="success",
            details={
                "quota_5h": item.get("quota_5h", ""),
                "quota_7d": item.get("quota_7d", ""),
            },
            created_at=timestamp,
        )
    invalidated_result = result.get("invalidated_result") or {}
    for item in invalidated_result.get("invalidated_accounts") or []:
        store.append(
            action="delete_invalidated",
            email=item.get("email", ""),
            account_id=item.get("account_id"),
            reason="401/token_invalidated",
            result=(
                "success"
                if item.get("remote_deleted")
                else "partial_failure"
            ),
            details={
                "acc_deleted": bool(item.get("acc_deleted")),
                "remote_deleted": bool(item.get("remote_deleted")),
                "permanently_blocked": bool(item.get("permanently_blocked")),
                "acc_error": item.get("acc_error", ""),
                "remote_error": item.get("remote_error", ""),
            },
            created_at=timestamp,
        )


def run_observed_policy(state) -> dict[str, Any]:
    """Run policy with event logging and deduplicated ACC credential alerts."""

    try:
        result = enforce_acc_low_quota_policy(state)
    except Exception as exc:
        error_text = str(exc).strip()
        state.policy_events.append(
            action="policy_error",
            reason=error_text,
            result="failed",
        )
        if is_acc_credential_error(exc):
            push_result = state.acc_alerts.notify_failure(
                state.pushplus_token,
                error_text,
            )
            if push_result.get("error"):
                state.policy_events.append(
                    action="pushplus_error",
                    reason=push_result["error"],
                    result="failed",
                )
        raise
    record_policy_events(state.policy_events, result)
    if state.acc_alerts.mark_recovered():
        state.policy_events.append(
            action="acc_credentials_recovered",
            reason="ACC 自动策略恢复成功",
            result="success",
        )
    return result
