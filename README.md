# Sub2API WebUI

Sub2API + ACC 席位自动维护工具。WebUI 默认监听 `28463`，适合 Linux / 宝塔面板部署。

## 快速开始

```bash
python entry.py --host 0.0.0.0 --port 28463
```

浏览器打开 `http://服务器IP:28463/`，先完成安装配置：

- Sub2API 地址和管理员 API Key
- 母号 ACC 信息：母号邮箱 + 直接粘贴 ACC JSON / HAR / Session / token
- OIDC API 地址和 API Key
- SOCKS5/socks5h 出站代理
- 自动注册域名、补号数量、池子阈值
- Web 密码、端口、自动维护周期

保存后进入控制台，后台定时任务会自动运行，不需要手动刷新页面。

## 功能

- 首次安装向导：未安装前不能误进控制台
- 完整自动维护：席位校正、远程扫描、自动补号、导入 Sub2API、生成 OIDC 卡
- ACC 席位硬策略：ChatGPT 席位最多 2，Codex 不自动改回 ChatGPT
- 低额度策略：额度低于 10% 自动停止 Sub2API 调用并改为 Codex
- 远程账号扫描、异常清理、隐私同步
- SOCKS5/socks5h 出站代理
- WebUI CSRF 防护 + 密码登录

## 配置

建议先复制模板：

```bash
cp .env.example .env
```

关键配置：

```ini
SUB2API_BASE_URL=https://你的Sub2API
SUB2API_ADMIN_API_KEY=sk-admin-xxx
SUB2API_OUTBOUND_PROXY_URL=socks5://127.0.0.1:1080
SUB2API_WEB_SECRET=强密码

ACC_MOTHER_ACCOUNT_EMAIL=mother@example.com
# OPENAI_* 由 WebUI 粘贴 ACC 内容后自动写入

SUB2API_OIDC_API_URL=https://你的OIDC
SUB2API_OIDC_API_KEY=...
SUB2API_AUTO_REGISTER_DOMAIN=@team.example.com
```

完整配置见 `.env.example`。

## 文档

| 文档 | 内容 |
|------|------|
| [DEPLOY.md](./DEPLOY.md) | 宝塔面板部署教程 |
| [CHANGELOG.md](./CHANGELOG.md) | 更新记录 |

## 目录

```text
entry.py
newtoken/
  acc/
  common/
  sub2api/
  webui/
scripts/
tools/
```

## 依赖

基础 WebUI 尽量使用 Python 标准库。自动注册链路需要 `curl_cffi`。
