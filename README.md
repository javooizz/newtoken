# NewToken / Sub2API WebUI

一个低依赖的 Sub2API + ACC 席位管理工具。Linux 部署入口是 `entry.py`，WebUI 默认监听 `28463`，只依赖 Python 标准库。

## 当前能力

- Sub2API 远程账号扫描、异常清理、隐私同步、Codex Session 导入
- OpenAI OAuth 建号并导入 Sub2API
- ACC 成员席位管理
- ChatGPT 席位硬限制 `<= 2`
- Codex 席位不会被自动改回 ChatGPT
- 额度低于 `10%` 时，自动停用远程账号并把匹配 ACC 成员改为 Codex
- SOCKS5 / SOCKS5H 出站代理
- WebUI CSRF 防护和可选密码 `SUB2API_WEB_SECRET`
- WebUI 后端自动定时执行低额度席位策略，不依赖浏览器手动刷新

## 目录结构

```text
entry.py                         # Linux/宝塔 WebUI 入口

newtoken/
  common/                        # 运行时路径、HTTP、SOCKS5 代理
  sub2api/                       # 转换、远程账号、OAuth、额度桥接
  acc/                           # ACC Seat API、缓存、本地 env
  desktop/                       # Tk 桌面端模块
  webui/                         # Linux WebUI 模块

tools/                           # 打包、维护脚本
scripts/                         # Windows 启动脚本
docs/                            # 后续文档扩展
```

根目录只保留 `entry.py` 作为 Linux/WebUI 部署入口；业务代码都在 `newtoken/` 包里维护。

## Linux / 宝塔部署

```bash
cd /www/wwwroot/newtoken-main
python3 entry.py --host 0.0.0.0 --port 28463
```

宝塔面板建议：

- 项目目录：`/www/wwwroot/newtoken-main`
- 启动文件：`entry.py`
- 启动命令：`python3 entry.py --host 0.0.0.0 --port 28463`
- 防火墙和云安全组放行：`28463`
- 公网开放前必须配置：`SUB2API_WEB_SECRET`

## 配置示例

`.env` 放在项目根目录，不要提交到仓库。

```dotenv
SUB2API_BASE_URL=https://your-sub2api-host
SUB2API_ADMIN_API_KEY=your-admin-key
SUB2API_GROUP_IDS=
SUB2API_PROXY_ID=
SUB2API_WEB_HOST=0.0.0.0
SUB2API_WEB_PORT=28463
SUB2API_WEB_SECRET=change-this-password
SUB2API_AUTO_POLICY_ENABLED=true
SUB2API_AUTO_POLICY_INTERVAL_SECONDS=300
SUB2API_AUTO_POLICY_RUN_ON_START=true
SUB2API_OUTBOUND_PROXY_URL=socks5://127.0.0.1:1080
SUB2API_VALIDATE_CONCURRENCY=24
SUB2API_IMPORT_CONCURRENCY=50
```

## 自动任务

WebUI 启动后会在服务端开启调度线程，浏览器页面关闭也会继续跑。默认启动 10 秒后执行一次低额度策略，之后每 `SUB2API_AUTO_POLICY_INTERVAL_SECONDS` 秒执行一次。

策略任务会自动跳过未完成配置的状态；只要 `.env` 里补齐 `SUB2API_BASE_URL`、`SUB2API_ADMIN_API_KEY`、`OPENAI_ACCOUNT_ID`，以及 `OPENAI_ACCESS_TOKEN` 或 `OPENAI_SESSION_TOKEN`，下一轮就会自动执行。任务去重由后端处理，同一时间不会并发跑多个席位策略。

相关配置：

```dotenv
SUB2API_AUTO_POLICY_ENABLED=true
SUB2API_AUTO_POLICY_INTERVAL_SECONDS=300
SUB2API_AUTO_POLICY_RUN_ON_START=true
```

带账号密码：

```dotenv
SUB2API_OUTBOUND_PROXY_URL=socks5://user:pass@127.0.0.1:1080
```

让代理端解析域名：

```dotenv
SUB2API_OUTBOUND_PROXY_URL=socks5h://127.0.0.1:1080
```

## 开发验证

```bash
python3 -m compileall -q .
python3 entry.py --host 0.0.0.0 --port 28463
```

Windows 打包桌面版：

```powershell
py .\tools\build_sub2api_standalone_exe.py --onefile
```

