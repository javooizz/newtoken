"""Account health monitoring and automatic offline actions."""

from __future__ import annotations

from typing import Any

from newtoken.webui.config import WebState


def evaluate_health(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Classify each remote account into alive/dead/low-quota/auth-error buckets.

    Returns health report with categorized lists and actionable counts.
    """
    items = list(snapshot.get("items") or [])
    alive: list[dict[str, Any]] = []
    dead: list[dict[str, Any]] = []
    low_quota: list[dict[str, Any]] = []
    auth_error: list[dict[str, Any]] = []
    no_quota: list[dict[str, Any]] = []

    for item in items:
        status = str(item.get("status") or "").lower()
        reason = str(item.get("reason") or "").lower()
        quota = float(item.get("remaining_quota_percent") or 0)
        if status == "dead" or "dead" in reason:
            dead.append(item)
        elif status == "auth_error" or "401" in reason or status == "unauthorized":
            auth_error.append(item)
        elif quota <= 0:
            no_quota.append(item)
        elif quota < 10:
            low_quota.append(item)
        else:
            alive.append(item)

    return {
        "total": len(items),
        "alive": len(alive),
        "dead": len(dead),
        "auth_error": len(auth_error),
        "no_quota": len(no_quota),
        "low_quota": len(low_quota),
        "alive_items": alive,
        "dead_items": dead,
        "auth_error_items": auth_error,
        "no_quota_items": no_quota,
        "low_quota_items": low_quota,
        "needs_replenish": len(alive) < 5,
    }


def auto_offline_dead(
    state: WebState,
    target: list[dict[str, Any]],
) -> dict[str, Any]:
    """Offline dead/auth-error/no-quota accounts via Sub2API remote delete."""
    if not target:
        return {"offlined": 0, "failed": 0, "errors": []}

    try:
        from newtoken.webui.remote import delete_selected_remote_items

        result = delete_selected_remote_items(state, "dead")
        return {
            "offlined": result.get("deleted", 0),
            "failed": result.get("failed", 0),
            "errors": [],
        }
    except Exception as exc:  # noqa: BLE001
        return {"offlined": 0, "failed": len(target), "errors": [str(exc)]}
