from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import newtoken.acc.seat_client as seat_core
from newtoken.sub2api.remote import (
    DEFAULT_OPENAI_IMPORT_CONCURRENCY,
    build_remote_config,
)
from newtoken.sub2api.usage_bridge import Sub2APIUsageSnapshot
from newtoken.webui.acc import (
    ACC_MOTHER_USER_ID,
    classify_remote_runtime_ids_by_acc_seat,
    delete_invalidated_accounts,
    demote_protected_mother_account,
    extract_invalidated_remote_account_ids,
    ensure_minimum_cooldown_reserve_members,
    is_mother_account_user,
    load_acc_members,
    promote_user_to_chatgpt_with_hard_cap,
)
from newtoken.webui.config import PROMOTION_COOLDOWN_SECONDS, WebState
from newtoken.webui.remote import delete_selected_remote_items


class InvalidatedAccountRulesTest(unittest.TestCase):
    def test_extracts_only_401_and_token_invalidated_account_ids(self) -> None:
        refresh_result = {
            "errors": [
                {
                    "account_id": 11,
                    "message": "HTTP 401 error_code:token_invalidated",
                },
                {
                    "account_id": 12,
                    "message": "HTTP 429 rate limited",
                },
            ],
            "results": [
                {
                    "account_id": 13,
                    "success": False,
                    "error": {
                        "status": 401,
                        "body": {"error": {"code": "token_invalidated"}},
                    },
                },
                {
                    "account_id": 14,
                    "success": False,
                    "message": "quota exhausted",
                },
            ],
        }

        self.assertEqual(
            extract_invalidated_remote_account_ids(refresh_result),
            [11, 13],
        )


class RotationCooldownRulesTest(unittest.TestCase):
    def test_cooldown_is_six_hours_and_survives_state_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            state = WebState(env_path)
            now = 1_000_000.0

            expires_at = state.mark_promotion_cooldown("USER@example.com", now)

            self.assertEqual(expires_at, now + PROMOTION_COOLDOWN_SECONDS)
            self.assertEqual(PROMOTION_COOLDOWN_SECONDS, 6 * 60 * 60)
            restarted_state = WebState(env_path)
            self.assertTrue(
                restarted_state.is_promotion_on_cooldown(
                    "user@example.com",
                    now + PROMOTION_COOLDOWN_SECONDS - 1,
                )
            )
            self.assertFalse(
                restarted_state.is_promotion_on_cooldown(
                    "user@example.com",
                    now + PROMOTION_COOLDOWN_SECONDS,
                )
            )


class AccMemberDeletionRulesTest(unittest.TestCase):
    def test_delete_user_calls_account_member_delete_endpoint(self) -> None:
        calls = []

        class RecordingSeatClient(seat_core.SeatClient):
            def _request_json(self, method, path, payload=None):
                calls.append((method, path, payload))
                return {"success": True}

        client = RecordingSeatClient(
            seat_core.Config(
                access_token="access-token",
                account_id="acc-123",
                device_id="",
                session_token="",
                client_build_number=seat_core.CLIENT_BUILD_NUMBER,
                client_version=seat_core.CLIENT_VERSION,
                base_url=seat_core.DEFAULT_BASE_URL,
            )
        )

        result = client.delete_user("user-456")

        self.assertEqual(result, {"success": True})
        self.assertEqual(
            calls,
            [
                (
                    "DELETE",
                    "/backend-api/accounts/acc-123/users/user-456",
                    None,
                )
            ],
        )

    def test_invalidated_remote_is_deleted_only_after_acc_member_deletion(self) -> None:
        class FakeSeatClient:
            def __init__(self) -> None:
                self.deleted_user_ids = []

            def delete_user(self, user_id):
                self.deleted_user_ids.append(user_id)
                if user_id == "user-fails":
                    raise RuntimeError("ACC delete failed")
                return {"success": True}

        remote_calls = []
        blocked_emails = []

        def fake_remote_delete(config, items):
            remote_calls.extend(items)
            return {"deleted": len(items), "failed": 0, "items": items}

        snapshots = {
            11: Sub2APIUsageSnapshot(
                account_id=11,
                name="ok",
                email="ok@example.com",
                quota_5h_text="--",
                quota_7d_text="--",
                usage_updated_at="",
            ),
            12: Sub2APIUsageSnapshot(
                account_id=12,
                name="fails",
                email="fails@example.com",
                quota_5h_text="--",
                quota_7d_text="--",
                usage_updated_at="",
            ),
            13: Sub2APIUsageSnapshot(
                account_id=13,
                name="already-absent",
                email="absent@example.com",
                quota_5h_text="--",
                quota_7d_text="--",
                usage_updated_at="",
            ),
        }
        users_by_email = {
            "ok@example.com": {"id": "user-ok", "email": "ok@example.com"},
            "fails@example.com": {
                "id": "user-fails",
                "email": "fails@example.com",
            },
        }

        result = delete_invalidated_accounts(
            FakeSeatClient(),
            users_by_email,
            snapshots,
            [11, 12, 13],
            remote_config=object(),
            remote_delete=fake_remote_delete,
            block_promotion=blocked_emails.append,
        )

        self.assertEqual(result["deleted_acc_user_ids"], ["user-ok"])
        self.assertEqual(
            [item["account_id"] for item in remote_calls],
            [11, 12, 13],
        )
        self.assertEqual(blocked_emails, ["fails@example.com"])
        self.assertEqual(
            result["acc_delete_failures"],
            [
                {
                    "account_id": 12,
                    "email": "fails@example.com",
                    "error": "ACC delete failed",
                }
            ],
        )


