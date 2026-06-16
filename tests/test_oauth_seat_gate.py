from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import newtoken.acc.seat_client as seat_core
from newtoken.sub2api.remote_oauth import PendingOpenAIOAuthSession
from newtoken.webui.config import WebState
from newtoken.webui.oauth import complete_oauth_manually


class OAuthSeatGateTest(unittest.TestCase):
    def make_state(self, account_name: str) -> WebState:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        state = WebState(Path(temp_dir.name) / ".env")
        state.last_oauth_session = {
            "remote_config": object(),
            "pending_session": PendingOpenAIOAuthSession(
                session_id="session-1",
                state="state-1",
                auth_url="https://example.test/auth",
                account_name=account_name,
                proxy_id=None,
                proxy_name="default",
                group_ids=[5],
                redirect_uri="http://localhost:1455/auth/callback",
                concurrency=10,
            ),
            "status": "waiting_callback",
            "error": "",
            "result": None,
            "callback_url": "",
        }
        return state

    def test_codex_seat_is_imported_inactive(self) -> None:
        state = self.make_state("codex@example.com")

        with mock.patch.object(
            state,
            "build_seat_client",
            return_value=object(),
        ), mock.patch(
            "newtoken.webui.oauth.seat_core.list_all_users",
            return_value=[
                {
                    "id": "user-codex",
                    "email": "codex@example.com",
                    "seat_type": seat_core.CODEX_SEAT_TYPE,
                }
            ],
        ), mock.patch(
            "newtoken.webui.oauth.complete_openai_oauth_account_creation",
            return_value={"account_id": 123, "account_name": "codex@example.com"},
        ) as complete_mock:
            result = complete_oauth_manually(
                state,
                "http://localhost:1455/auth/callback?code=abc",
            )

        self.assertEqual(result["account_id"], 123)
        complete_mock.assert_called_once()
        self.assertEqual(complete_mock.call_args.kwargs["target_status"], "inactive")

    def test_chatgpt_seat_is_imported_active(self) -> None:
        state = self.make_state("chatgpt@example.com")

        with mock.patch.object(
            state,
            "build_seat_client",
            return_value=object(),
        ), mock.patch(
            "newtoken.webui.oauth.seat_core.list_all_users",
            return_value=[
                {
                    "id": "user-chatgpt",
                    "email": "chatgpt@example.com",
                    "seat_type": seat_core.CHATGPT_SEAT_TYPE,
                }
            ],
        ), mock.patch(
            "newtoken.webui.oauth.complete_openai_oauth_account_creation",
            return_value={"account_id": 456, "account_name": "chatgpt@example.com"},
        ) as complete_mock:
            result = complete_oauth_manually(
                state,
                "http://localhost:1455/auth/callback?code=abc",
            )

        self.assertEqual(result["account_id"], 456)
        complete_mock.assert_called_once()
        self.assertEqual(complete_mock.call_args.kwargs["target_status"], "active")


if __name__ == "__main__":
    unittest.main()
