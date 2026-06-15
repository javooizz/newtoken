# 安全设计文档

## 1. 安全目标

本项目要尽量降低以下常见风险：

- SQL 注入
- XSS
- CSRF
- 会话固定
- 爆破登录
- 卡密泄露
- 授权码重放
- Token 泄露
- 开放重定向
- 配置错误导致管理员锁死

需要明确：

- 没有任何系统可以承诺“绝对零漏洞”
- `PHP 7.3` 已停止官方安全维护，这是客观风险
- 本项目的目标是按当前能力将高频、高危的实现错误压到最低

## 2. 威胁模型

### 2.1 外部攻击者

能力假设：

- 能构造恶意表单和 URL
- 能尝试撞库和口令爆破
- 能尝试利用开放重定向和回调参数
- 能截获不安全通道中的请求

### 2.2 内部误操作

能力假设：

- 管理员误导出错误卡密批次
- 管理员误启用强制 SSO 导致锁死
- 运维误配置 HTTPS 或 Cookie

### 2.3 数据库泄露场景

能力假设：

- 攻击者获得数据库读权限
- 攻击者尝试利用库中信息恢复卡密、管理员密码、授权码或 token

## 3. 安全基线

首版必须满足：

1. 所有数据库查询使用 `PDO` 预处理
2. 关闭 `PDO::ATTR_EMULATE_PREPARES`
3. 不直接拼接用户输入到 SQL
4. 所有随机值使用 `random_bytes()`
5. 管理员密码使用 `password_hash()`
6. 卡密、授权码、Access Token 仅存哈希
7. 登录成功后 `session_regenerate_id(true)`
8. Cookie 打开 `HttpOnly`、`Secure`、`SameSite=Lax`
9. 所有表单启用 CSRF Token
10. 所有 HTML 输出默认转义
11. 强制 HTTPS
12. `redirect_uri` 精确匹配
13. 授权码一次性使用
14. 日志记录关键行为但不记录明文秘密值

## 4. PHP 7.3 风险说明

项目要求兼容 `PHP 7.3`，但需要向业务方明确：

- PHP 7.3 已经 EOL
- 即使应用代码安全，运行时本身仍存在长期维护风险
- 建议上线后尽快规划升级到受支持版本

应对策略：

- 避免引入高风险扩展依赖
- 尽量使用 PHP 核心成熟函数
- 服务器层面使用最新 OpenSSL、Nginx/Apache、MySQL
- 强制及时更新系统补丁

## 5. 身份与管理员密码安全

### 5.1 管理员密码存储

建议：

```php
$material = hash_hmac('sha256', $password, APP_PEPPER);
$hash = password_hash($material, PASSWORD_BCRYPT, ['cost' => 12]);
```

原则：

- `APP_PEPPER` 只放服务器配置或环境变量
- 不写入数据库
- 不写入代码仓库

### 5.2 管理员与员工账户分离

- 管理员和员工使用独立登录入口
- 管理员账户不得与员工身份混用
- 管理员权限必须明显区分 `owner` 与 `admin`

### 5.3 登录失败限制

建议限流：

- 同一 IP 对 `/sso` 登录页：8 次失败 / 15 分钟
- 同一账号失败累计达到阈值后短时锁定
- 管理员登录采用更严格阈值

## 6. Session 安全

### 6.1 会话配置

必须设置：

- `session.cookie_httponly = 1`
- `session.cookie_secure = 1`
- `session.use_only_cookies = 1`
- `session.use_strict_mode = 1`

### 6.2 登录后处理

- 登录成功后轮换 Session ID
- 权限切换后轮换 Session ID
- 退出登录时清空 Session 和 Cookie

### 6.3 超时策略

- 员工页面空闲超时建议 `2 小时`
- 管理后台空闲超时建议 `30 分钟`

## 7. CSRF 与表单安全

以下页面必须启用 CSRF 防护：

- `/sso` 登录
- 管理员登录
- 卡密生成
- 卡密导出
- 卡密吊销

要求：

- 每个表单带一次性 CSRF Token
- Token 与 Session 绑定
- 校验失败直接拒绝请求并记日志

## 8. XSS 防护

原则：

- 所有用户可见输出默认走 `htmlspecialchars(..., ENT_QUOTES, 'UTF-8')`
- 不直接渲染未清洗的备注、姓名、错误回显
- 后台审计日志详情如需显示 JSON，需先转义

