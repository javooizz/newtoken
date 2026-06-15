# 部署与安装文档

## 1. 文档目标

本文件面向当前仓库中的真实实现，说明如何把系统部署到服务器并跑起来。

当前版本的核心模型是：

- 管理员后台用账号密码登录
- 用户侧只有一个入口：`/sso`
- 用户通过 `卡密 + 邮箱前缀 + 邮箱后缀` 完成登录
- 如果是新卡，系统会在首次使用时自动绑定邮箱
- 系统作为 `OIDC Provider` 对接 `ChatGPT Business`

## 2. 系统要求

### 2.1 基础环境

- Linux 云服务器或 Windows 服务器
- 公网域名，例如 `sso.example.com`
- HTTPS 证书
- `PHP 7.3`
- `MySQL 5.7+` 或 `MySQL 8.x`
- `Nginx + PHP-FPM`、`Apache` 或其他可运行 PHP 的 Web 环境

### 2.2 必须启用的 PHP 扩展

- `pdo`
- `pdo_mysql`
- `openssl`
- `json`

### 2.3 建议启用的 PHP 扩展

- `mbstring`
- `ctype`
- `filter`
- `session`

### 2.4 当前不依赖的扩展

- `curl`
- `gd`
- `zip`
- `mysqli`
- `redis`

## 3. PHP 函数要求

### 3.1 不要禁用的函数

如果你使用了 `disable_functions`，下面这些函数必须可用：

- `random_bytes`
- `hash_hmac`
- `password_hash`
- `password_verify`
- `session_start`
- `session_regenerate_id`
- `session_set_cookie_params`
- `ini_set`
- `header`
- `http_response_code`
- `json_encode`
- `json_decode`
- `filter_var`
- `file_get_contents`
- `file_put_contents`
- `mkdir`
- `is_file`
- `is_dir`
- `unlink`
- `openssl_pkey_new`
- `openssl_pkey_export`
- `openssl_pkey_get_public`
- `openssl_pkey_get_details`
- `openssl_sign`

### 3.2 可以继续禁用的危险函数

本项目不依赖这些函数，可以继续禁用：

- `exec`
- `shell_exec`
- `system`
- `passthru`
- `proc_open`
- `popen`

## 4. 目录与权限

### 4.1 目录结构

项目主要目录：

```text
gptoidc/
  app/
  cli/
  docs/
  public/
  sql/
  storage/
    exports/
    keys/
    ratelimits/
```

### 4.2 Web 根目录

必须只暴露：

- `public/`

不要把这些目录直接暴露到公网：

- `app/`
- `cli/`
- `sql/`
- `storage/`

### 4.3 写权限要求

Web 进程必须可写：

- `app/config.php`
- `storage/keys/`
- `storage/exports/`
- `storage/ratelimits/`

### 4.4 open_basedir

如果服务器启用了 `open_basedir`，至少要允许访问：

- 项目根目录
- `app/`
- `public/`
- `storage/`

## 5. 域名与邮箱规划

### 5.1 SSO 域名

建议使用单独域名或子域名：

- `sso.example.com`

### 5.2 受控邮箱后缀

系统的 `/sso` 页面会验证邮箱后缀，所以你需要提前确定：

- 哪些邮箱后缀允许登录

例如：

- `example.com`
- `member.example.com`

这些后缀会写入：

- `allowed_email_domains`

## 6. 安装方式

当前版本推荐直接使用 Web 安装向导。

安装页面：

- `/install`

它会自动完成：

- 写入 `app/config.php`
- 自动建库
- 导入 `sql/schema.sql`
- 生成 OIDC RSA 密钥
- 创建首个管理员

## 7. 安装前准备

上线前先准备：

1. 域名已解析到服务器
2. HTTPS 可用
3. MySQL 可连接
4. PHP 扩展已开启
5. `storage/` 和 `app/` 写权限已配置

## 8. 安装页面填写说明

打开：

- `https://你的域名/install`

### 8.1 Application

- `App URL`
  - 例如：`https://sso.example.com`

- `Allowed email domains`
  - 逗号分隔
  - 例如：`example.com,member.example.com`

### 8.2 Database

- `DB host`
- `DB port`
- `DB name`
- `DB user`
- `DB password`

说明：

- 当前安装器会尝试自动 `CREATE DATABASE IF NOT EXISTS`
- 因此数据库用户最好有建库权限
- 如果没有建库权限，请先手工建库再安装

