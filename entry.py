"""Linux/WebUI entry point.

Run with:
    python3 entry.py

The server reads SUB2API_WEB_HOST and SUB2API_WEB_PORT from .env.  The default
port is 28463, chosen to avoid common service ports.
"""

from __future__ import annotations

from sub2api_webui import main


if __name__ == "__main__":
    raise SystemExit(main())
