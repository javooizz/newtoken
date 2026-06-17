"""Bug A 回归测试：scan/账号列表查询必须按母号分组(group=)过滤，
否则会把别的分组的账号统计进本母号池。"""
import unittest
from unittest import mock

from newtoken.sub2api import remote


def _make_config(group_ids):
    return remote.Sub2APIRemoteConfig(
        base_url="https://onebool.com",
        admin_api_key="admin-key",
        group_ids=group_ids,
    )


def _empty_page(url, *args, **kwargs):
    # 模拟 Sub2API 标准响应壳：code=0 + data.items/total
    return 200, "{}", {"code": 0, "data": {"items": [], "total": 0}}


class Sub2APIGroupFilterTest(unittest.TestCase):
    def test_list_query_includes_group_filter(self):
        """group_ids=[4] 时，查询 URL 必须带 group=4。"""
        captured = []

        def fake(url, *args, **kwargs):
            captured.append(url)
            return _empty_page(url)

        with mock.patch.object(remote, "request_json", fake):
            items = remote.fetch_remote_account_list(_make_config([4]))

        self.assertEqual(items, [])
        self.assertTrue(captured, "没有发起任何请求")
        self.assertIn("group=4", captured[0], f"查询缺少分组过滤: {captured[0]}")

    def test_multiple_groups_query_each(self):
        """多分组时每个分组各查一次并合并。"""
        captured = []

        def fake(url, *args, **kwargs):
            captured.append(url)
            return _empty_page(url)

        with mock.patch.object(remote, "request_json", fake):
            remote.fetch_remote_account_list(_make_config([4, 5]))

        joined = " ".join(captured)
        self.assertIn("group=4", joined)
        self.assertIn("group=5", joined)

    def test_no_group_filter_when_unset(self):
        """未配置分组时保持旧行为（不带 group= 过滤）。"""
        captured = []

        def fake(url, *args, **kwargs):
            captured.append(url)
            return _empty_page(url)

        with mock.patch.object(remote, "request_json", fake):
            remote.fetch_remote_account_list(_make_config([]))

        self.assertTrue(captured)
        self.assertNotIn("group=", captured[0])


if __name__ == "__main__":
    unittest.main()
