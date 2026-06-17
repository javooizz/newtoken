# WebUI 宝塔部署

## 环境

- Linux
- Python 3.12+
- 宝塔面板
- 可访问的 Sub2API
- 已部署好的 `oidc/` 服务

自动注册链路需要：

```bash
pip install curl_cffi
```

WebUI 基础功能尽量不额外依赖 Flask/FastAPI/requests。

## 1. 上传项目

上传到例如：

```text
/www/wwwroot/sub2api-webui/
```

## 2. 准备配置

```bash
cd /www/wwwroot/sub2api-webui
cp .env.example .env
```

先至少填这些：

```ini
SUB2API_WEB_HOST=0.0.0.0
SUB2API_WEB_PORT=28463
SUB2API_WEB_SECRET=强密码
```

`28463` 不是常见端口，适合外部开放。

## 3. 宝塔 Python 项目

网站 -> Python 项目 -> 添加：

| 参数 | 值 |
|------|-----|
| 路径 | `/www/wwwroot/sub2api-webui` |
| 启动文件 | `entry.py` |
| 参数 | `--host 0.0.0.0 --port 28463` |
| Python | 3.12 |
| 开机启动 | 开启 |

## 4. 首次安装

打开：

```text
http://服务器IP:28463/
```

安装页会要求填写：

- Sub2API 地址
- Sub2API 管理员 API Key
- 母号邮箱
- 母号 ACC 内容
- OIDC API 地址
- OIDC API Key
- 自动注册邮箱域名
- SOCKS5/socks5h 出站代理

保存后会自动写入 `.env`，并启用后台定时任务。

## 5. OIDC 对接

OIDC 服务部署完成后，把它的：

- `SUB2API_OIDC_API_URL`
- `SUB2API_OIDC_API_KEY`

填进 WebUI。

OIDC 侧安装后也要把同一个 API Key 写进 `oidc/app/config.php` 的 `api_key`。

## 6. 反代（可选）

如果要用域名访问，建议让 WebUI 监听本机，再由 Nginx 反代：

```ini
SUB2API_WEB_HOST=127.0.0.1
SUB2API_WEB_PORT=28463
SUB2API_WEB_PUBLIC_BASE_URL=https://你的域名
```

Nginx 示例：

```nginx
location / {
    proxy_pass http://127.0.0.1:28463;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

## 7. 自动维护

后台调度器会自动运行这些动作：

- 扫描远程账号
- 低额度账号降级为 Codex
- ChatGPT 席位收敛到 2 个以内
- 清理"幽灵"席位（占 ChatGPT 席位却不在服务池的成员降为 Codex）
- 池内 active ChatGPT 服务号不足 2 个时自动注册
- 导入 Sub2API
- 调用 OIDC 生成卡密

浏览器关掉不会停，除非服务本身停掉。
