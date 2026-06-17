"""Bug E 回归测试：账号校验(converter_core.request_json)对 OpenAI 端点（CF 后）
在配了出站代理时必须走 curl_cffi 指纹+代理；其它主机/无代理保持纯 http。"""
import os
import unittest
from unittest import mock

from newtoken.sub2api import converter_core


class ValidationProxyRoutingTest(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get("SUB2API_OUTBOUND_PROXY_URL")
        os.environ["SUB2API_OUTBOUND_PROXY_URL"] = "socks5://u:p@h:1"

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("SUB2API_OUTBOUND_PROXY_URL", None)
        else:
            os.environ["SUB2API_OUTBOUND_PROXY_URL"] = self._saved

    def _patched(self, calls):
        def fake_cf(url, *, method, headers, json_body, timeout, proxy_url):
            calls["cf"] = (url, proxy_url)
            return 200, "{}", {"ok": True}

        def fake_http(url, **kwargs):
            calls["http"] = True
            return 200, "{}", {}

        return mock.patch.object(converter_core, "_cf_request_json", fake_cf), \
            mock.patch.object(converter_core, "http_request_json", fake_http)

    def test_openai_host_uses_curl_cffi(self):
        calls = {}
        p1, p2 = self._patched(calls)
        with p1, p2:
            converter_core.request_json("https://chatgpt.com/backend-api/wham/usage")
        self.assertIn("cf", calls, "OpenAI 端点未走 curl_cffi 指纹")
        self.assertNotIn("http", calls)
        self.assertEqual(calls["cf"][1], "socks5://u:p@h:1")

    def test_auth_openai_host_uses_curl_cffi(self):
        calls = {}
        p1, p2 = self._patched(calls)
        with p1, p2:
            converter_core.request_json("https://auth.openai.com/oauth/token", method="POST")
        self.assertIn("cf", calls)
        self.assertNotIn("http", calls)

    def test_non_openai_host_uses_plain_http(self):
        calls = {}
        p1, p2 = self._patched(calls)
        with p1, p2:
            converter_core.request_json("https://onebool.com/api/v1/admin/accounts")
        self.assertIn("http", calls, "非 OpenAI 主机不应走代理指纹")
        self.assertNotIn("cf", calls)

    def test_no_proxy_falls_back_to_http(self):
        os.environ.pop("SUB2API_OUTBOUND_PROXY_URL", None)
        calls = {}
        p1, p2 = self._patched(calls)
        with p1, p2:
            converter_core.request_json("https://chatgpt.com/x")
        self.assertIn("http", calls)
        self.assertNotIn("cf", calls)


if __name__ == "__main__":
    unittest.main()
