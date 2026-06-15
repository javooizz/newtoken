"""ACC 页面本地缓存工具。"""

from __future__ import annotations

import json
from pathlib import Path

from newtoken.sub2api.usage_bridge import Sub2APIUsageSnapshot


def read_acc_input_cache(path: Path) -> str:
    """读取 ACC 原文输入缓存。"""

    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def write_acc_input_cache(path: Path, raw_text: str) -> None:
    """写入 ACC 原文输入缓存，空内容时删除缓存。"""

    text = str(raw_text or "")
    if not text.strip():
        if path.exists():
            path.unlink()
        return
    path.write_text(text, encoding="utf-8")


def build_snapshot_payload(snapshot: Sub2APIUsageSnapshot) -> dict[str, object]:
    """把额度快照转成可落盘的 JSON 结构。"""

    return {
        "account_id": int(getattr(snapshot, "account_id", 0) or 0),
        "name": str(getattr(snapshot, "name", "") or "").strip(),
        "email": str(getattr(snapshot, "email", "") or "").strip().lower(),
        "quota_5h_text": str(getattr(snapshot, "quota_5h_text", "--") or "--").strip(),
        "quota_7d_text": str(getattr(snapshot, "quota_7d_text", "--") or "--").strip(),
        "usage_updated_at": str(getattr(snapshot, "usage_updated_at", "") or "").strip(),
        "quota_5h_remaining_percent": getattr(snapshot, "quota_5h_remaining_percent", None),
        "quota_7d_remaining_percent": getattr(snapshot, "quota_7d_remaining_percent", None),
        "account_status": str(getattr(snapshot, "account_status", "") or "").strip(),
        "quota_5h_reset_at": str(getattr(snapshot, "quota_5h_reset_at", "") or "").strip(),
        "quota_7d_reset_at": str(getattr(snapshot, "quota_7d_reset_at", "") or "").strip(),
        "quota_5h_reset_after_seconds": getattr(
            snapshot,
            "quota_5h_reset_after_seconds",
            None,
        ),
        "quota_7d_reset_after_seconds": getattr(
            snapshot,
            "quota_7d_reset_after_seconds",
            None,
        ),
    }


def parse_snapshot_payload(payload: object) -> Sub2APIUsageSnapshot | None:
    """把 JSON 结构恢复成额度快照。"""

    if not isinstance(payload, dict):
        return None
    try:
        account_id = int(payload.get("account_id", 0) or 0)
    except (TypeError, ValueError):
        account_id = 0
    email = str(payload.get("email") or "").strip().lower()
    if not email:
        return None
    return Sub2APIUsageSnapshot(
        account_id=account_id,
        name=str(payload.get("name") or "").strip(),
        email=email,
        quota_5h_text=str(payload.get("quota_5h_text") or "--").strip() or "--",
        quota_7d_text=str(payload.get("quota_7d_text") or "--").strip() or "--",
        usage_updated_at=str(payload.get("usage_updated_at") or "").strip(),
        quota_5h_remaining_percent=_parse_optional_float(
            payload.get("quota_5h_remaining_percent")
        ),
        quota_7d_remaining_percent=_parse_optional_float(
            payload.get("quota_7d_remaining_percent")
        ),
        account_status=str(payload.get("account_status") or "").strip().lower(),
        quota_5h_reset_at=str(payload.get("quota_5h_reset_at") or "").strip(),
        quota_7d_reset_at=str(payload.get("quota_7d_reset_at") or "").strip(),
        quota_5h_reset_after_seconds=_parse_optional_int(
            payload.get("quota_5h_reset_after_seconds")
        ),
        quota_7d_reset_after_seconds=_parse_optional_int(
            payload.get("quota_7d_reset_after_seconds")
        ),
    )


def _parse_optional_int(value: object) -> int | None:
    """把缓存中的可选整数安全恢复为 int。"""

    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_optional_float(value: object) -> float | None:
    """把缓存中的可选浮点数安全恢复为 float。"""

    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def read_usage_cache(path: Path) -> dict[str, Sub2APIUsageSnapshot]:
    """读取本地额度缓存。"""

    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    raw_lookup = payload.get("lookup")
    if not isinstance(raw_lookup, dict):
        return {}
    lookup: dict[str, Sub2APIUsageSnapshot] = {}
    for email, snapshot_payload in raw_lookup.items():
        snapshot = parse_snapshot_payload(snapshot_payload)
        if snapshot is None:
            continue
        lookup[str(email).strip().lower()] = snapshot
    return lookup


def write_usage_cache(path: Path, lookup: dict[str, Sub2APIUsageSnapshot]) -> None:
    """写入本地额度缓存。"""

    normalized_lookup = {
        str(email).strip().lower(): build_snapshot_payload(snapshot)
        for email, snapshot in (lookup or {}).items()
        if getattr(snapshot, "email", None)
    }
    payload = {"lookup": normalized_lookup}
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_member_list_cache(path: Path) -> list[dict]:
    """读取本地成员列表缓存。"""

    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    items = payload.get("items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def write_member_list_cache(path: Path, users: list[dict]) -> None:
    """写入本地成员列表缓存。"""

    payload = {
        "items": [user for user in (users or []) if isinstance(user, dict)],
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def read_ui_settings_cache(path: Path) -> dict[str, object]:
    """读取 ACC 单页本地 UI 设置缓存。"""

    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    return payload


def write_ui_settings_cache(path: Path, settings: dict[str, object]) -> None:
    """写入 ACC 单页本地 UI 设置缓存。"""

    payload = {
        key: value
        for key, value in (settings or {}).items()
        if key in {"auto_refresh_seconds"}
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
