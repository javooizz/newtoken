# Sub2API WebUI

Sub2API + ACC 席位管理工具。WebUI 默认监听 `28463`。

## 快速开始

```bash
python entry.py --host 0.0.0.0 --port 28463
```

浏览器打开 `http://127.0.0.1:28463/`

## 文档

| 文档 | 内容 |
|------|------|
| [DEPLOY.md](./DEPLOY.md) | 宝塔面板部署教程（含数据库、Nginx、SOCKS5） |
| [CHANGELOG.md](./CHANGELOG.md) | 版本更新记录 |

## 功能

- OAuth 一步建号 → Sub2API
- 远程账号扫描、异常清理、隐私同步
- ACC 席位管理（ChatGPT ≤ 2 硬锁）
- 低额度 (<10%) 自动改 Codex
- 自动策略调度器（300s 周期）
- SOCKS5/socks5h 出站代理
- WebUI CSRF 防护 + 密码登录

## .env 配置

```ini
SUB2API_BASE_URL=https://your-ip
SUB2API_ADMIN_API_KEY=sk-admin-xxx
SUB2API_OUTBOUND_PROXY_URL=socks5://127.0.0.1:1080
SUB2API_WEB_SECRET=强密码
```

完整配置见 `.env.example`

## 目录

```
entry.py  newtoken/  scripts/  tools/
```

## 相关项目

**GPT OIDC** — ChatGPT Business SSO 身份提供者，PHP 应用，独立部署，与 WebUI 共用 OAuth 域名。

## 依赖

Python 3.12 + curl_cffi