class ImportConcurrencyRulesTest(unittest.TestCase):
    def test_import_concurrency_is_always_fixed_to_five(self) -> None:
        config = build_remote_config(
            "https://sub2api.example.com",
            "admin-key",
            concurrency_text="99",
        )

        self.assertEqual(DEFAULT_OPENAI_IMPORT_CONCURRENCY, 5)
        self.assertEqual(config.concurrency, 5)


class Sub2APIRuntimeSeatRulesTest(unittest.TestCase):
    def test_only_healthy_chatgpt_accounts_are_active_in_sub2api(self) -> None:
        users = [
            {
                "id": "user-chatgpt",
                "email": "chatgpt@example.com",
                "seat_type": seat_core.CHATGPT_SEAT_TYPE,
            },
            {
                "id": "user-codex",
                "email": "codex@example.com",
                "seat_type": seat_core.CODEX_SEAT_TYPE,
            },
            {
                "id": "user-low",
                "email": "low@example.com",
                "seat_type": seat_core.CHATGPT_SEAT_TYPE,
            },
            {
                "id": ACC_MOTHER_USER_ID,
                "email": "mother@example.com",
                "seat_type": seat_core.CHATGPT_SEAT_TYPE,
            },
        ]
        usage_lookup = {
            "chatgpt@example.com": Sub2APIUsageSnapshot(
                account_id=11,
                name="chatgpt",
                email="chatgpt@example.com",
                quota_5h_text="80%",
                quota_7d_text="90%",
                usage_updated_at="",
                quota_5h_remaining_percent=80,
                quota_7d_remaining_percent=90,
            ),
            "codex@example.com": Sub2APIUsageSnapshot(
                account_id=12,
                name="codex",
                email="codex@example.com",
                quota_5h_text="95%",
                quota_7d_text="95%",
                usage_updated_at="",
                quota_5h_remaining_percent=95,
                quota_7d_remaining_percent=95,
            ),
            "low@example.com": Sub2APIUsageSnapshot(
                account_id=13,
                name="low",
                email="low@example.com",
                quota_5h_text="9%",
                quota_7d_text="90%",
                usage_updated_at="",
                quota_5h_remaining_percent=9,
                quota_7d_remaining_percent=90,
            ),
            "mother@example.com": Sub2APIUsageSnapshot(
                account_id=14,
                name="mother",
                email="mother@example.com",
                quota_5h_text="99%",
                quota_7d_text="99%",
                usage_updated_at="",
                quota_5h_remaining_percent=99,
                quota_7d_remaining_percent=99,
            ),
        }

        result = classify_remote_runtime_ids_by_acc_seat(users, usage_lookup)

        self.assertEqual(result["active_ids"], [11])
        self.assertEqual(result["inactive_ids"], [12, 13, 14])


class PermanentPromotionBlockRulesTest(unittest.TestCase):
    def test_permanent_block_survives_state_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            state = WebState(env_path)

            state.block_promotion_permanently("BLOCKED@example.com")

            restarted_state = WebState(env_path)
            self.assertTrue(
                restarted_state.is_promotion_permanently_blocked(
                    "blocked@example.com"
                )
            )
            self.assertFalse(
                restarted_state.is_promotion_permanently_blocked(
                    "healthy@example.com"
                )
            )


