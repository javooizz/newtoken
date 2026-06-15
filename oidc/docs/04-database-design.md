# 数据库设计文档

## 1. 设计目标

数据库设计遵循以下目标：

- 结构尽量少表，便于维护
- 关键数据可审计
- 不存明文卡密
- 可支撑 OIDC 基础流程
- 可支撑后台管理和问题排查

首版建议使用 6 张核心表。

## 2. 表清单

1. `admins`
2. `users`
3. `card_keys`
4. `auth_codes`
5. `access_tokens`
6. `audit_logs`

首版不单独建：

- `refresh_tokens`
- `oidc_clients`
- `password_resets`
- `scim_users`

## 3. admins 表

用途：后台管理员账号。

建议字段：

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| id | bigint unsigned pk | 主键 |
| username | varchar(64) unique | 管理员登录名 |
| email | varchar(190) unique | 管理员邮箱 |
| password_hash | varchar(255) | 管理员密码哈希 |
| role | varchar(32) | `owner` / `admin` |
| status | varchar(16) | `active` / `disabled` |
| last_login_at | datetime null | 最近登录时间 |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 更新时间 |

索引建议：

- `unique(username)`
- `unique(email)`
- `index(status)`

## 4. users 表

用途：卡密绑定后的用户账户。

建议字段：

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| id | bigint unsigned pk | 主键 |
| oidc_subject | varchar(64) unique | OIDC `sub` |
| email | varchar(190) unique | 员工邮箱 |
| email_domain | varchar(128) | 邮箱域名，便于审计和过滤 |
| full_name | varchar(190) | 显示名 |
| given_name | varchar(100) null | 名 |
| family_name | varchar(100) null | 姓 |
| password_hash | varchar(255) | 兼容保留字段，用户侧当前不依赖密码登录 |
| status | varchar(16) | `active` / `disabled` / `locked` |
| activated_by_card_id | bigint unsigned null | 绑定卡密 |
| activated_at | datetime null | 首次绑定时间 |
| last_login_at | datetime null | 最近登录时间 |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 更新时间 |

索引建议：

- `unique(oidc_subject)`
- `unique(email)`
- `index(email_domain)`
- `index(status)`

规则：

- `email` 必须和 OpenAI 预期登录邮箱一致
- `oidc_subject` 一经生成不得变更

## 5. card_keys 表

用途：保存卡密元数据。

建议字段：

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| id | bigint unsigned pk | 主键 |
| batch_no | varchar(64) | 批次号 |
| card_prefix | varchar(8) | 明文前缀展示用 |
| card_suffix | varchar(8) | 明文后缀展示用 |
| card_hash | char(64) unique | 卡密哈希，数据库只存它 |
| status | varchar(16) | `unused` / `used` / `revoked` / `expired` |
| expires_at | datetime null | 过期时间 |
| used_by_user_id | bigint unsigned null | 使用人 |
| used_at | datetime null | 使用时间 |
| exported_at | datetime null | 首次导出时间 |
| note | varchar(255) null | 批注 |
| created_by_admin_id | bigint unsigned | 创建人 |
| created_at | datetime | 创建时间 |
| updated_at | datetime | 更新时间 |

索引建议：

- `unique(card_hash)`
- `index(batch_no)`
- `index(status)`
- `index(expires_at)`
- `index(created_by_admin_id)`

说明：

- `card_prefix` 和 `card_suffix` 只用于后台识别，不可用于重新拼接恢复全部卡密
- 哈希建议使用 `hash_hmac('sha256', raw_card, APP_KEY)`

## 6. auth_codes 表

用途：保存 OIDC 授权码状态。

建议字段：

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| id | bigint unsigned pk | 主键 |
| user_id | bigint unsigned | 对应员工 |
| client_id | varchar(128) | OpenAI Client ID |
| code_hash | char(64) unique | 授权码哈希 |
| redirect_uri | varchar(500) | 回调地址 |
| scope | varchar(255) | 授权范围 |
| nonce | varchar(255) | OIDC nonce |
| code_challenge | varchar(255) | PKCE challenge |
| code_challenge_method | varchar(16) | 只允许 `S256` |
| expires_at | datetime | 过期时间 |
| used_at | datetime null | 使用时间 |
| ip_address | varchar(64) null | 发起 IP |
| user_agent_hash | char(64) null | UA 摘要 |
| created_at | datetime | 创建时间 |