### 8.3 OpenAI OIDC

- `OpenAI client ID`
- `OpenAI client secret`
- `Allowed redirect URIs`

如果你此时还没在 OpenAI 后台完成 `Custom OIDC`，可以先留空，后面在后台设置页补。

### 8.4 First admin

- `Username`
- `Email`
- `Password`

注意：

- 这里只是管理员后台账号密码
- 用户侧不使用账号密码

## 9. 安装完成后会生成什么

安装成功后，系统会生成：

- `app/config.php`
- `storage/keys/private.pem`
- `storage/keys/public.pem`

并写入数据库表：

- `admins`
- `users`
- `card_keys`
- `auth_codes`
- `access_tokens`
- `audit_logs`

## 10. 关键路由

部署完成后，应该能访问这些路径：

- `/`
- `/install`
- `/sso`
- `/admin/login`
- `/admin`
- `/.well-known/openid-configuration`
- `/jwks.json`
- `/authorize`
- `/token`
- `/userinfo`

说明：

- `/login` 会跳转到 `/sso`
- `/activate` 也会跳转到 `/sso`

## 11. 当前登录模型

用户不是用账号密码登录，而是：

1. 在 `ChatGPT Business` 输入完整邮箱
2. OpenAI 跳转到你的 `/sso`
3. 用户输入：
   - 邮箱前缀
   - 邮箱后缀
   - 卡密
   - 显示名可选
4. 系统校验卡密与邮箱
5. 完成绑定或直接登录
6. 返回 OpenAI 继续 OIDC 流程

如果 OpenAI 在授权请求里带了 `login_hint`：

- 系统会锁定邮箱后缀
- 并要求前缀拼出的完整邮箱与 OpenAI 传来的邮箱一致

## 12. OpenAI 后台配置

### 12.1 域验证

进入：

- `https://chatgpt.com/admin/identity`

先完成至少一个域名验证。

### 12.2 Custom OIDC

在 OpenAI 后台选择：

- `Set up SSO`
- `Custom OIDC`

根据你目前拿到的最新 OpenAI 文档，向导步骤通常会显示为：

1. `Provide an Identity Provider Name`
2. `Create an Application`
3. `Add Claims`
4. `Provide your OIDC Configuration`
5. `Configure Application Link`
6. `Test Single Sign-On`

填写这些值：

- `Issuer URL`：`https://你的域名`
- `Discovery URL`：`https://你的域名/.well-known/openid-configuration`
- `Authorization Endpoint`：`https://你的域名/authorize`
- `Token Endpoint`：`https://你的域名/token`
- `Userinfo Endpoint`：`https://你的域名/userinfo`
- `JWKS URL`：`https://你的域名/jwks.json`

### 12.2.1 回调地址设置

OpenAI 最新文档里，最关键的一步是：

- 你的 OIDC 应用必须支持 `authorization code grant type`
- 并且要把 OpenAI 提供的 `Login redirect URI` 加入回调白名单

你需要把它加入：

- 安装页中的 `Allowed redirect URIs`
或
- 后台设置页中的 `允许的回调地址`

注意：

- 这个地址写到配置里，不要硬编码到源码
- 这条地址由 OpenAI 当前连接唯一生成，不应直接写进文档模板
- 如果 OpenAI 后台重置连接，这条地址可能变化
- 变化后要同步更新系统中的 `oidc_allowed_redirect_uris`

然后把 OpenAI 生成的：

- `client_id`
- `client_secret`

回填到：

- `/admin` 的设置页

### 12.2.2 Claims 设置建议

在 OpenAI 向导的 `Add Claims` 步骤中，建议至少保证：

- `email`
- `email_verified`
- `name`
- `given_name`
- `family_name`
- `sub`

### 12.2.3 Application Link 是什么

如果 OpenAI 向导里出现：

- `Application Name`
- `Application login URL`

它表示的是一个**可选应用入口链接**。

作用：

- 让你在身份系统自己的“应用门户”里放一个 `ChatGPT` 入口
- 用户点击这个入口后，直接跳到 OpenAI 的 SSO 登录地址

对于当前这套项目：

- 当前没有单独的“应用门户”模块
- 所以这一步不是必填，不做也不影响核心 SSO

你只需要知道：

- `Application login URL` 是 OpenAI 给你的一个入口地址
- 它不是 `Discovery Endpoint`
- 它不是 `Login redirect URI`
- 它也不是你要写进源码的固定值

