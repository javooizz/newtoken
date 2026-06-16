"""Camoufox 启动参数统一入口。"""

from __future__ import annotations

import os

try:
    from camoufox.sync_api import Camoufox
except ImportError:  # pragma: no cover
    from camoufox import Camoufox  # type: ignore[no-redef]


def _env_text(name: str) -> str:
    """读取环境变量文本值。"""
    return os.getenv(name, "").strip()


def _env_flag(name: str, default: bool = False) -> bool:
    """把常见真假文本统一转成布尔值。"""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def build_camoufox_launch_options(*, headless: bool) -> dict[str, object]:
    """统一组装 Camoufox 浏览器启动参数。"""
    options: dict[str, object] = {
        "headless": headless,
        "os": _env_text("CAMOUFOX_OS") or "windows",
    }

    if _env_flag("CAMOUFOX_HUMANIZE", default=True):
        options["humanize"] = True
    if _env_flag("CAMOUFOX_BLOCK_IMAGES"):
        options["block_images"] = True

    proxy_server = _env_text("CAMOUFOX_PROXY_SERVER") or _env_text("BROWSER_PROXY_SERVER")
    proxy_username = _env_text("CAMOUFOX_PROXY_USERNAME") or _env_text("BROWSER_PROXY_USERNAME")
    proxy_password = _env_text("CAMOUFOX_PROXY_PASSWORD") or _env_text("BROWSER_PROXY_PASSWORD")
    if proxy_server:
        proxy: dict[str, str] = {"server": proxy_server}
        if proxy_username:
            proxy["username"] = proxy_username
        if proxy_password:
            proxy["password"] = proxy_password
        options["proxy"] = proxy

    if _env_flag("CAMOUFOX_GEOIP", default=bool(proxy_server)):
        options["geoip"] = True
    return options


def build_camoufox_context_options() -> dict[str, object]:
    """统一组装 Camoufox context 参数。"""
    options: dict[str, object] = {}
    locale = _env_text("CAMOUFOX_LOCALE")
    if locale:
        options["locale"] = locale

    # 默认不强改 UA，避免 Firefox 内核和 Chrome UA 混搭。
    user_agent = _env_text("CAMOUFOX_USER_AGENT")
    if user_agent:
        options["user_agent"] = user_agent
    return options