建议响应头：

- `Content-Security-Policy: default-src 'self'; frame-ancestors 'none'; base-uri 'self'`
- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: no-referrer`

## 9. SQL 注入防护

### 9.1 数据访问规范

必须：

- 全部使用 `PDO::prepare()` + `execute()`
- 禁用模拟预处理
- 不允许把用户输入拼接进 `WHERE`、`ORDER BY`、`LIMIT`、表名、列名

### 9.2 动态字段处理

如确需动态排序或筛选：

- 必须使用白名单映射
- 不可直接把请求参数作为列名拼接

## 10. 卡密安全

### 10.1 生成策略

- 使用 `random_bytes()` 生成原始随机值
- 编码后形成可读卡密
- 建议长度不低于 20 字符

### 10.2 存储策略

- 仅保存哈希
- 明文只在生成导出时出现一次
- 后台后续只展示部分掩码

### 10.3 导出策略

- 导出仅允许管理员操作
- 导出动作必须写审计日志
- 导出文件默认建议管理员下载后立即转存到受控位置

## 11. OIDC 专项安全

### 11.1 Redirect URI

- 必须精确匹配
- 不允许通配符
- 不允许开放跳转

### 11.2 PKCE

- 强制 `S256`
- 缺少 `code_challenge` 直接拒绝
- 缺少 `code_verifier` 的 token 请求直接拒绝

### 11.3 授权码

- 一次性使用
- 短时过期
- 数据库存哈希
- 与 `client_id`、`redirect_uri`、`code_challenge` 强绑定

### 11.4 ID Token

- 使用 `RS256`
- 私钥不得放在 Web 可访问目录
- JWT 需包含标准时间字段
- `nonce` 有值时必须原样带回

### 11.5 Access Token

- 首版使用短期 Bearer Token
- 数据库存哈希
- 到期即失效
- 首版不发放 `refresh_token`

## 12. 日志与隐私

### 12.1 可以记录

- 账号 ID
- 操作类型
- IP
- 时间
- 是否成功
- 部分上下文标识

### 12.2 不应记录

- 管理员明文密码
- 明文卡密
- 明文授权码
- 明文 access token
- 明文 client secret

### 12.3 建议脱敏

- 邮箱可视情况部分脱敏
- 审计详情内若含敏感值，建议仅记录摘要

## 13. 密钥管理

### 13.1 应用密钥

- `APP_KEY`：用于 HMAC 卡密、授权码、token 摘要
- `APP_PEPPER`：用于管理员密码预处理

### 13.2 OIDC 签名密钥

- 使用独立 RSA 私钥签发 `id_token`
- 对外通过 `jwks.json` 发布公钥
- 私钥文件权限必须最小化

### 13.3 轮换策略

- 首版可以手工轮换
- 轮换时需保证旧公钥保留一段时间，以兼容短期内尚未过期的 token

## 14. 部署安全

要求：

- 强制 HTTPS
- Web 根目录只暴露 `public/`
- 配置文件不放入可直接下载的路径
- 禁止目录浏览
- 服务器时间准确同步
- 数据库账号最小权限

## 15. 备份与恢复

### 15.1 必须备份

- 数据库
- 应用配置
- OIDC 私钥

### 15.2 恢复时注意

- 不得把测试环境私钥覆盖到生产
- 恢复后要检查 `issuer`、域名、HTTPS 证书是否一致

## 16. 上线前安全检查清单

- `PDO` 已关闭模拟预处理
- 所有表单有 CSRF Token
- Session 登录后会轮换
- 管理员密码哈希和卡密哈希已启用
- 私钥不在 Web 目录内
- `jwks.json` 可访问
- `redirect_uri` 白名单已写死
- `PKCE S256` 已强制
- Access Token 不写明文日志
- 管理后台已限流
- HTTPS 正常
- 安全响应头已开启

## 17. 残余风险

即使按本设计实现，仍需承认以下残余风险：

1. `PHP 7.3` EOL 风险无法通过应用代码彻底消除
2. `ChatGPT Business` 无 SCIM，成员管理仍有人为操作风险
3. 邮箱变更可能导致 OpenAI 侧出现账号关联问题
4. 管理员导出卡密后，卡密传播链路不在本系统控制范围内

这些都必须在上线说明中明确给业务方。
