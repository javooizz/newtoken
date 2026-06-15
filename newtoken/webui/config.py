"""Configuration and shared runtime state for the WebUI."""

from __future__ import annotations

import json
import secrets
from pathlib import Path

import newtoken.acc.seat_client as seat_core
from newtoken.sub2api.remote import build_remote_config, load_remote_import_defaults
from newtoken.common.http_client import apply_proxy_env
from newtoken.common.runtime import get_app_dir
from newtoken.webui.tasks import WebTaskStore

APP_DIR = get_app_dir(__file__)
ENV_PATH = APP_DIR / ".env"
WEB_DEFAULT_PORT = 28463
WEB_DEFAULT_HOST = "0.0.0.0"
MAX_REQUEST_BODY_BYTES = 4 * 1024 * 1024
SESSION_COOKIE_NAME = "sub2api_web_session"
SEAT_ACTIONS = {
    "ChatGPT": "default",
    "Codex": "usage_based",
}
LOW_QUOTA_THRESHOLD_PERCENT = 10.0
WEB_ENV_FIELD_ORDER = [
    "SUB2API_BASE_URL",
    "SUB2API_ADMIN_API_KEY",
    "SUB2API_GROUP_IDS",
    "SUB2API_PROXY_ID",
    "SUB2API_OUTBOUND_PROXY_URL",
    "SUB2API_IMPORT_CONCURRENCY",
    "SUB2API_VALIDATE_CONCURRENCY",
    "SUB2API_IMPORT_PRIORITY",
    "SUB2API_UPDATE_EXISTING",
    "SUB2API_SKIP_DEFAULT_GROUP_BIND",
    "SUB2API_CONFIRM_MIXED_CHANNEL_RISK",
    "SUB2API_OAUTH_REDIRECT_URI",
    "SUB2API_OAUTH_PROXY_ID",
    "SUB2API_OAUTH_PROXY_URL",
    "SUB2API_OAUTH_PROXY_NAME",
    "SUB2API_OAUTH_GROUP_IDS",
    "SUB2API_OAUTH_GROUP_NAME",
    "SUB2API_OAUTH_ACCOUNT_CONCURRENCY",
    "SUB2API_WEB_PORT",
    "SUB2API_WEB_HOST",
    "SUB2API_WEB_SECRET",
    "ACC_MOTHER_ACCOUNT_EMAIL",
    "CHATGPT_RANDOM_EMAIL_DOMAIN",
    "OPENAI_ACCESS_TOKEN",
    "OPENAI_ACCOUNT_ID",
    "OPENAI_DEVICE_ID",
    "OPENAI_SESSION_TOKEN",
    "OPENAI_CLIENT_BUILD_NUMBER",
    "OPENAI_CLIENT_VERSION",
    "OPENAI_BASE_URL",
]
WEB_DEFAULT_ENV_VALUES: dict[str, str] = {
    "SUB2API_BASE_URL": "",
    "SUB2API_ADMIN_API_KEY": "",
    "SUB2API_GROUP_IDS": "",
    "SUB2API_PROXY_ID": "",
    "SUB2API_OUTBOUND_PROXY_URL": "",
    "SUB2API_IMPORT_CONCURRENCY": "50",
    "SUB2API_VALIDATE_CONCURRENCY": "24",
    "SUB2API_IMPORT_PRIORITY": "",
    "SUB2API_UPDATE_EXISTING": "true",
    "SUB2API_SKIP_DEFAULT_GROUP_BIND": "false",
    "SUB2API_CONFIRM_MIXED_CHANNEL_RISK": "false",
    "SUB2API_OAUTH_REDIRECT_URI": "http://localhost:1455/auth/callback",
    "SUB2API_OAUTH_PROXY_ID": "",
    "SUB2API_OAUTH_PROXY_URL": "",
    "SUB2API_OAUTH_PROXY_NAME": "default",
    "SUB2API_OAUTH_GROUP_IDS": "",
    "SUB2API_OAUTH_GROUP_NAME": "cc",
    "SUB2API_OAUTH_ACCOUNT_CONCURRENCY": "10",
    "SUB2API_WEB_PORT": str(WEB_DEFAULT_PORT),
    "SUB2API_WEB_HOST": WEB_DEFAULT_HOST,
    "SUB2API_WEB_SECRET": "",
    "ACC_MOTHER_ACCOUNT_EMAIL": "",
    "CHATGPT_RANDOM_EMAIL_DOMAIN": "example.com",
    "OPENAI_ACCESS_TOKEN": "",
    "OPENAI_ACCOUNT_ID": "",
    "OPENAI_DEVICE_ID": "",
    "OPENAI_SESSION_TOKEN": "",
    "OPENAI_CLIENT_BUILD_NUMBER": seat_core.CLIENT_BUILD_NUMBER,
    "OPENAI_CLIENT_VERSION": seat_core.CLIENT_VERSION,
    "OPENAI_BASE_URL": seat_core.DEFAULT_BASE_URL,
}


