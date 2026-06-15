# 宝塔面板部署教程

## 环境

宝塔面板 → 软件商店装好：
- **Nginx** 1.22+
- **MySQL** 5.7+（宝塔自带的就行）
- **Python 3.12**（Python项目管理器）

```bash
pip3.12 install curl_cffi
```

## 部署

### 1. 上传项目到 `/www/wwwroot/sub2api-webui/`

### 2. 配置 `.env`

```bash
cp .env.example .env && vim .env
```

```ini
SUB2API_BASE_URL=https://你的Sub2API
SUB2API_ADMIN_API_KEY=sk-admin-xxx
SUB2API_GROUP_IDS=1
SUB2API_OUTBOUND_PROXY_URL=socks5://代理IP:1080
SUB2API_WEB_HOST=0.0.0.0
SUB2API_WEB_PORT=28463
SUB2API_WEB_PUBLIC_BASE_URL=http://服务器IP:28463
SUB2API_WEB_SECRET=16位强密码
```

### 3. 宝塔 Python 项目管理器

网站 → Python 项目 → 添加：

| 参数 | 值 |
|------|-----|
| 路径 | `/www/wwwroot/sub2api-webui` |
| 文件 | `entry.py` |
| 参数 | `--host 0.0.0.0 --port 28463` |
| Python | 3.12 |
| 开机 | ✅ |

### 4. 防火墙放行

宝塔 → 安全 → 添加 `28463 TCP`

### 5. 访问

`http://服务器IP:28463/` → 输入密码 → 登录

---

## Nginx 反代（可选）

```nginx
location / {
    proxy_pass http://127.0.0.1:28463;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

## OIDC 搭配部署

GPT OIDC（PHP SSO）独立部署，与 WebUI 通过 Nginx 共用一个域名。详见 OIDC 项目目录下的 `DEPLOY_OIDC.md`。
