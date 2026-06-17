"""Bug D 回归测试：seat_client 访问 chatgpt.com 时，配置了代理就必须走
curl_cffi(指纹)+socks5h 代理（纯 Python TLS 经 CF 会 403）；无代理保持旧路径。"""
import unittest
from unittest import mock

from newtoken.acc import seat_client


def _cfg(proxy_url=""):
    return seat_client.Config(
        access_token="at",
        account_id="acc",
        device_id="dev",
        session_token="st",
        client_build_number="1",
        client_version="v",
        base_url="https://chatgpt.com",
        proxy_url=proxy_url,
    )


class SeatProxyRoutingTest(unittest.TestCase):
    def test_uses_curl_cffi_when_proxy_set(self):
        calls = {}

        def fake_curl(url, *, method, headers, body, proxy_url, timeout=30):
            calls["curl"] = proxy_url
            return 200, "OK", '{"items": [], "total": 0}', {}

        def fake_http(*args, **kwargs):
            calls["http"] = True
            return 200, "OK", '{"items": [], "total": 0}', {}

        with mock.patch.object(seat_client, "_curl_request_text", fake_curl), \
             mock.patch.object(seat_client, "http_request_text", fake_http):
            seat_client.SeatClient(_cfg("socks5://u:p@h:1")).list_users(0, 25)

        self.assertIn("curl", calls, "配了代理却没走 curl_cffi")
        self.assertNotIn("http", calls, "配了代理却仍走纯 http")
        # 路由层把原始 proxy_url 透传给传输层（socks5h 升级在传输层内部完成）
        self.assertEqual(calls["curl"], "socks5://u:p@h:1")

    def test_curl_transport_upgrades_socks5_to_socks5h(self):
        captured = {}

        class _FakeResp:
            status_code = 200
            reason = "OK"
            text = "{}"
            headers = {}

        def fake_request(method, url, **kwargs):
            captured["proxies"] = kwargs.get("proxies")
            captured["impersonate"] = kwargs.get("impersonate")
            return _FakeResp()

        fake_curl_cffi = mock.MagicMock()
        fake_curl_cffi.requests.request = fake_request
        with mock.patch.dict("sys.modules", {"curl_cffi": fake_curl_cffi}):
            seat_client._curl_request_text(
                "https://chatgpt.com/x", method="GET", headers={}, body=None,
                proxy_url="socks5://u:p@h:1",
            )
        self.assertEqual(
            captured["proxies"],
            {"http": "socks5h://u:p@h:1", "https": "socks5h://u:p@h:1"},
        )
        self.assertEqual(captured["impersonate"], "chrome")

    def test_uses_plain_http_when_no_proxy(self):
        calls = {}

        def fake_curl(*args, **kwargs):
            calls["curl"] = True
            return 200, "OK", "{}", {}

        def fake_http(url, **kwargs):
            calls["http"] = True
            return 200, "OK", '{"items": [], "total": 0}', {}

        with mock.patch.object(seat_client, "_curl_request_text", fake_curl), \
             mock.patch.object(seat_client, "http_request_text", fake_http):
            seat_client.SeatClient(_cfg("")).list_users(0, 25)

        self.assertIn("http", calls)
        self.assertNotIn("curl", calls)


if __name__ == "__main__":
    unittest.main()
