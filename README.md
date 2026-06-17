# NewToken Linux WebUI

Sub2API + ACC 席位自动维护工具，带一个可独立部署的 OIDC 卡密登录服务。WebUI 默认监听 `28463`，适合 Linux / 宝塔面板部署。

> 📖 **自部署 / 完整跑起来**：见 [docs/14-部署运行手册](./docs/14-部署运行手册.md)（前置、`.env` 配置与值来源、启动、逐环节验证、🔴 关键约束、故障排查、清理）。
> 自动注册已重写为 **codex oauth + 自建 OIDC 卡密 SSO**（免手机验证拿 codex token），旧「企业 SSO 免验证码」方案已弃，见 [docs/04 头部](./docs/04-自动注册引擎.md) 与 [docs/13](./docs/13-已知问题与维护要点.md)。

## 仓库包含什么

```text
entry.py                 WebUI 启动入口
newtoken/                WebUI、ACC、Sub2API 对接源码
oidc/                    GPT OIDC 卡密登录服务源码（PHP）
scripts/                 辅助脚本
tools/                   兼容工具入口
DEPLOY.md                WebUI 宝塔部署说明
oidc/DEPLOY_OIDC.md      OIDC 宝塔部署说明
```

## 快速启动 WebUI

```bash
cp .env.example .env
python entry.py --host 0.0.0.0 --port 28463
```

浏览器打开：

```text
http://服务器IP:28463/
```

首次进入会先打开安装配置页。安装完成前不会进入控制台。

## WebUI 必填配置

- Sub2API 地址和管理员 API Key
- 母号邮箱
- 母号 ACC 内容：直接粘贴 ACC JSON / HAR / Session / token
- OIDC API 地址和 API Key
- SOCKS5/socks5h 出站代理（可选）
- 自动注册邮箱域名、补号数量、池子阈值
- Web 密码、监听地址、监听端口、自动维护周期

保存后后台调度器会自动运行，不需要手动刷新页面。

## OIDC 服务

OIDC 是独立 PHP 服务，源码在 `oidc/`。它负责：

- ChatGPT Business Custom OIDC 登录
- 卡密生成、绑定、查询
- 对 WebUI 暴露 `/api/status`、`/api/cards/generate`、`/api/cards/lookup`

部署顺序建议：

1. 先按 [oidc/DEPLOY_OIDC.md](./oidc/DEPLOY_OIDC.md) 部署 OIDC。
2. 在 OIDC 后台复制 `api_key`。
3. 再按 [DEPLOY.md](./DEPLOY.md) 部署 WebUI。
4. WebUI 里填写 `SUB2API_OIDC_API_URL=https://你的OIDC域名` 和同一个 `api_key`。

## 自动维护策略

- ChatGPT 席位最多保留 2 个，Codex 席位不会被自动改回 ChatGPT。
- 额度低于 10% 的账号会停止 Sub2API 调用，并被改为 Codex。
- **占着 ChatGPT 席位却不在服务池的"幽灵"成员**会先被降为 Codex，释放硬上限（永不踢人，只改席位类型）。
- **池内 active ChatGPT 服务号少于 2 个**时自动注册、导入 Sub2API、生成 OIDC 卡密。
- 后台定时任务由服务端运行，浏览器关闭也不影响。

> ⚠️ 部分号运行 ~20 次后会概率性报 401，需二次 codex oauth（含 add-phone）续命——当前为删号补新的消耗模式，续命待实现，见 [docs/13-已知问题与维护要点](./docs/13-已知问题与维护要点.md)。

## 依赖

WebUI 基础功能尽量使用 Python 标准库，不依赖 Flask/FastAPI/requests。自动注册链路需要：

```bash
pip install curl_cffi
```

OIDC 服务需要 PHP + MySQL，详见 [oidc/PHP_SETUP.md](./oidc/PHP_SETUP.md)。
