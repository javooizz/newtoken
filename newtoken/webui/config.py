"""Configuration and shared runtime state for the WebUI."""

from __future__ import annotations

import json
import secrets
import threading
from pathlib import Path
from typing import Any

import newtoken.acc.seat_client as seat_core
from newtoken.sub2api.remote import build_remote_config, load_remote_import_defaults
from newtoken.common.http_client import apply_proxy_env
from newtoken.common.runtime import get_app_dir
from newtoken.webui.tasks import WebTaskStore
from newtoken.webui.event_log import PolicyEventStore
from newtoken.webui.notifications import AccCredentialAlertManager

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
PROMOTION_COOLDOWN_SECONDS = 6 * 60 * 60
AUTO_POLICY_TASK_LABEL = "low_quota_policy"
AUTO_MAINTENANCE_TASK_LABEL = "auto_maintenance"
AUTO_POLICY_DEFAULT_INTERVAL_SECONDS = 300
AUTO_POLICY_MIN_INTERVAL_SECONDS = 30
AUTO_POLICY_MAX_INTERVAL_SECONDS = 86400
SETUP_DONE_KEY = "SUB2API_SETUP_DONE"
WEB_ENV_FIELD_ORDER = [
    "SUB2API_SETUP_DONE",
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
    "SUB2API_WEB_PORT",
    "SUB2API_WEB_HOST",
    "SUB2API_WEB_PUBLIC_BASE_URL",
    "SUB2API_WEB_SECRET",
    "SUB2API_AUTO_POLICY_ENABLED",
    "SUB2API_AUTO_POLICY_INTERVAL_SECONDS",
    "SUB2API_AUTO_POLICY_RUN_ON_START",
    "ACC_MOTHER_ACCOUNT_EMAIL",
    "CHATGPT_RANDOM_EMAIL_DOMAIN",
    "SUB2API_OIDC_API_URL",
    "SUB2API_OIDC_API_KEY",
    "SUB2API_AUTO_REGISTER_ENABLED",
    "SUB2API_AUTO_REGISTER_COUNT",
    "SUB2API_AUTO_REGISTER_THRESHOLD",
    "SUB2API_AUTO_REGISTER_DOMAIN",
    "OPENAI_ACCESS_TOKEN",
    "OPENAI_ACCOUNT_ID",
    "OPENAI_DEVICE_ID",
    "OPENAI_SESSION_TOKEN",
    "OPENAI_CLIENT_BUILD_NUMBER",
    "OPENAI_CLIENT_VERSION",
    "OPENAI_BASE_URL",
]
WEB_DEFAULT_ENV_VALUES: dict[str, str] = {
    "SUB2API_SETUP_DONE": "false",
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
    "SUB2API_WEB_PORT": str(WEB_DEFAULT_PORT),
    "SUB2API_WEB_HOST": WEB_DEFAULT_HOST,
    "SUB2API_WEB_PUBLIC_BASE_URL": "",
    "SUB2API_WEB_SECRET": "",
    "SUB2API_AUTO_POLICY_ENABLED": "true",
    "SUB2API_AUTO_POLICY_INTERVAL_SECONDS": str(AUTO_POLICY_DEFAULT_INTERVAL_SECONDS),
    "SUB2API_AUTO_POLICY_RUN_ON_START": "true",
    "ACC_MOTHER_ACCOUNT_EMAIL": "",
    "CHATGPT_RANDOM_EMAIL_DOMAIN": "example.com",
    "SUB2API_OIDC_API_URL": "",
    "SUB2API_OIDC_API_KEY": "",
    "SUB2API_AUTO_REGISTER_ENABLED": "true",
    "SUB2API_AUTO_REGISTER_COUNT": "3",
    "SUB2API_AUTO_REGISTER_THRESHOLD": "1",
    "SUB2API_AUTO_REGISTER_DOMAIN": "",
    "OPENAI_ACCESS_TOKEN": "",
    "OPENAI_ACCOUNT_ID": "",
    "OPENAI_DEVICE_ID": "",
    "OPENAI_SESSION_TOKEN": "",
    "OPENAI_CLIENT_BUILD_NUMBER": seat_core.CLIENT_BUILD_NUMBER,
    "OPENAI_CLIENT_VERSION": seat_core.CLIENT_VERSION,
    "OPENAI_BASE_URL": seat_core.DEFAULT_BASE_URL,
    "SUB2API_LOG_LEVEL": "INFO",
    "SUB2API_LOG_DIR": "",
    "SUB2API_LOG_MAX_BYTES": "10485760",
    "SUB2API_LOG_BACKUP_COUNT": "5",
}

