# Sub2API ACC WebUI

Sub2API ACC WebUI 是一个轻量级 Linux Web 控制台，用来管理 Sub2API OpenAI OAuth 账号、ACC 成员席位、额度轮换策略和异常告警。开源版只包含服务端 WebUI，不包含 Windows 桌面版。

## 功能介绍

- ACC 凭证管理：保存 ACC JSON / HAR / Session，加载 ACC 成员与席位状态。
- OAuth 一步建号：生成 OpenAI OAuth 授权链接，回调后自动创建并导入 Sub2API。
- 席位感知导入：OAuth 导入前读取 ACC 席位，ChatGPT 导入为 `active`，Codex 导入为 `inactive`。
- 自动额度策略：默认每 30 秒刷新 Sub2API 额度，额度阈值固定为 10%。
- ChatGPT 席位保护：ChatGPT 席位硬上限固定为 2，策略会先降席位，再检查数量，最后补席位。
- 低额度轮换：低于 10% 额度的账号会被停用 Sub2API，并把 ACC 席位改回 Codex。
- 冷却机制：正常轮换下场的账号进入 6 小时冷却期，冷却结束后才允许再次上场。
- 可用 ACC 后备池：只在可用 ACC 后备账号少于 3 个时新增账号；不会因为 ChatGPT 席位少于 3 个而新增账号。
- 401 清理：发现 `401/token_invalidated` 时，先删 ACC 成员，再删 Sub2API 账号；ACC 删除失败则永久禁止补位。
- 母号保护：母号 `user-s48XGo8NpCt5xv9XoI3b0w4z` 永远不能改为 ChatGPT。
- Sub2API 管理：扫描远程账号、同步隐私、删除 401、删除无额度、删除死号。
- 导入工具：本地账号 JSON 转换校验、复制缓存、上传缓存、粘贴 JSON 导入。
- 推送告警：ACC 凭证过期或失效时通过 PushPlus 去重推送，恢复后自动重置告警状态。
- 操作日志：席位更换与异常处理记录持久化保存，页面展示最近 300 条。
- 安全基础：Web 密码、CSRF、防止密钥明文渲染、HTTP/SOCKS 出站代理。

## 核心规则

1. Sub2API 只有 ChatGPT 席位账号可以运行。
2. Codex 席位账号可以导入 Sub2API，但状态必须是 `inactive`。
3. ChatGPT 席位账号导入 Sub2API 后状态为 `active`。
4. 后台策略每轮都会兜底同步：健康 ChatGPT 保持 `active`，Codex、母号、低额度账号保持 `inactive`。
5. 新增账号只看 ACC 后备池是否不足 3 个：后备账号必须是 Codex、非母号、不在冷却、不在永久禁用列表。
6. ChatGPT 席位最多 2 个，补位前会先降席位并检查席位数量。

## 快速开始

```bash
python -m pip install curl_cffi
cp .env.example .env
python entry.py --host 0.0.0.0 --port 28463
```

打开 `http://127.0.0.1:28463/`。

生产环境建议配置 `SUB2API_WEB_SECRET`，并通过 Nginx 或 Caddy 反代到 HTTPS。

## 关键配置

```ini
SUB2API_BASE_URL=https://your-sub2api.example.com
SUB2API_ADMIN_API_KEY=
SUB2API_GROUP_IDS=
SUB2API_PROXY_ID=
SUB2API_OUTBOUND_PROXY_URL=

SUB2API_WEB_HOST=0.0.0.0
SUB2API_WEB_PORT=28463
SUB2API_WEB_BASE_PATH=
SUB2API_WEB_PUBLIC_BASE_URL=https://your-domain.example.com/newtoken
SUB2API_WEB_SECRET=

SUB2API_AUTO_POLICY_ENABLED=true
SUB2API_AUTO_POLICY_INTERVAL_SECONDS=30
SUB2API_AUTO_POLICY_RUN_ON_START=true

ACC_BACKEND_EMAIL_TEMPLATE=sm{index:03d}@example.com
ACC_BACKEND_EMAIL_START_INDEX=1

PUSHPLUS_TOKEN=
```

`ACC_BACKEND_EMAIL_TEMPLATE` 是自动补成员账号池模板，`{index}` 会按顺序递增。例如 `sm{index:03d}@example.com` 会生成 `sm001@example.com`、`sm002@example.com`。

不要把真实 `.env`、HAR、Session、Token、私钥提交到 Git。

## 操作手册

1. 进入 WebUI，先在“配置”里填写 Sub2API 地址、Admin API Key、分组 ID、代理和 Web 公网地址。
2. 保存配置后点击“测试连接”，确认 Sub2API 可访问。
3. 在“ACC 策略”里粘贴 ACC JSON / HAR / Session，点击“保存 ACC”。
4. 点击“加载成员”，确认 ACC 成员和席位能正常读取。
5. 在“OAuth 一步建号”里填写账号名、公网回调地址、代理 ID、分组信息，点击“开始授权建号”。
6. 授权完成后回到 WebUI，系统会先读取 ACC 席位，再导入 Sub2API：ChatGPT 为 `active`，Codex 为 `inactive`。
7. 点击“扫描状态”检查远程账号状态。
8. 点击“立即运行策略”手动触发一次额度与席位策略。
9. 后台自动策略开启后，会按配置间隔自动刷新额度、降席位、补席位、同步 Sub2API active/inactive。
10. 在“更换记录”查看最近 300 条策略处理记录。

## 页面按钮说明

- `刷新任务`：刷新后台任务状态。
- `保存 ACC`：保存 ACC 凭证。
- `加载成员`：读取 ACC 成员列表。
- `执行策略` / `立即运行策略`：手动运行额度与席位策略。
- `扫描状态`：扫描 Sub2API 远程账号状态。
- `同步隐私`：同步远程账号隐私设置。
- `删 401`：删除 token invalidated / 401 的账号。
- `删无额度`：删除无额度账号。
- `删死号`：删除无法正常使用的远程账号。
- `转换校验`：校验本地账号 JSON。
- `复制缓存`：复制转换后的缓存内容。
- `上传缓存`：上传缓存到 Sub2API。

## 目录结构

```text
entry.py                     WebUI 启动入口
newtoken/webui/              HTTP 服务、页面、任务调度、ACC/OAuth API
newtoken/sub2api/            Sub2API 管理接口、OAuth 建号、额度刷新
newtoken/acc/seat_client.py  ACC 席位 API 客户端
newtoken/common/             运行时和 HTTP 工具
tests/                       策略与 WebUI 回归测试
docs/                        设计与计划文档
```

## 验证

```bash
python -m unittest discover -s tests -v
python -m compileall -q newtoken tests
```

## 部署

Linux / systemd / Nginx 部署步骤见 [DEPLOY.md](./DEPLOY.md)。

## 安全说明

这个项目会操作账号席位和 Sub2API 远程账号状态。请只在你拥有权限的环境中使用，并先用少量账号验证策略结果。删除类按钮会永久删除远程账号，建议先执行“扫描状态”确认结果，再操作删除。
