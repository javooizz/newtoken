# GPT OIDC 部署文档

`oidc/` 是独立 PHP 服务，用于 ChatGPT Business Custom OIDC + 卡密登录。WebUI 会调用它的 API 自动生成卡密。

## 目录结构

```text
oidc/
  public/               宝塔网站目录指向这里
    index.php
    .htaccess
  app/                  后端源码，不要直接暴露
    config.sample.php
  sql/
    schema.sql
  storage/              运行时目录，保存密钥和临时导出
```

## 环境要求

- PHP 7.4+
- MySQL 5.7+
- PHP 扩展：`pdo_mysql`、`openssl`

详细 PHP 设置见 [PHP_SETUP.md](./PHP_SETUP.md)。

## 1. 上传源码

建议部署到：

```text
/www/wwwroot/gpt-oidc/
```

宝塔网站目录必须指向：

```text
/www/wwwroot/gpt-oidc/public
```

不要指向项目根目录，否则 `app/`、`sql/`、`storage/` 会暴露。

## 2. 创建运行目录

```bash
mkdir -p /www/wwwroot/gpt-oidc/storage/keys
mkdir -p /www/wwwroot/gpt-oidc/storage/exports
mkdir -p /www/wwwroot/gpt-oidc/storage/ratelimits
chown -R www:www /www/wwwroot/gpt-oidc/storage
chmod -R 750 /www/wwwroot/gpt-oidc/storage
```

## 3. 创建数据库

宝塔面板 -> 数据库 -> 添加数据库：

| 字段 | 示例 |
|------|------|
| 数据库名 | `gptoidc` |
| 用户名 | `gptoidc` |
| 密码 | 面板生成 |
| 访问权限 | 本地服务器 |
| 字符集 | `utf8mb4` |

安装向导会自动导入 `sql/schema.sql`。

## 4. 宝塔建站

宝塔面板 -> 网站 -> PHP 项目 -> 添加站点：

| 字段 | 值 |
|------|-----|
| 域名 | `oidc.你的域名.com` |
| 网站目录 | `/www/wwwroot/gpt-oidc/public` |
| PHP 版本 | 7.4 或更高 |

建议开启 HTTPS。

伪静态 / Nginx 规则：

```nginx
location / {
    try_files $uri $uri/ /index.php?$query_string;
}

location ~ \.php$ {
    fastcgi_pass unix:/tmp/php-cgi-74.sock;
    fastcgi_index index.php;
    fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
    include fastcgi_params;
}

location ~ /(app|sql|storage) {
    deny all;
    return 403;
}
```

如果 PHP 版本不是 7.4，把 `php-cgi-74.sock` 改成对应版本。

## 5. 打开安装向导

访问：

```text
https://oidc.你的域名.com/install
```

需要填写：

- 应用地址：`https://oidc.你的域名.com`
- 允许的邮箱后缀：例如 `team.example.com`
- WebUI API Key：可留空自动生成，也可以手动填一串强随机值
- MySQL 地址、端口、库名、用户名、密码
- OpenAI OIDC Client ID / Secret：可以先填占位，OpenAI 后台配置完成后再回后台修改
- OpenAI Login redirect URI 白名单
- 首个管理员账号

安装完成后会生成：

- `app/config.php`
- `storage/keys/private.pem`
- `storage/keys/public.pem`
- MySQL 表结构

这些运行时文件不要提交到 git。

## 6. 和 WebUI 对接

OIDC 安装完成后，在 `app/config.php` 找到：

```php
'api_key' => '这里的值',
```

WebUI 侧填写：

```ini
SUB2API_OIDC_API_URL=https://oidc.你的域名.com
SUB2API_OIDC_API_KEY=同一个api_key
```

WebUI 会调用：

| 方法 | 地址 | 用途 |
|------|------|------|
| `GET` | `/api/status` | 健康检查和卡密统计 |
| `POST` | `/api/cards/generate` | 自动生成卡密 |
| `POST` | `/api/cards/lookup` | 查询卡密状态 |

测试命令：

```bash
curl -s https://oidc.你的域名.com/api/status \
  -H "Authorization: Bearer 你的api_key"

curl -s https://oidc.你的域名.com/api/cards/generate \
  -H "Authorization: Bearer 你的api_key" \
  -H "Content-Type: application/json" \
  -d '{"count":3,"expires_days":30,"note":"webui-test"}'
```

## 7. OpenAI Custom OIDC

OpenAI 后台配置时使用这些地址：

| OpenAI 字段 | 值 |
|-------------|-----|
| Issuer | `https://oidc.你的域名.com` |
| Discovery URL | `https://oidc.你的域名.com/.well-known/openid-configuration` |
| Authorization Endpoint | `https://oidc.你的域名.com/authorize` |
| Token Endpoint | `https://oidc.你的域名.com/token` |
| Userinfo Endpoint | `https://oidc.你的域名.com/userinfo` |
| JWKS URL | `https://oidc.你的域名.com/jwks.json` |
| Scopes | `openid profile email` |

OpenAI 向导生成 Client ID、Client Secret、Login redirect URI 后，回到：

```text
https://oidc.你的域名.com/admin
```

在“系统设置”里保存这些值。

## 8. 用户登录流程

1. 用户在 ChatGPT 里输入受控邮箱。
2. OpenAI 跳转到 `https://oidc.你的域名.com/authorize`。
3. 用户输入邮箱前缀和卡密。
4. 新卡密首次绑定邮箱，旧卡密必须匹配已绑定邮箱。
5. OIDC 签发授权码并跳回 OpenAI。
6. OpenAI 后台调用 `/token` 和 `/userinfo` 完成登录。

## 常见问题

**`/api/status` 返回 `API not configured`**

说明 `app/config.php` 里 `api_key` 为空。到后台“系统设置”填入并保存。

**WebUI 生成卡密失败，提示 `invalid api key`**

说明 WebUI 的 `SUB2API_OIDC_API_KEY` 和 OIDC `app/config.php` 里的 `api_key` 不一致。

**JWKS 或 token 报密钥错误**

检查 `storage/keys/private.pem` 和 `storage/keys/public.pem` 是否存在，且 `www` 用户可读。