如果未来你自己想做一个“用户入口页”，可以把这条地址做成一个按钮链接，例如：

- 按钮名称：`ChatGPT`
- 点击后跳到 OpenAI 提供的 `Application login URL`

### 12.3 OpenAI 联调建议

保持：

- `SSO Optional`

测试时用两个浏览器窗口：

1. 一个普通窗口保留管理员会话
2. 一个隐身窗口测试 OpenAI 登录

## 13. Nginx 配置示例

```nginx
server {
    listen 80;
    server_name sso.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name sso.example.com;

    root /var/www/gptoidc/public;
    index index.php;

    ssl_certificate /etc/letsencrypt/live/sso.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/sso.example.com/privkey.pem;

    add_header X-Frame-Options DENY always;
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy no-referrer always;
    add_header Content-Security-Policy "default-src 'self'; frame-ancestors 'none'; base-uri 'self'" always;

    location / {
        try_files $uri /index.php?$query_string;
    }

    location ~ \.php$ {
        include fastcgi_params;
        fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        fastcgi_pass unix:/run/php/php7.3-fpm.sock;
    }

    location ~ /\. {
        deny all;
    }
}
```

## 14. php.ini 建议

至少建议：

```ini
session.use_only_cookies = 1
session.use_strict_mode = 1
session.cookie_httponly = 1
date.timezone = UTC
```

如果生产环境是 HTTPS：

- 保持安全 Cookie 策略

## 15. 本地自查清单

安装后至少检查：

1. `/install` 能打开
2. `/admin/login` 能打开
3. `/sso` 能打开
4. `/.well-known/openid-configuration` 返回 JSON
5. `/jwks.json` 返回 JSON
6. 管理员能登录后台
7. 能生成一批卡密
8. 能导出卡密 CSV
9. 测试卡密能在 `/sso` 登录

## 16. 运行前命令自查

### 16.1 Windows

```powershell
php -m
php -i | findstr /I "disable_functions open_basedir pdo pdo_mysql openssl json session"
```

### 16.2 Linux

```bash
php -m | egrep 'PDO|pdo_mysql|openssl|json|session'
php -i | grep disable_functions
php -i | grep open_basedir
```

## 17. 常见报错

### 17.1 安装页提示无法写配置

原因：

- `app/config.php` 无写权限

处理：

- 给 Web 用户写权限

### 17.2 安装页提示无法写密钥

原因：

- `storage/keys/` 无写权限

处理：

- 给 `storage/keys/` 写权限

### 17.3 安装页提示数据库失败

原因：

- MySQL 连接信息错误
- DB 用户无建库权限

处理：

- 修正数据库配置
- 或手工创建数据库再安装

### 17.4 `/sso` 提示邮箱后缀不支持

原因：

- OpenAI 传来的邮箱后缀不在 `allowed_email_domains` 中

处理：

- 到后台设置页补充允许的邮箱后缀

### 17.5 OpenAI 登录失败

检查：

1. OpenAI 后台 `Custom OIDC` 配置是否正确
2. `client_id` / `client_secret` 是否已回填到后台设置
3. `redirect_uri` 是否和 OpenAI 实际使用值完全一致
4. `/.well-known/openid-configuration` 是否可公网访问
5. `/jwks.json` 是否可公网访问

## 18. 上线前最后检查

- 管理员后台可登录
- `/sso` 单页登录可打开
- 测试卡密可以绑定并登录
- OpenAI `Custom OIDC` 已配置
- SSO 仍为 `Optional`
- 能看到 OIDC 发现文档和 JWKS
- 导出卡密正常
- 审计日志正常写入

## 19. 回滚方案

如果 OpenAI 登录联调失败：

1. 保留本地管理员会话
2. 登录 `/admin` 检查配置
3. 在 OpenAI 后台把 SSO 继续保持或恢复成 `Optional`
4. 必要时暂时停用 OpenAI 侧强制策略

## 20. 当前实现边界

这套系统当前已经实现：

- 安装 UI
- 管理后台
- 卡密生成和导出
- 单页卡密 SSO 登录
- OIDC 协议端点

但需要明确：

- 运行时仍依赖你服务器上的 PHP 环境
- `PHP 7.3` 已 EOL，建议尽快规划升级
- `ChatGPT Business` 没有 `SCIM`
- OpenAI 工作区成员管理仍需你在 OpenAI 后台处理
