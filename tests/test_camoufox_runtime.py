from __future__ import annotations

from newtoken.common.camoufox_runtime import build_camoufox_context_options, build_camoufox_launch_options


def test_build_camoufox_launch_options_defaults(monkeypatch) -> None:
    for name in (
        "CAMOUFOX_OS",
        "CAMOUFOX_HUMANIZE",
        "CAMOUFOX_BLOCK_IMAGES",
        "CAMOUFOX_GEOIP",
        "CAMOUFOX_PROXY_SERVER",
        "CAMOUFOX_PROXY_USERNAME",
        "CAMOUFOX_PROXY_PASSWORD",
        "BROWSER_PROXY_SERVER",
        "BROWSER_PROXY_USERNAME",
        "BROWSER_PROXY_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)

    options = build_camoufox_launch_options(headless=False)

    assert options == {
        "headless": False,
        "os": "windows",
        "humanize": True,
    }


def test_build_camoufox_launch_options_proxy_enables_geoip(monkeypatch) -> None:
    monkeypatch.setenv("CAMOUFOX_PROXY_SERVER", "http://127.0.0.1:8080")
    monkeypatch.setenv("CAMOUFOX_PROXY_USERNAME", "user")
    monkeypatch.setenv("CAMOUFOX_PROXY_PASSWORD", "pass")
    monkeypatch.delenv("CAMOUFOX_GEOIP", raising=False)

    options = build_camoufox_launch_options(headless=True)

    assert options["headless"] is True
    assert options["geoip"] is True
    assert options["proxy"] == {
        "server": "http://127.0.0.1:8080",
        "username": "user",
        "password": "pass",
    }


def test_build_camoufox_context_options_only_uses_explicit_overrides(monkeypatch) -> None:
    monkeypatch.delenv("CAMOUFOX_LOCALE", raising=False)
    monkeypatch.delenv("CAMOUFOX_USER_AGENT", raising=False)

    assert build_camoufox_context_options() == {}

    monkeypatch.setenv("CAMOUFOX_LOCALE", "en-US")
    monkeypatch.setenv("CAMOUFOX_USER_AGENT", "Custom UA")

    assert build_camoufox_context_options() == {
        "locale": "en-US",
        "user_agent": "Custom UA",
    }
