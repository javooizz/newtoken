"""统一日志基础设施：轮转文件 + 控制台 + 关联 ID(run_id) + 敏感数据脱敏。

服务全链路唯一日志入口。仅依赖标准库。

用法：
    from newtoken.common.logging_setup import setup_logging, get_logger, log_run_context
    setup_logging(level="INFO")                 # 进程启动时调一次
    logger = get_logger("webui.register")       # 各模块取 logger
    with log_run_context("auto203500/r1"):      # 关联 ID 自动注入每条日志
        logger.info("...")
"""
from __future__ import annotations

import contextvars
import logging
import logging.handlers
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from newtoken.common.runtime import get_app_dir

LOGGER_ROOT = "sub2api"
_LOG_FILENAME = "sub2api.log"
_DEFAULT_LEVEL = "INFO"
_DEFAULT_MAX_BYTES = 10 * 1024 * 1024
_DEFAULT_BACKUP_COUNT = 5
_FORMAT = "%(asctime)s | %(levelname)-5s | %(threadName)-16s | %(run_id)s | %(name)s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

_run_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("sub2api_run_id", default="-")
_configured = False
_log_path: Path | None = None


# --- 脱敏 -------------------------------------------------------------------

def mask_token(value: str) -> str:
    """token 只留前 6 位 + 长度。"""
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 10:
        return "***"
    return f"{text[:6]}…(masked,len={len(text)})"


def mask_card(value: str) -> str:
    """卡密只留前 4 位。"""
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 4:
        return "***"
    return f"{text[:4]}****"


def mask_password(value: str) -> str:
    return "***" if value else ""


# 兜底网：抓 JWT 与 "key":"value" 形态的密钥（防 HTTP 响应体里漏密钥）。
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{6,}(?:\.[A-Za-z0-9_-]+)?")
_KV_SECRET_RE = re.compile(
    r"(\"?(?:access_token|refresh_token|id_token|password|client_secret|api_key|card)\"?\s*[:=]\s*\"?)"
    r"([A-Za-z0-9._\-]{6,})",
    re.IGNORECASE,
)


def mask_text(text: str) -> str:
    """对一段文本做兜底脱敏。"""
    s = str(text)
    s = _JWT_RE.sub(lambda m: mask_token(m.group(0)), s)
    s = _KV_SECRET_RE.sub(lambda m: m.group(1) + mask_token(m.group(2)), s)
    return s


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = _run_id_var.get()
        return True


class _MaskingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:
            return True
        masked = mask_text(rendered)
        if masked != rendered:
            record.msg = masked
            record.args = ()
        return True


# --- 关联 ID ----------------------------------------------------------------

@contextmanager
def log_run_context(run_id: str) -> Iterator[str]:
    token = _run_id_var.set(str(run_id or "-"))
    try:
        yield _run_id_var.get()
    finally:
        _run_id_var.reset(token)


# --- 配置 -------------------------------------------------------------------

def _resolve_level(level: object) -> int:
    raw = level if level not in (None, "") else (os.environ.get("SUB2API_LOG_LEVEL") or _DEFAULT_LEVEL)
    if isinstance(raw, int):
        return raw
    resolved = logging.getLevelName(str(raw).strip().upper())
    return resolved if isinstance(resolved, int) else logging.INFO


def _resolve_int(value: object, env_key: str, default: int) -> int:
    raw = value if value not in (None, "") else os.environ.get(env_key)
    try:
        out = int(str(raw).strip())
        return out if out > 0 else default
    except (TypeError, ValueError):
        return default


def _resolve_log_dir(log_dir: object) -> Path:
    raw = log_dir if log_dir not in (None, "") else os.environ.get("SUB2API_LOG_DIR")
    if raw:
        return Path(str(raw)).expanduser()
    return get_app_dir(__file__) / "logs"


def setup_logging(
    *,
    level: object = None,
    log_dir: object = None,
    max_bytes: object = None,
    backup_count: object = None,
) -> Path:
    """配置 sub2api 根 logger（幂等）。返回日志文件路径。"""
    global _configured, _log_path
    root = logging.getLogger(LOGGER_ROOT)
    resolved_level = _resolve_level(level)
    if _configured and _log_path is not None:
        root.setLevel(resolved_level)
        return _log_path

    target_dir = _resolve_log_dir(log_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / _LOG_FILENAME

    formatter = logging.Formatter(_FORMAT, _DATEFMT, defaults={"run_id": "-"})
    ctx_filter = _ContextFilter()
    mask_filter = _MaskingFilter()

    file_handler = logging.handlers.RotatingFileHandler(
        path,
        maxBytes=_resolve_int(max_bytes, "SUB2API_LOG_MAX_BYTES", _DEFAULT_MAX_BYTES),
        backupCount=_resolve_int(backup_count, "SUB2API_LOG_BACKUP_COUNT", _DEFAULT_BACKUP_COUNT),
        encoding="utf-8",
    )
    console_handler = logging.StreamHandler()
    for handler in (file_handler, console_handler):
        handler.setFormatter(formatter)
        handler.addFilter(ctx_filter)
        handler.addFilter(mask_filter)
        root.addHandler(handler)

    root.setLevel(resolved_level)
    root.propagate = False
    _configured = True
    _log_path = path
    return path


def get_logger(name: str) -> logging.Logger:
    clean = str(name or "").strip()
    if not clean or clean == LOGGER_ROOT:
        return logging.getLogger(LOGGER_ROOT)
    if clean.startswith(LOGGER_ROOT + "."):
        return logging.getLogger(clean)
    return logging.getLogger(f"{LOGGER_ROOT}.{clean}")


def reset_logging() -> None:
    """清空配置（供测试与重配置使用）。"""
    global _configured, _log_path
    root = logging.getLogger(LOGGER_ROOT)
    for handler in list(root.handlers):
        try:
            handler.close()
        except Exception:
            pass
        root.removeHandler(handler)
    _configured = False
    _log_path = None