索引建议：

- `unique(code_hash)`
- `index(user_id)`
- `index(client_id)`
- `index(expires_at)`

规则：

- 授权码只能使用一次
- 建议有效期 `60 秒` 到 `120 秒`

## 7. access_tokens 表

用途：保存 Access Token 状态。

建议字段：

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| id | bigint unsigned pk | 主键 |
| user_id | bigint unsigned | 对应员工 |
| client_id | varchar(128) | OpenAI Client ID |
| token_hash | char(64) unique | Access Token 哈希 |
| scope | varchar(255) | scope |
| expires_at | datetime | 过期时间 |
| revoked_at | datetime null | 撤销时间 |
| ip_address | varchar(64) null | 签发时 IP |
| user_agent_hash | char(64) null | UA 摘要 |
| created_at | datetime | 创建时间 |

索引建议：

- `unique(token_hash)`
- `index(user_id)`
- `index(client_id)`
- `index(expires_at)`
- `index(revoked_at)`

规则：

- 首版不做 `refresh_token`
- Access Token 建议短期有效，默认 `10 分钟`

## 8. audit_logs 表

用途：记录审计事件。

建议字段：

| 字段 | 类型建议 | 说明 |
| --- | --- | --- |
| id | bigint unsigned pk | 主键 |
| actor_type | varchar(16) | `admin` / `user` / `system` |
| actor_id | bigint unsigned null | 行为发起人 |
| action | varchar(64) | 行为类型 |
| target_type | varchar(32) null | 目标类型 |
| target_id | varchar(64) null | 目标 ID |
| details_json | text null | 细节 JSON |
| ip_address | varchar(64) null | IP |
| created_at | datetime | 记录时间 |

索引建议：

- `index(actor_type, actor_id)`
- `index(action)`
- `index(target_type, target_id)`
- `index(created_at)`

建议记录的 `action`：

- `admin_login_success`
- `admin_login_failed`
- `card_batch_created`
- `card_exported`
- `card_revoked`
- `user_activated`
- `card_login_success`
- `card_login_failed`
- `oidc_authorize_success`
- `oidc_authorize_failed`
- `oidc_token_issued`
- `password_reset_by_admin`
- `user_disabled`

## 9. 关系说明

- 一个 `admin` 可以创建多批卡密
- 一个 `card_key` 最终最多绑定一个 `user`
- 一个 `user` 会产生多个 `auth_code`
- 一个 `user` 会产生多个 `access_token`
- `audit_logs` 可关联管理员、员工、卡密、授权码等任意目标

## 10. 状态流转

### 10.1 卡密状态

`unused -> used`

`unused -> revoked`

`unused -> expired`

规则：

- `used` 不允许再返回 `unused`
- `revoked` 和 `expired` 都不能再激活

### 10.2 员工状态

`active -> disabled`

`active -> locked`

规则：

- `disabled` 用户不得参与 OIDC 登录
- `locked` 可用于登录失败次数过多后的暂时封锁

## 11. 哈希与敏感数据设计

### 11.1 卡密哈希

- 不保存明文卡密
- 仅保存 `card_hash`
- 明文只在生成导出瞬间出现在内存中

### 11.2 授权码与 Token 哈希

- 数据库仅保存 `hash_hmac` 后的摘要
- 即使数据库泄露，也不能直接拿来伪造 OIDC 登录

### 11.3 兼容字段说明

- 用户侧当前不使用账号密码登录
- `password_hash` 在 `users` 表中仅作兼容保留
- 管理员后台仍然使用密码登录
- 输入密码先叠加 `APP_PEPPER`

## 12. 数据保留建议

- `auth_codes`：可按过期时间定期清理
- `access_tokens`：保留最近 30 到 90 天审计数据
- `audit_logs`：建议至少保留 180 天
- `card_keys`：除非合规要求删除，否则建议长期保留审计记录

## 13. 清理策略

可通过计划任务定期执行：

1. 删除已过期且超过保留期的授权码
2. 删除已过期且超过保留期的 access token
3. 压缩旧审计日志

首版可先不引入复杂任务调度，仅在后台或 CLI 中提供清理脚本。
