# Sub2API 独立工具

只保留 `Sub2API + ACC 席位管理` 的单页工具公开版。

## 功能

- Sub2API 远程账号统计、刷新、启停、删死号、一键隐私
- OpenAI OAuth 一键授权建号
- ACC 成员席位管理
- `recover-state -> refresh token -> 查额度 -> 开/关调度` 自动联动
- 单文件 exe 首次启动自动生成 `.env`
- GitHub Release 自动挂 exe，客户端可直接点“一键更新”

## 本地运行

```powershell
py .\sub2api_standalone_tool.py
```

或直接双击：

```text
启动Sub2API独立工具.bat
```

## Linux WebUI 部署

WebUI 入口文件是 `entry.py`，不依赖 Flask、FastAPI、requests、PySocks，只使用 Python 标准库。默认监听端口是 `28463`，避开了常见的 80、443、8080、3000 等端口。

```bash
cd /www/wwwroot/newtoken-main
python3 entry.py
```

也可以显式指定监听地址和端口：

```bash
python3 entry.py --host 0.0.0.0 --port 28463
```

宝塔面板部署建议：

- 上传项目到 `/www/wwwroot/newtoken-main`
- Python 项目启动文件填 `entry.py`
- 启动命令填 `python3 entry.py --host 0.0.0.0 --port 28463`
- 在宝塔安全、防火墙和云服务器安全组里放行 `28463`
- 公网开放前务必配置 `SUB2API_WEB_SECRET`

`.env` 示例：

```dotenv
SUB2API_BASE_URL=https://your-sub2api-host
SUB2API_ADMIN_API_KEY=your-admin-key
SUB2API_WEB_HOST=0.0.0.0
SUB2API_WEB_PORT=28463
SUB2API_WEB_SECRET=change-this-password
SUB2API_OUTBOUND_PROXY_URL=socks5://127.0.0.1:1080
```

带账号密码的 SOCKS5 写法：

```dotenv
SUB2API_OUTBOUND_PROXY_URL=socks5://user:pass@127.0.0.1:1080
```

如果希望代理端解析域名，可以写成：

```dotenv
SUB2API_OUTBOUND_PROXY_URL=socks5h://127.0.0.1:1080
```

### WebUI 代码结构

- `entry.py`：Linux/宝塔部署入口。
- `sub2api_webui.py`：兼容入口，只转发到服务器主函数。
- `sub2api_webui_server.py`：HTTP 协议、鉴权、CSRF、启动服务。
- `sub2api_webui_api.py`：API 路由分发、配置保存校验、后台任务分发。
- `sub2api_webui_page.py`：HTML 模板和值注入。
- `sub2api_webui_assets.py`：内联 CSS 和前端 JS。
- `sub2api_webui_acc.py`：ACC 凭据导入、成员加载、低额度席位策略。
- `sub2api_webui_conversion.py`：本地账号转换、校验、缓存导入。
- `sub2api_webui_oauth.py`：OpenAI OAuth 建号流程。
- `sub2api_webui_remote.py`：Sub2API 远程账号扫描和清理。
- `sub2api_webui_actions.py`：兼容导出层，保留旧 import 不炸。
- `sub2api_webui_config.py`：`.env` 读写、运行状态、远程配置和 ACC 客户端构建。
- `sub2api_webui_tasks.py`：后台任务队列、并发限制、同类任务去重。
- `sub2api_webui_utils.py`：JSON 安全序列化、脱敏、HTML 转义等小工具。

## 打包 exe

```powershell
py .\build_sub2api_standalone_exe.py --onefile
```

输出文件：

- `dist\Sub2API独立工具.exe`

## 隐私说明

- `.env`
- `*.har`
- 本地缓存文件

这些都已在本目录 `.gitignore` 中忽略，不应该上传。

## 自动 Release

- 推送到 `main`：自动更新 `latest` Release，并重新挂载最新 exe
- 推送 `v*` 标签：自动创建对应版本 Release，并挂载 exe

默认更新仓库：

- [DZenner/newtoken](https://github.com/DZenner/newtoken)
