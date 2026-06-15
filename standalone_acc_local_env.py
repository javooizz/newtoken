"""本地 .env 配置读写工具。"""

from __future__ import annotations

import json
from pathlib import Path

ENV_KEY_ORDER = [
    "OPENAI_ACCESS_TOKEN",
    "OPENAI_ACCOUNT_ID",
    "OPENAI_DEVICE_ID",
    "OPENAI_SESSION_TOKEN",
    "OPENAI_CLIENT_BUILD_NUMBER",
    "OPENAI_CLIENT_VERSION",
    "OPENAI_BASE_URL",
    "MAILCOW_BASE_URL",
    "MAILCOW_API_KEY",
    "MAILCOW_DOMAIN",
    "MAILCOW_DEFAULT_PASSWORD",
    "MAILCOW_MAILBOX_PREFIX",
    "MAILCOW_DISPLAY_NAME_PREFIX",
    "MAILCOW_MAILBOX_QUOTA_MB",
    "MAILCOW_IMAP_HOST",
    "MAILCOW_IMAP_PORT",
    "MAILCOW_IMAP_SSL",
    "MAILCOW_IMAP_FOLDER",
]


def parse_env_value(raw_value: str) -> str:
    """把 .env 中的原始值转成字符串。"""
    value = raw_value.strip()
    if not value:
        return ""
    if value.startswith('"') and value.endswith('"'):
        try:
            return str(json.loads(value))
        except json.JSONDecodeError:
            return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    return value


def read_env_file(path: Path) -> dict[str, str]:
    """读取简单的 .env 文件。"""
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = parse_env_value(value)
    return values


def write_env_file(path: Path, values: dict[str, str]) -> None:
    """把配置写入 .env 文件，同时保留已有未知键。"""
    existing = read_env_file(path)
    merged = dict(existing)
    for key, value in values.items():
        merged[key] = str(value)

    lines = ["# 本地席位工具配置，仅供当前机器使用"]
    written_keys: set[str] = set()

    for key in ENV_KEY_ORDER:
        if key not in merged:
            continue
        lines.append(f"{key}={json.dumps(merged[key], ensure_ascii=False)}")
        written_keys.add(key)

    for key in sorted(merged):
        if key in written_keys:
            continue
        lines.append(f"{key}={json.dumps(merged[key], ensure_ascii=False)}")

    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
