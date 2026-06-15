# Changelog

## 2026-06-15

### 重构：OAuth 一步建号流程

**背景：** 原 WebUI 的 OAuth 建号是"生成授权链接"+"完成建号"两个分立按钮，用户容易把"登录授权"和"建号导入"当成两个独立动作，中间停顿可能触发接码验证。

**改动：**

- `newtoken/webui/oauth.py` 重写：增加状态机（idle → waiting_callback → creating_account → done/error），`threading.Lock` 防止回调重复建号
- `newtoken/webui/server.py`：新增 `GET /oauth/callback` 公开入口，OpenAI 授权后自动回调触发建号
- `newtoken/webui/api.py`：旧路由 `/api/oauth/create`、`/api/oauth/complete` 替换为 `/api/oauth/start`、`/api/oauth/status`、`/api/oauth/manual-complete`
- `newtoken/webui/page.py`：OAuth 区块改为一步式布局——一个主按钮 + 状态展示 + 手动 Code 兜底
- `newtoken/webui/assets.py`：前端实现 `startOauth()` 一步启动、自动弹出授权页、每 2s 轮询状态、状态切换 CSS 反馈
- `newtoken/webui/config.py`：`WebState` 增加 `oauth_lock`；`WEB_ENV_FIELD_ORDER` 和 `WEB_DEFAULT_ENV_VALUES` 增加 `SUB2API_WEB_PUBLIC_BASE_URL`

### 新增配置项

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SUB2API_WEB_PUBLIC_BASE_URL` | 空 | 宝塔反代或公网部署时，用于生成 OAuth redirect URI |

### WebUI 优化

- 登录页改用 CSS 变量（原硬编码色值），与主面板主题一致
- OAuth 状态块去掉内联样式，改用 `.oauth-state` CSS 类，区分 ok/bad 状态背景色
- `build_index_view` 移除无效模板变量 `oauth_redirect_uri`
- `_parse_group_ids` 增加 `ValueError` 和 `gid > 0` 校验
- `_handle_oauth_callback` 回调页面增加与登录页一致的最简样式
