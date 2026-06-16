# Linux 部署说明

下面以 `/opt/sub2api-acc-webui` 和端口 `28463` 为例。实际路径、端口、域名按你的服务器调整。

## 1. 准备环境

```bash
cd /opt
git clone <your-repo-url> sub2api-acc-webui
cd sub2api-acc-webui
python3.11 -m pip install curl_cffi
cp .env.example .env
```

编辑 `.env`：

```ini
SUB2API_BASE_URL=https://your-sub2api.example.com
SUB2API_ADMIN_API_KEY=your-admin-api-key
SUB2API_GROUP_IDS=5
SUB2API_PROXY_ID=
SUB2API_OUTBOUND_PROXY_URL=

SUB2API_WEB_HOST=127.0.0.1
SUB2API_WEB_PORT=28463
SUB2API_WEB_BASE_PATH=/newtoken
SUB2API_WEB_PUBLIC_BASE_URL=https://your-domain.example.com/newtoken
SUB2API_WEB_SECRET=change-this-password

SUB2API_AUTO_POLICY_ENABLED=true
SUB2API_AUTO_POLICY_INTERVAL_SECONDS=30
SUB2API_AUTO_POLICY_RUN_ON_START=true

ACC_BACKEND_EMAIL_TEMPLATE=sm{index:03d}@example.com
ACC_BACKEND_EMAIL_START_INDEX=1
PUSHPLUS_TOKEN=
```

ACC 的 `OPENAI_ACCESS_TOKEN` / `OPENAI_SESSION_TOKEN` / `OPENAI_ACCOUNT_ID` 建议在 WebUI 里保存，不要写进公开文档或提交到仓库。

## 2. systemd 服务

创建 `/etc/systemd/system/sub2api-acc-webui.service`：

```ini
[Unit]
Description=Sub2API ACC WebUI
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/sub2api-acc-webui
ExecStart=/usr/bin/python3.11 /opt/sub2api-acc-webui/entry.py --host 127.0.0.1 --port 28463
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
systemctl daemon-reload
systemctl enable --now sub2api-acc-webui
systemctl status sub2api-acc-webui
```

## 3. Nginx 反代

如果 WebUI 挂在 `/newtoken`：

```nginx
location /newtoken/ {
    proxy_pass http://127.0.0.1:28463/newtoken/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

如果 WebUI 独占一个域名根路径，把 `.env` 的 `SUB2API_WEB_BASE_PATH` 留空，并使用：

```nginx
location / {
    proxy_pass http://127.0.0.1:28463/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

## 4. OAuth 回调

WebUI 的“公网回调地址”填写外网可访问的 WebUI 根地址：

- 子路径部署：`https://your-domain.example.com/newtoken`
- 根路径部署：`https://your-domain.example.com`

程序会自动使用 `/oauth/callback` 作为回调路径。请确认防火墙、Nginx、HTTPS 证书和 `SUB2API_WEB_PUBLIC_BASE_URL` 都一致。

OAuth 回调完成后会先查 ACC 席位，再导入 Sub2API：

- ChatGPT 席位：导入后设置为 `active`
- Codex 席位：导入后设置为 `inactive`
- ACC 找不到该账号：阻止导入

## 5. 自动策略顺序

自动策略每轮会按下面顺序执行：

1. 刷新 Sub2API 额度。
2. 识别 401 / token invalidated。
3. 对 401 账号先删 ACC，再删 Sub2API；ACC 删除失败则永久禁止补位。
4. 把低于 10% 额度的账号降为 Codex，并停用 Sub2API。
5. 检查 ChatGPT 席位数量，确保不超过 2。
6. 统计可用 ACC 后备账号：Codex、非母号、不在冷却、不在永久禁用列表。
7. 只有可用 ACC 后备账号少于 3 个时，才按账号池模板新增账号。
8. 从健康 Codex 后备账号中补 ChatGPT 席位。
9. 最终同步 Sub2API 状态：健康 ChatGPT 为 `active`，Codex、母号、低额度账号为 `inactive`。

## 6. 验证

```bash
curl -I http://127.0.0.1:28463/newtoken/
journalctl -u sub2api-acc-webui -n 100 --no-pager
```

登录 WebUI 后：

1. 点击“测试连接”确认 Sub2API 可访问。
2. 保存 ACC 后点击“加载成员”。
3. 点击“扫描状态”确认远程账号数据。
4. 点击“立即运行策略”观察 ChatGPT 席位、低额度数和更换记录。

## 7. 升级建议

升级前先备份：

```bash
tar -czf /opt/sub2api-acc-webui-backup-$(date +%Y%m%d-%H%M%S).tar.gz /opt/sub2api-acc-webui
```

升级时保留 `.env` 和 `.webui-runtime`，它们包含本地配置、冷却记录、永久禁用记录和策略日志。
