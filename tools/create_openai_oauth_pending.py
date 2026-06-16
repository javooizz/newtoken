"""生成一条新的 OpenAI OAuth 授权链接。"""

from __future__ import annotations

import json
import sys

from newtoken.sub2api.remote_oauth import (
    create_openai_oauth_pending_session,
    load_openai_oauth_defaults,
)


def main() -> int:
    env_path = sys.argv[1] if len(sys.argv) > 1 else ".env"
    redirect_uri = (
        sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:28463/oauth/callback"
    )
    defaults = load_openai_oauth_defaults(env_path)
    result = create_openai_oauth_pending_session(
        base_url=defaults.get("base_url", ""),
        admin_api_key=defaults.get("admin_api_key", ""),
        proxy_id=defaults.get("proxy_id", ""),
        proxy_url=defaults.get("proxy_url", ""),
        proxy_name=defaults.get("proxy_name", "default"),
        redirect_uri=redirect_uri,
        group_ids=[],
        group_name=defaults.get("group_name", "cc"),
        concurrency=defaults.get("concurrency", "10"),
    )
    pending = result["pending_session"]
    print(
        json.dumps(
            {
                "session_id": pending.session_id,
                "state": pending.state,
                "auth_url": pending.auth_url,
                "redirect_uri": pending.redirect_uri,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
