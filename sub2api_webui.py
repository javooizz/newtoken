"""Compatibility entry point for the dependency-light Linux WebUI."""

from __future__ import annotations

from newtoken.webui.server import main


if __name__ == "__main__":
    raise SystemExit(main())
