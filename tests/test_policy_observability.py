from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from newtoken.webui.event_log import PolicyEventStore
from newtoken.webui.notifications import (
    AccCredentialAlertManager,
    is_acc_credential_error,
)
from newtoken.webui.policy_runner import record_policy_events, run_observed_policy
from newtoken.webui.api import dispatch_api, save_config_from_payload
from newtoken.webui.config import WebState
from newtoken.webui.page import build_index_html


class PolicyEventStoreTest(unittest.TestCase):
    def test_keeps_only_latest_three_hundred_events_across_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "policy_events.json"
            store = PolicyEventStore(path)

            for index in range(305):
                store.append(
                    action="promote_chatgpt",
                    email=f"user{index}@example.com",
                    account_id=index,
                    reason="quota available",
                    result="success",
                    created_at=float(index),
                )

            restarted = PolicyEventStore(path)
            events = restarted.list_recent()

            self.assertEqual(len(events), 300)
            self.assertEqual(events[0]["account_id"], 304)
            self.assertEqual(events[-1]["account_id"], 5)


class AccCredentialAlertTest(unittest.TestCase):
    def test_recognizes_acc_expiry_errors_without_matching_unrelated_failures(self) -> None:
        self.assertTrue(
            is_acc_credential_error(
                "Your authentication token has been invalidated. Please sign in again."
            )
        )
        self.assertTrue(is_acc_credential_error("token_expired"))
        self.assertTrue(is_acc_credential_error("缺少 ACC access token 或 session token"))
        self.assertFalse(is_acc_credential_error("Sub2API HTTP 401 admin key invalid"))
        self.assertFalse(is_acc_credential_error("network connection refused"))

    def test_alert_is_sent_once_until_recovery_and_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "acc_alert_state.json"
            sent = []

            manager = AccCredentialAlertManager(
                state_path,
                sender=lambda token, title, content: sent.append(
                    (token, title, content)
                ),
            )
            first = manager.notify_failure(
                "push-token",
                "token_expired",
                now=1_000.0,
            )
            second = manager.notify_failure(
                "push-token",
                "token_expired",
                now=1_030.0,
            )
            restarted = AccCredentialAlertManager(
                state_path,
                sender=lambda token, title, content: sent.append(
                    (token, title, content)
                ),
            )
            third = restarted.notify_failure(
                "push-token",
                "token_expired",
                now=1_060.0,
            )

            self.assertTrue(first["sent"])
            self.assertTrue(second["deduplicated"])
            self.assertTrue(third["deduplicated"])
            self.assertEqual(len(sent), 1)

            restarted.mark_recovered(now=2_000.0)
            fourth = restarted.notify_failure(
                "push-token",
                "token_expired",
                now=2_030.0,
            )

            self.assertTrue(fourth["sent"])
            self.assertEqual(len(sent), 2)

    def test_push_failure_is_reported_without_raising(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = AccCredentialAlertManager(
                Path(temp_dir) / "acc_alert_state.json",
                sender=lambda token, title, content: (_ for _ in ()).throw(
                    RuntimeError("push unavailable")
                ),
            )

            result = manager.notify_failure(
                "push-token",
                "token_expired",
                now=1_000.0,
            )

            self.assertFalse(result["sent"])
            self.assertEqual(result["error"], "push unavailable")


class PolicyRunnerTest(unittest.TestCase):
    def test_records_seat_changes_and_invalidated_account_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = PolicyEventStore(Path(temp_dir) / "events.json")
            result = {
                "changed_members": [
                    {
                        "email": "down@example.com",
                        "account_id": 11,
                        "quota_5h": "8%",
                        "quota_7d": "40%",
                    }
                ],
                "promoted_members": [
                    {
                        "email": "up@example.com",
                        "account_id": 12,
                        "quota_5h": "80%",
                        "quota_7d": "70%",
                    }
                ],
                "invalidated_result": {
                    "invalidated_accounts": [
                        {
                            "email": "bad@example.com",
                            "account_id": 13,
                            "acc_deleted": False,
                            "permanently_blocked": True,
                            "remote_deleted": True,
                        }
                    ]
                },
                "reserve_members": {
                    "invited_members": [
                        {
                            "email": "reserve@example.com",
                            "account_id": 14,
                            "seat_type": "usage_based",
                        }
                    ],
                    "skipped_members": [
                        {
                            "email": "failed@example.com",
                            "account_id": 15,
                            "reason": "invite failed",
                        }
                    ],
                },
            }

            record_policy_events(store, result, created_at=1_000.0)

            events = store.list_recent()
            self.assertEqual(
                [event["action"] for event in events],
                [
                    "delete_invalidated",
                    "promote_chatgpt",
                    "invite_member",
                    "invite_member",
                    "demote_codex",
                ],
            )
            self.assertTrue(events[0]["details"]["permanently_blocked"])
            self.assertEqual(events[2]["result"], "failed")
            self.assertEqual(events[3]["result"], "success")

    def test_acc_failure_alerts_once_and_success_marks_recovered(self) -> None:
        class FakeEvents:
            def __init__(self) -> None:
                self.items = []

            def append(self, **item):
                self.items.append(item)
                return item

        class FakeAlerts:
            def __init__(self) -> None:
                self.failures = []
                self.recovered = 0

            def notify_failure(self, token, error_text):
                self.failures.append((token, error_text))
                return {"sent": True, "deduplicated": False, "error": ""}

            def mark_recovered(self):
                self.recovered += 1
                return True

        class FakeState:
            pushplus_token = "push-token"
            policy_events = FakeEvents()
            acc_alerts = FakeAlerts()

        state = FakeState()
        with mock.patch(
            "newtoken.webui.policy_runner.enforce_acc_low_quota_policy",
            side_effect=RuntimeError("token_expired"),
        ):
            with self.assertRaisesRegex(RuntimeError, "token_expired"):
                run_observed_policy(state)

        self.assertEqual(len(state.acc_alerts.failures), 1)
        self.assertEqual(state.policy_events.items[-1]["action"], "policy_error")

        with mock.patch(
            "newtoken.webui.policy_runner.enforce_acc_low_quota_policy",
            return_value={"changed_members": [], "promoted_members": []},
        ):
            run_observed_policy(state)

        self.assertEqual(state.acc_alerts.recovered, 1)
        self.assertEqual(
            state.policy_events.items[-1]["action"],
            "acc_credentials_recovered",
        )


class PolicyObservabilityWebUITest(unittest.TestCase):
    def test_pushplus_token_is_saved_but_never_returned_or_rendered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = WebState(Path(temp_dir) / ".env")

            result = save_config_from_payload(
                state,
                {"PUSHPLUS_TOKEN": "private-push-token"},
            )
            html = build_index_html(state.load_config(), state)

            self.assertEqual(result["PUSHPLUS_TOKEN"], "")
            self.assertIn("PUSHPLUS_TOKEN_MASKED", result)
            self.assertNotIn("private-push-token", html)
            self.assertIn('id="cfg_pushplus_token"', html)
            self.assertIn('id="policy_event_log"', html)

    def test_backend_account_pool_template_is_saved_and_rendered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = WebState(Path(temp_dir) / ".env")

            result = save_config_from_payload(
                state,
                {
                    "ACC_BACKEND_EMAIL_TEMPLATE": "worker-{index}@example.org",
                    "ACC_BACKEND_EMAIL_START_INDEX": "7",
                },
            )
            html = build_index_html(state.load_config(), state)

            self.assertEqual(
                result["ACC_BACKEND_EMAIL_TEMPLATE"],
                "worker-{index}@example.org",
            )
            self.assertEqual(result["ACC_BACKEND_EMAIL_START_INDEX"], "7")
            self.assertIn('id="cfg_acc_backend_email_template"', html)
            self.assertIn("worker-{index}@example.org", html)

    def test_import_section_does_not_render_duplicate_concurrency_controls(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = WebState(Path(temp_dir) / ".env")

            html = build_index_html(state.load_config(), state)

            self.assertNotIn('id="cfg_validate_concurrency"', html)
            self.assertIn('id="cfg_validate_concurrency_config"', html)

    def test_policy_events_api_returns_latest_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state = WebState(Path(temp_dir) / ".env")
            state.policy_events.append(
                action="promote_chatgpt",
                email="user@example.com",
                account_id=88,
                result="success",
                created_at=1_000.0,
            )

            result = dispatch_api("/api/policy/events", {"limit": 50}, state)

            self.assertEqual(result["total"], 1)
            self.assertEqual(result["items"][0]["account_id"], 88)


if __name__ == "__main__":
    unittest.main()
