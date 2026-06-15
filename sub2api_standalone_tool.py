"""Compatibility wrapper for the desktop application entry."""

from __future__ import annotations

from newtoken.desktop.standalone_tool import main


if __name__ == "__main__":
    raise SystemExit(main())

