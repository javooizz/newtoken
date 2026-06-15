# 宝塔面板部署教程

## 环境

宝塔面板安装：

- Nginx 1.22+
- Python 3.12
- 可访问的 Sub2API 后台
- 独立部署好的 OIDC API

自动注册链路需要：

```bash
pip3.12 install curl_cffi
```

基础 WebUI 本身不依赖 Flask/FastAPI/requests。

## 部署

### 1. 上传项目

上传到：

```bash
/www/wwwroot/sub2api-webui/
```

### 2. 准备配置文件

```bash
cd /www/wwwroot/sub2api-webui
cp .env.example .env
```

可以只先填 Web 监听和密码，其余配置进入 WebUI 安装页填写：

```ini
SUB2API_WEB_HOST=0.0.0.0
SUB2API_WEB_PORT=28463
SUB2API_WEB_SECRET=16位以上强密码
```

### 3. 宝塔 Python 项目

网站 → Python 项目 → 添加：

| 参数 | 值 |
|------|-----|
| 路径 | `/www/wwwroot/sub2api-webui` |
| 文件 | `entry.py` |
| 参数 | `--host 0.0.0.0 --port 28463` |
| Python | 3.12 |
| 开机启动 | 开启 |

`28463` 是默认非高频端口。需要换端口时，同时改 `.env`、宝塔参数和防火墙。

### 4. 防火墙放行

宝塔 → 安全 → 添加：

```text
28463 TCP
```

### 5. 首次安装

访问：

```text
http://服务器IP:28463/
```

安装页必须填写：

- Sub2API 地址
- Sub2API 管理员 API Key
- 母号邮箱
- 母号 ACC 内容：直接粘贴 ACC JSON / HAR / Session / token
- OIDC API 地址
- OIDC API Key
- 自动注册邮箱域名
- SOCKS5/socks5h 出站代理

保存后 `SUB2API_SETUP_DONE=true`，控制台才会完整启用。

## Nginx 反代

可选。若使用 HTTPS 域名反代，建议把 WebUI 仍绑定在本机：

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

## 自动维护

安装完成后，服务端调度器会按 `SUB2API_AUTO_POLICY_INTERVAL_SECONDS` 自动运行。浏览器关闭也不影响后台任务。

自动维护包含：

- 扫描 Sub2API 远程账号
- 低额度账号停止调用
- ACC 成员强制改 Codex
- ChatGPT 席位收敛到 2 个以内
- 池子不足时自动注册
- 导入 Sub2API
- 调用 OIDC API 生成卡
