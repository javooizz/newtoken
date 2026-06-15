"""Compatibility wrapper for the ACC seat CLI."""

from __future__ import annotations

from newtoken.acc.seat_client import *  # noqa: F401,F403
from newtoken.acc.seat_client import main


if __name__ == "__main__":
    raise SystemExit(main())

