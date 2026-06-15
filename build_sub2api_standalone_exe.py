"""Compatibility wrapper for the desktop build tool."""

from __future__ import annotations

from tools.build_sub2api_standalone_exe import main


if __name__ == "__main__":
    raise SystemExit(main())