class CooldownReserveMemberRulesTest(unittest.TestCase):
    def test_does_not_invite_when_three_acc_reserve_members_are_available(self) -> None:
        class FakeClient:
            def __init__(self) -> None:
                self.invited: list[tuple[str, str]] = []

            def invite_user(self, email, seat_type):
                self.invited.append((email, seat_type))
                return {"success": True, "email": email}

        class FakeState:
            def is_promotion_on_cooldown(self, email, now):
                return email == "cooling@example.com"

            def is_promotion_permanently_blocked(self, email):
                return email == "blocked@example.com"

        users = [
            {
                "id": "user-reserve-1",
                "email": "reserve1@example.com",
                "seat_type": seat_core.CODEX_SEAT_TYPE,
            },
            {
                "id": "user-reserve-2",
                "email": "reserve2@example.com",
                "seat_type": seat_core.CODEX_SEAT_TYPE,
            },
            {
                "id": "user-reserve-3",
                "email": "reserve3@example.com",
                "seat_type": seat_core.CODEX_SEAT_TYPE,
            },
            {
                "id": "user-cooling",
                "email": "cooling@example.com",
                "seat_type": seat_core.CODEX_SEAT_TYPE,
            },
            {
                "id": ACC_MOTHER_USER_ID,
                "email": "mother@example.com",
                "seat_type": seat_core.CODEX_SEAT_TYPE,
            },
        ]

        result = ensure_minimum_cooldown_reserve_members(
            client := FakeClient(),
            FakeState(),
            users,
            {},
            now=1000,
        )

        self.assertEqual(result["reserve_count"], 3)
        self.assertEqual(result["target_count"], 3)
        self.assertEqual(result["missing_count"], 0)
        self.assertEqual(result["invited_members"], [])
        self.assertEqual(client.invited, [])

    def test_backend_invite_pool_skips_existing_accounts(self) -> None:
        class FakeClient:
            def invite_user(self, email, seat_type):
                return {"success": True, "email": email}

        class FakeState:
            def is_promotion_on_cooldown(self, email, now):
                return False

            def is_promotion_permanently_blocked(self, email):
                return False

        users = [
            {
                "id": "user-sm001",
                "email": "sm001@example.com",
                "seat_type": seat_core.CODEX_SEAT_TYPE,
            }
        ]

        result = ensure_minimum_cooldown_reserve_members(
            FakeClient(),
            FakeState(),
            users,
            {},
            now=1000,
        )

        self.assertEqual(
            [item["email"] for item in result["invited_members"]],
            [
                "sm002@example.com",
                "sm003@example.com",
            ],
        )

    def test_backend_invite_pool_continues_after_sm100_is_used(self) -> None:
        class FakeClient:
            def invite_user(self, email, seat_type):
                return {"success": True, "email": email}

        class FakeState:
            def is_promotion_on_cooldown(self, email, now):
                return False

            def is_promotion_permanently_blocked(self, email):
                return False

        users = [
            {
                "id": f"user-sm{index:03d}",
                "email": f"sm{index:03d}@example.com",
                "seat_type": seat_core.CHATGPT_SEAT_TYPE,
            }
            for index in range(1, 101)
        ]

        result = ensure_minimum_cooldown_reserve_members(
            FakeClient(),
            FakeState(),
            users,
            {},
            now=1000,
        )

        self.assertEqual(
            [item["email"] for item in result["invited_members"]],
            [
                "sm101@example.com",
                "sm102@example.com",
                "sm103@example.com",
            ],
        )

    def test_backend_invite_pool_uses_configured_email_template(self) -> None:
        class FakeClient:
            def invite_user(self, email, seat_type):
                return {"success": True, "email": email}

        class FakeState:
            def load_config(self):
                return {
                    "ACC_BACKEND_EMAIL_TEMPLATE": "worker-{index}@example.org",
                    "ACC_BACKEND_EMAIL_START_INDEX": "7",
                }

            def is_promotion_on_cooldown(self, email, now):
                return False

            def is_promotion_permanently_blocked(self, email):
                return False

        result = ensure_minimum_cooldown_reserve_members(
            FakeClient(),
            FakeState(),
            [],
            {},
            now=1000,
            target_count=2,
        )

        self.assertEqual(
            [item["email"] for item in result["invited_members"]],
            [
                "worker-7@example.org",
                "worker-8@example.org",
            ],
        )

    def test_invite_failure_blocks_candidate_permanently(self) -> None:
        class FakeClient:
            def invite_user(self, email, seat_type):
                raise RuntimeError("Rate limit exceeded")

        class FakeState:
            def __init__(self) -> None:
                self.blocked: list[str] = []

            def is_promotion_on_cooldown(self, email, now):
                return False

            def is_promotion_permanently_blocked(self, email):
                return False

            def block_promotion_permanently(self, email):
                self.blocked.append(email)

        state = FakeState()

        result = ensure_minimum_cooldown_reserve_members(
            FakeClient(),
            state,
            [],
            {},
            now=1000,
            target_count=1,
        )

        self.assertEqual(state.blocked, ["sm001@example.com"])
        self.assertTrue(result["skipped_members"][0]["permanently_blocked"])