PLACEHOLDER_MARKERS = (
    "your-",
    "your_",
    "your.",
    "your_",
    "你的",
    "示例",
    "example.com",
    "sk-admin-xxx",
)


def is_truthy_text(value: Any, *, default: bool = False) -> bool:
    """Parse common bool-ish strings without importing WebUI utils."""

    text = str(value or "").strip().lower()
    if not text:
        return bool(default)
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def has_effective_config_value(key: str, value: Any) -> bool:
    """Treat empty and template placeholder values as not configured."""

    text = str(value or "").strip()
    if not text:
        return False
    lowered = text.lower()
    if key in {"SUB2API_BASE_URL", "SUB2API_ADMIN_API_KEY", "SUB2API_AUTO_REGISTER_DOMAIN"}:
        return not any(marker in lowered for marker in PLACEHOLDER_MARKERS)
    return True


def get_setup_missing_fields(values: dict[str, str]) -> list[str]:
    """Return user-facing setup requirements still missing."""

    required_labels = (
        ("SUB2API_BASE_URL", "Sub2API 地址"),
        ("SUB2API_ADMIN_API_KEY", "Sub2API 管理员 API Key"),
        ("ACC_MOTHER_ACCOUNT_EMAIL", "母号邮箱"),
        ("SUB2API_OIDC_API_URL", "OIDC API 地址"),
        ("SUB2API_OIDC_API_KEY", "OIDC API Key"),
        ("SUB2API_AUTO_REGISTER_DOMAIN", "自动注册邮箱域名"),
    )
    missing = [
        label
        for key, label in required_labels
        if not has_effective_config_value(key, values.get(key, ""))
    ]
    has_account_id = has_effective_config_value("OPENAI_ACCOUNT_ID", values.get("OPENAI_ACCOUNT_ID", ""))
    has_token = has_effective_config_value("OPENAI_ACCESS_TOKEN", values.get("OPENAI_ACCESS_TOKEN", "")) or has_effective_config_value(
        "OPENAI_SESSION_TOKEN", values.get("OPENAI_SESSION_TOKEN", "")
    )
    if not has_account_id or not has_token:
        missing.append("母号 ACC 内容")
    return missing