def parse_env_value(raw_value: str) -> str:
    """Parse a simple .env value."""

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
    """Read a simple KEY=VALUE .env file without GUI dependencies."""

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
    """Write .env while preserving unknown keys."""

    merged = dict(WEB_DEFAULT_ENV_VALUES)
    merged.update(read_env_file(path))
    merged.update({key: str(value or "") for key, value in values.items()})
    lines = ["# Sub2API WebUI local configuration"]
    written: set[str] = set()
    for key in WEB_ENV_FIELD_ORDER:
        lines.append(f"{key}={json.dumps(merged.get(key, ''), ensure_ascii=False)}")
        written.add(key)
    for key in sorted(merged):
        if key not in written:
            lines.append(f"{key}={json.dumps(merged.get(key, ''), ensure_ascii=False)}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


class WebState:
    """Shared runtime state for the WebUI server."""

    def __init__(self, env_path: Path) -> None:
        self.env_path = env_path
        self.tasks = WebTaskStore()
        self.csrf_token = secrets.token_urlsafe(24)
        self.sessions: set[str] = set()
        self.auth_secret = ""
        self.acc_credentials: dict[str, str] = {
            "access_token": "",
            "account_id": "",
            "device_id": "",
            "session_token": "",
            "client_build_number": seat_core.CLIENT_BUILD_NUMBER,
            "client_version": seat_core.CLIENT_VERSION,
            "base_url": seat_core.DEFAULT_BASE_URL,
        }
        self.last_remote_scan: dict[str, Any] | None = None
        self.last_conversion_payload = ""
        self.last_conversion_summary: dict[str, Any] | None = None
        self.last_oauth_session: dict[str, Any] | None = None
        self.last_acc_members: list[dict[str, Any]] = []
        self.last_usage_lookup: dict[str, Any] = {}
        self.load_config()

    def load_config(self) -> dict[str, str]:
        if not self.env_path.exists():
            write_env_file(self.env_path, WEB_DEFAULT_ENV_VALUES)
        values = dict(WEB_DEFAULT_ENV_VALUES)
        values.update(read_env_file(self.env_path))
        self.auth_secret = str(values.get("SUB2API_WEB_SECRET") or "").strip()
        apply_proxy_env(values.get("SUB2API_OUTBOUND_PROXY_URL", ""))
        self._load_acc_credentials(values)
        return values

    def save_config(self, updates: dict[str, str]) -> dict[str, str]:
        values = self.load_config()
        values.update({key: str(value or "") for key, value in updates.items()})
        write_env_file(self.env_path, values)
        return self.load_config()

    def _load_acc_credentials(self, values: dict[str, str]) -> None:
        self.acc_credentials = {
            "access_token": str(values.get("OPENAI_ACCESS_TOKEN") or "").strip(),
            "account_id": str(values.get("OPENAI_ACCOUNT_ID") or "").strip(),
            "device_id": str(values.get("OPENAI_DEVICE_ID") or "").strip(),
            "session_token": str(values.get("OPENAI_SESSION_TOKEN") or "").strip(),
            "client_build_number": (
                str(values.get("OPENAI_CLIENT_BUILD_NUMBER") or "").strip()
                or seat_core.CLIENT_BUILD_NUMBER
            ),
            "client_version": (
                str(values.get("OPENAI_CLIENT_VERSION") or "").strip()
                or seat_core.CLIENT_VERSION
            ),
            "base_url": (
                str(values.get("OPENAI_BASE_URL") or "").strip()
                or seat_core.DEFAULT_BASE_URL
            ),
        }

    def build_remote_config(self):
        defaults = load_remote_import_defaults(str(self.env_path))
        return build_remote_config(
            defaults.get("base_url", ""),
            defaults.get("admin_api_key", ""),
            group_ids_text=defaults.get("group_ids", ""),
            proxy_id_text=defaults.get("proxy_id", ""),
            concurrency_text=defaults.get("concurrency", ""),
            priority_text=defaults.get("priority", ""),
            update_existing=defaults.get("update_existing", True),
            skip_default_group_bind=defaults.get("skip_default_group_bind", False),
            confirm_mixed_channel_risk=defaults.get(
                "confirm_mixed_channel_risk",
                False,
            ),
        )

    def build_seat_client(self) -> seat_core.SeatClient:
        creds = self.acc_credentials
        config = seat_core.Config(
            access_token=creds["access_token"],
            account_id=creds["account_id"],
            device_id=creds["device_id"],
            session_token=creds["session_token"],
            client_build_number=creds["client_build_number"] or seat_core.CLIENT_BUILD_NUMBER,
            client_version=creds["client_version"] or seat_core.CLIENT_VERSION,
            base_url=seat_core.normalize_base_url(
                creds["base_url"] or seat_core.DEFAULT_BASE_URL
            ),
        )
        if not config.access_token and not config.session_token:
            raise SeatApiWebError("缺少 ACC access token 或 session token")
        if not config.account_id:
            raise SeatApiWebError("缺少 ACC account_id")
        return seat_core.SeatClient(config)


class SeatApiWebError(RuntimeError):
    """WebUI-facing ACC error."""
