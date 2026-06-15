# 总体架构文档

## 1. 设计原则

本项目的实现原则：

- 尽量少依赖第三方库
- 以单体 PHP 应用形式实现
- 保持目录扁平，目标压缩到 `20 个文件内`
- 优先保证可维护性和安全性，不为了省文件牺牲关键校验
- 优先支持 `ChatGPT Business` 的 OIDC 单一场景，不抽象成通用 IAM 平台

## 2. 系统角色关系

### 2.1 OpenAI 侧

- `ChatGPT Business`：OIDC Client / Relying Party
- OpenAI 管理后台：负责域名验证、SSO 配置、用户工作区邀请

### 2.2 本系统

- 卡密发放系统
- 单页 `/sso` 登录系统
- OIDC Identity Provider

### 2.3 用户侧

- 新用户：通过 `/sso` 首次绑定卡密和邮箱
- 已绑定用户：通过 `/sso` 继续使用卡密登录并通过 OIDC 进入 ChatGPT Business

## 3. 逻辑架构

系统分为四层：

### 3.1 表现层

负责：

- 单页 `/sso` 登录页
- 授权确认页
- 管理员页面
- 错误页

### 3.2 业务层

负责：

- 卡密生成与校验
- 新卡首次绑定
- 已绑定卡密登录
- 管理员操作
- OIDC 授权与令牌签发
- 审计日志写入

### 3.3 安全层

负责：

- Session 安全配置
- CSRF 校验
- `/sso` 登录限流
- Token 生成与校验
- 卡密哈希

### 3.4 数据层

负责：

- MySQL 连接
- 预处理 SQL
- 查询封装
- 事务处理

## 4. 运行组件

首版运行组件建议：

- `PHP 7.3`
- `MySQL 5.7+` 或 `MySQL 8.x`
- `Nginx + PHP-FPM` 或 `Apache + mod_php/php-fpm`
- `OpenSSL` 用于 JWT 签名
- 受信任的 HTTPS 证书

## 5. 关键业务流程

### 5.1 卡密生成与导出

1. 管理员登录后台
2. 输入数量、有效期、备注
3. 系统使用 `random_bytes()` 生成卡密原文
4. 原文仅用于当次 CSV 导出
5. 数据库仅保存卡密哈希与元数据
6. 记录审计日志

### 5.2 `/sso` 首次绑定

1. 用户访问 `/sso`
2. 提交卡密、邮箱前缀、邮箱后缀
3. 系统校验卡密状态和邮箱后缀
4. 如果是新卡，系统自动创建绑定关系
5. 记录绑定日志

### 5.3 `/sso` 普通登录

1. 用户访问 `/sso`
2. 提交卡密、邮箱前缀、邮箱后缀
3. 系统验证该邮箱是否与卡密绑定一致
4. 登录成功后轮换 Session ID
5. 进入授权流或系统首页

### 5.4 OpenAI OIDC 授权

1. OpenAI 调用 `/authorize`
2. 系统校验 `client_id`、`redirect_uri`、`scope`、`state`、`nonce`、`code_challenge`
3. 若用户未登录，则跳转到本地登录页
4. 登录后生成一次性授权码
5. 将用户带回 OpenAI 回调地址
6. OpenAI 调用 `/token` 换取 `access_token` 和 `id_token`
7. 系统返回签名后的 token 数据

## 6. URL 设计

建议首版路由如下：

- `/`：首页或状态页
- `/sso`：用户单页卡密登录
- `/logout`：退出登录
- `/authorize`：OIDC 授权端点
- `/token`：OIDC 令牌端点
- `/userinfo`：OIDC 用户信息端点
- `/.well-known/openid-configuration`：OIDC 发现文档
- `/jwks.json`：公钥发布
- `/admin`：后台首页
- `/admin/login`：管理员登录
- `/admin/cards`：卡密管理
- `/admin/cards/export`：导出卡密
- `/admin/users`：用户管理
- `/admin/logs`：审计日志

## 7. 模块划分建议

代码阶段建议保留以下文件划分：

1. `public/index.php`
2. `app/bootstrap.php`
3. `app/config.sample.php`
4. `app/db.php`
5. `app/http.php`
6. `app/security.php`
7. `app/session.php`
8. `app/cards.php`
9. `app/users.php`
10. `app/admin.php`
11. `app/oidc.php`
12. `app/views.php`
13. `cli/init_admin.php`
14. `cli/gen_signing_keys.php`
15. `sql/schema.sql`

加上当前 7 份文档，整体仍可控制在 20 个文件内。

## 8. 配置设计

首版配置项建议：

- `APP_ENV`
- `APP_DEBUG`
- `APP_URL`
- `APP_KEY`
- `DB_HOST`
- `DB_PORT`
- `DB_NAME`
- `DB_USER`
- `DB_PASS`
- `OIDC_ISSUER`
- `OIDC_CLIENT_ID`
- `OIDC_CLIENT_SECRET`
- `OIDC_ALLOWED_REDIRECT_URIS`
- `OIDC_ID_TOKEN_TTL`
- `OIDC_ACCESS_TOKEN_TTL`
- `SESSION_NAME`
- `ALLOWED_EMAIL_DOMAINS`

## 9. OIDC 声明设计

建议 `id_token` 中至少包含：

- `iss`
- `sub`
- `aud`
- `exp`
- `iat`
- `auth_time`
- `nonce`
- `email`
- `email_verified`
- `name`
- `given_name`
- `family_name`

`sub` 设计要求：

- 稳定
- 不暴露内部自增 ID 细节
- 不因邮箱变更而直接失效

建议使用内部生成的不可预测字符串作为用户主体标识。

## 10. 错误处理原则

- 对外错误尽量模糊，避免泄露敏感信息
- 对内日志必须带明确失败原因
- 授权失败时按 OIDC 规范返回错误参数
- 管理后台错误应保留可追踪审计记录

## 11. OpenAI 联调架构建议

联调时遵循以下顺序：

1. 先部署测试域名，例如 `sso.example.com`
2. 先保证 `/.well-known/openid-configuration` 和 `/jwks.json` 可公网访问
3. 再在 OpenAI 后台选择 `Custom OIDC`
4. 保持 SSO 为 `Optional`
5. 使用两个浏览器窗口或一个隐身窗口并行测试
6. 通过测试后，再切换到正式访问入口

## 12. 应急设计

为防止配置错误锁死管理员，首版要求：

- 至少保留一个本地管理员账户
- 该管理员账户不依赖 OpenAI 登录
- 上线前先验证该账户可正常登录后台
- 生产切换时不得立刻强制所有管理员只走 SSO

## 13. 未来扩展兼容点

虽然首版不做多租户，但建议保留以下低成本扩展空间：

- `oidc_clients` 表可以延后增加
- `allowed_email_domains` 可从配置升级到数据库
- `audit_logs` 设计时预留 `actor_type`、`actor_id`、`target_type` 字段
- 用户状态中预留 `disabled`、`locked`、`pending_reset` 等状态