def is_setup_complete(values: dict[str, str]) -> bool:
    """A console is considered installed only after setup is explicitly saved."""

    return is_truthy_text(values.get(SETUP_DONE_KEY), default=False) and not get_setup_missing_fields(values)


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
        self.scheduler: Any | None = None
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
        self.oauth_lock = threading.Lock()
        self.pushplus_token = ""
        self.policy_lock = threading.Lock()
        runtime_dir = self.env_path.parent / ".webui-runtime"
        self.cooldown_path = runtime_dir / "promotion_cooldowns.json"
        self.blocked_promotions_path = runtime_dir / "blocked_promotions.json"
        self.policy_events = PolicyEventStore(runtime_dir / "policy_events.json")
        self.acc_alerts = AccCredentialAlertManager(runtime_dir / "acc_alert_state.json")
        self.promotion_cooldowns: dict[str, float] = {}
        self.blocked_promotions: set[str] = set()
        self._load_promotion_cooldowns()
        self._load_blocked_promotions()
        self.load_config()

    def load_config(self) -> dict[str, str]:
        if not self.env_path.exists():
            write_env_file(self.env_path, WEB_DEFAULT_ENV_VALUES)
        values = dict(WEB_DEFAULT_ENV_VALUES)
        values.update(read_env_file(self.env_path))
        self.auth_secret = str(values.get("SUB2API_WEB_SECRET") or "").strip()
        self.pushplus_token = str(values.get("PUSHPLUS_TOKEN") or "").strip()
        apply_proxy_env(values.get("SUB2API_OUTBOUND_PROXY_URL", ""))
        self._load_acc_credentials(values)
        return values

    def save_config(self, updates: dict[str, str]) -> dict[str, str]:
        values = self.load_config()
        values.update({key: str(value or "") for key, value in updates.items()})
        values["SUB2API_IMPORT_CONCURRENCY"] = "5"
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
            proxy_url=str(
                self.load_config().get("SUB2API_OUTBOUND_PROXY_URL", "") or ""
            ).strip(),
        )
        if not config.access_token and not config.session_token:
            raise SeatApiWebError("缺少 ACC access token 或 session token")
        if not config.account_id:
            raise SeatApiWebError("缺少 ACC account_id")
        return seat_core.SeatClient(config)

    def is_promotion_on_cooldown(self, email: str, now: float) -> bool:
        normalized_email = str(email or "").strip().lower()
        if not normalized_email:
            return True
        with self.policy_lock:
            expires_at = float(self.promotion_cooldowns.get(normalized_email) or 0)
            if expires_at <= now:
                if self.promotion_cooldowns.pop(normalized_email, None) is not None:
                    self._write_promotion_cooldowns_locked()
                return False
            return True

    def mark_promotion_cooldown(self, email: str, now: float) -> float:
        normalized_email = str(email or "").strip().lower()
        if not normalized_email:
            return 0
        expires_at = now + PROMOTION_COOLDOWN_SECONDS
        with self.policy_lock:
            self.promotion_cooldowns[normalized_email] = expires_at
            self._write_promotion_cooldowns_locked()
        return expires_at

    def clear_promotion_cooldown(self, email: str) -> None:
        normalized_email = str(email or "").strip().lower()
        if not normalized_email:
            return
        with self.policy_lock:
            if self.promotion_cooldowns.pop(normalized_email, None) is not None:
                self._write_promotion_cooldowns_locked()

    def is_promotion_permanently_blocked(self, email: str) -> bool:
        normalized_email = str(email or "").strip().lower()
        if not normalized_email:
            return True
        with self.policy_lock:
            return normalized_email in self.blocked_promotions

    def block_promotion_permanently(self, email: str) -> None:
        normalized_email = str(email or "").strip().lower()
        if not normalized_email:
            return
        with self.policy_lock:
            if normalized_email not in self.blocked_promotions:
                self.blocked_promotions.add(normalized_email)
                self._write_blocked_promotions_locked()

    def _load_promotion_cooldowns(self) -> None:
        try:
            payload = json.loads(self.cooldown_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return
        if not isinstance(payload, dict):
            return
        loaded: dict[str, float] = {}
        for email, expires_at in payload.items():
            normalized_email = str(email or "").strip().lower()
            try:
                normalized_expires_at = float(expires_at)
            except (TypeError, ValueError):
                continue
            if normalized_email and normalized_expires_at > 0:
                loaded[normalized_email] = normalized_expires_at
        self.promotion_cooldowns = loaded

    def _write_promotion_cooldowns_locked(self) -> None:
        self.cooldown_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.cooldown_path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(self.promotion_cooldowns, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        temporary_path.replace(self.cooldown_path)

    def _load_blocked_promotions(self) -> None:
        try:
            payload = json.loads(self.blocked_promotions_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return
        if not isinstance(payload, list):
            return
        self.blocked_promotions = {
            str(email or "").strip().lower()
            for email in payload
            if str(email or "").strip()
        }

    def _write_blocked_promotions_locked(self) -> None:
        self.blocked_promotions_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.blocked_promotions_path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(sorted(self.blocked_promotions), ensure_ascii=False),
            encoding="utf-8",
        )
        temporary_path.replace(self.blocked_promotions_path)


class SeatApiWebError(RuntimeError):
    """WebUI-facing ACC error."""