class MotherAccountProtectionRulesTest(unittest.TestCase):
    def test_mother_account_id_is_hardcoded_and_detected(self) -> None:
        self.assertEqual(ACC_MOTHER_USER_ID, "user-s48XGo8NpCt5xv9XoI3b0w4z")
        self.assertTrue(is_mother_account_user({"id": ACC_MOTHER_USER_ID}))
        self.assertFalse(is_mother_account_user({"id": "user-other"}))

    def test_mother_account_can_not_be_promoted_to_chatgpt(self) -> None:
        client = object()
        with mock.patch(
            "newtoken.webui.acc.seat_core.list_all_users",
            return_value=[
                {
                    "id": ACC_MOTHER_USER_ID,
                    "email": "mother@example.com",
                    "seat_type": seat_core.CODEX_SEAT_TYPE,
                }
            ],
        ):
            with self.assertRaisesRegex(Exception, "母号"):
                promote_user_to_chatgpt_with_hard_cap(
                    client,
                    {
                        "id": ACC_MOTHER_USER_ID,
                        "email": "mother@example.com",
                        "seat_type": seat_core.CODEX_SEAT_TYPE,
                    },
                )

    def test_mother_account_is_demoted_before_policy_continues(self) -> None:
        client = object()
        users = [
            {
                "id": ACC_MOTHER_USER_ID,
                "email": "mother@example.com",
                "seat_type": seat_core.CHATGPT_SEAT_TYPE,
            },
            {
                "id": "user-normal",
                "email": "normal@example.com",
                "seat_type": seat_core.CHATGPT_SEAT_TYPE,
            },
        ]
        with mock.patch(
            "newtoken.webui.acc.seat_core.ensure_user_seat",
            return_value={"changed": True},
        ) as ensure_seat:
            result = demote_protected_mother_account(client, users)

        ensure_seat.assert_called_once_with(
            client,
            user_id=ACC_MOTHER_USER_ID,
            email=None,
            target_seat_type=seat_core.CODEX_SEAT_TYPE,
        )
        self.assertEqual(result[0]["email"], "mother@example.com")
        self.assertEqual(result[0]["reason"], "母号不能占用 ChatGPT 席位")

    def test_loading_members_also_demotes_protected_mother_account(self) -> None:
        state = mock.Mock()
        client = object()
        state.build_seat_client.return_value = client
        first_users = [
            {
                "id": ACC_MOTHER_USER_ID,
                "email": "mother@example.com",
                "seat_type": seat_core.CHATGPT_SEAT_TYPE,
            }
        ]
        second_users = [
            {
                "id": ACC_MOTHER_USER_ID,
                "email": "mother@example.com",
                "seat_type": seat_core.CODEX_SEAT_TYPE,
            }
        ]
        with (
            mock.patch(
                "newtoken.webui.acc.seat_core.list_all_users",
                side_effect=[first_users, second_users],
            ),
            mock.patch(
                "newtoken.webui.acc.seat_core.ensure_user_seat",
                return_value={"changed": True},
            ) as ensure_seat,
            mock.patch(
                "newtoken.webui.acc.seat_core.enforce_chatgpt_seat_limit",
                return_value={"users": second_users, "changed_users": []},
            ),
        ):
            result = load_acc_members(state)

        ensure_seat.assert_called_once_with(
            client,
            user_id=ACC_MOTHER_USER_ID,
            email=None,
            target_seat_type=seat_core.CODEX_SEAT_TYPE,
        )
        self.assertEqual(result["protected_mother_members"][0]["email"], "mother@example.com")


class ManualInvalidatedDeletionRulesTest(unittest.TestCase):
    def test_manual_delete_401_uses_acc_and_remote_deletion_flow(self) -> None:
        class FakeState:
            policy_events = mock.Mock()
            last_remote_scan = {
                "dead_items": [
                    {
                        "account_id": 21,
                        "name": "invalid",
                        "email": "invalid@example.com",
                        "status": "auth_error",
                        "reason": "HTTP 401 token_invalidated",
                    }
                ]
            }

            def build_seat_client(self):
                return object()

            def build_remote_config(self):
                return object()

            def block_promotion_permanently(self, email):
                return None

        expected = {"deleted_acc_user_ids": ["user-21"]}
        with (
            mock.patch(
                "newtoken.webui.remote.seat_core.list_all_users",
                return_value=[
                    {
                        "id": "user-21",
                        "email": "invalid@example.com",
                    }
                ],
            ),
            mock.patch(
                "newtoken.webui.remote.delete_invalidated_accounts",
                return_value=expected,
            ) as delete_flow,
        ):
            result = delete_selected_remote_items(FakeState(), "auth_error")

        self.assertEqual(result, expected)
        self.assertEqual(delete_flow.call_args.args[3], [21])


if __name__ == "__main__":
    unittest.main()
