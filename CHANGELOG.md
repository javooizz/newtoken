# Changelog
## 2026-06-17

### proxy_id 绑定修复 + 30s 周期 + 401 根因实验

**改动：**

- **修复 proxy_id 未绑定（commit `f0398ec`）**：走 `/accounts/data` 导入时 proxy_id 不在导入体内生效（`ImportData` 不读该字段），须随 `group_ids` 一起进 post-import bulk-update payload——`build_openai_post_import_update_payload` 原先漏了 proxy_id。修复后导入号正确绑定 `SUB2API_PROXY_ID`，号被 Sub2API 调用时走与母号/注册一致的出口代理（生产 `GET /accounts/9748 → proxy_id=33` 验证落库）。
- **维护周期下限 60→30s（commit `9f13dd2`）**：`AUTO_POLICY_MIN_INTERVAL_SECONDS` 调至 30，对齐 main 默认，支持高频轮换/观察。
- **401 根因实验结论**：曾假设 401 源于号被调用 IP ≠ 注册 IP，绑母号同代理（proxy_id=33）后实测**号仍大量 401**——IP 一致非主因，根因回到 **rt 概率性短命**；真正稳定仍需 401 续命（二次 codex oauth + add-phone，详见 [docs/13](./docs/13-已知问题与维护要点.md)「401 号续命」节）。

### 合并 main 策略层 + 重建自动补号模型

**背景：** `feat/javoo`（含 OIDC 卡密注册引擎）与 `origin/main`（更完善的额度/席位策略层，但脱敏移除了注册引擎）是两套独立源码。本次把 main 的策略层与可观测性合入 feat/javoo，并按 main `README` 的稳定态模型重建自动补号决策。

**改动：**

- **合入 main 策略层**：`enforce_acc_low_quota_policy` 完整轮换（刷额度 / 删 401 / 低额度 ChatGPT→Codex / 6h 冷却 / 母号保护 / ChatGPT 席位收敛 ≤2 / Sub2API active|inactive 同步）；新增 `event_log.py`（策略事件持久化，前端"更换记录"展示最近 300 条）、`notifications.py`（PushPlus 去重告警）、`policy_runner.py`（可观测包装）；`api.py` 新增 `/api/policy/events` 路由。
- **重建自动补号模型（`auto.py`）**：
  - **删除错误护栏**：旧逻辑用"ChatGPT 席位数 ≥ K"门控注册，当存在"占席位却不在服务池"的幽灵席位时会永久卡死、不再补号。
  - **新增幽灵席位清理（Phase 2.5）**：占着 ChatGPT 席位却不在 Sub2API 服务池的成员（"幽灵"）先降为 Codex（符合"永不 remove member"），释放被占满的硬上限。
  - **补号触发改为按服务号水位**：`need = K(=2) − 池内 active ChatGPT 服务号数`（取自策略层 `active_chatgpt_remote_ids`），不再用旧的"Sub2API alive 数 ≥ threshold"。先降后补（demote-first），任何时刻 ChatGPT 席位 ≤ K，护栏因此不再需要。
- **OpenAI 传输统一走 curl_cffi + socks5h 代理**：`seat_client.py`（席位接口）、`converter_core.py`（额度校验）、`register.py`（注册）三处，避免纯 TLS 被 Cloudflare 403/reset。
- **导入修复**：同母号多号共享 workspace `chatgpt_account_id` 会被 codex-session 端点误判重复、只进 1 个；改走 `/accounts/data` 按 user_id/email 去重并绑定 `group_ids`。
- **远程列表分组过滤**：Sub2API 服务端只认单数 `group=<id>` 过滤（`group_id`/`group_ids` 被忽略），导入/扫描相应适配。
- **安装标记修复**：`SUB2API_SETUP_DONE` 在配置齐全时仍为 `false` 导致 WebUI 卡在"未安装"，已修正。

**已知待办（未实现）：** 部分号在运行 ~20 次后会**概率性**报 401（首次 codex oauth 的 rt 失效，非每个号都会），需对该号做**第二次 codex oauth（会触发 add-phone 手机验证）续命**并更新池内 rt；当前 `delete_invalidated` 对 401 号直接删除 + 注册新号补位，是一次性消耗模式。add-phone 自动化处理待接入，详见 [docs/13](./docs/13-已知问题与维护要点.md) 第 1 节。

## 2026-06-15

### 修复：ACC 导入解析兼容性

**改动：**

- ACC 粘贴框现在兼容 `OPENAI_*` / `ACCESS_TOKEN` / `SESSION_TOKEN` 这类 `.env` 片段
- 兼容 Cookie 里的 `session-token`
- 兼容直接粘贴 Bearer token
- 当已提供 `accessToken` 和 `accountId` 时，不再因为同时存在 `sessionToken` 就强制联网覆盖

### 交付：补齐 OIDC 源码与部署文档

**背景：** WebUI 已经有 OIDC 配置入口，但仓库缺少 OIDC 服务源码和部署说明，别人拿到项目后无法完整部署。

**改动：**

- 新增 `oidc/` 独立 PHP 服务源码、SQL 表结构、运行目录占位文件
- 新增 `oidc/DEPLOY_OIDC.md` 和 `oidc/PHP_SETUP.md`
- README 和 WebUI 部署文档补充 WebUI + OIDC 双服务部署顺序
- OIDC 安装向导和后台设置新增 WebUI API Key 配置
- OIDC API 认证错误统一返回 JSON，方便 WebUI 判断失败原因
- `.gitignore` 忽略 OIDC 运行时配置、私钥、卡密导出和限流文件

### 重构：WebUI 安装向导与自动维护控制台

**背景：** 旧 WebUI 把安装、配置、手动 OAuth 建号和日常运维混在一个页面里，容易让首次部署的人误操作，也不利于宝塔面板部署。

**改动：**

- WebUI 改为“安装配置页 + 控制台”两段式
- 安装未完成时不会进入完整控制台
- 去掉手动 OAuth 一步建号入口，后台自动维护改为唯一入口
- 增加 OIDC API 配置、母号 ACC 配置、自动注册域名、自动注册数量和阈值
- 安装完成后，后台调度器自动运行完整维护流程
- 修复自动维护远程扫描统计字段错误，避免误判池子为空

### WebUI 优化

- 统一控制台视觉层级，减少重复配置区块
- 设置区、状态区、任务区分层更清晰
- 安装状态直接展示缺失项
- 保留 SOCKS5 出站代理和 CSRF 防护
