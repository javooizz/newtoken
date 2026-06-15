# 多母号 OIDC 设计文档（卡密模式 · 二次开发 oidc/）

- 状态：待评审
- 日期：2026-06-16
- 范围：在现有 `oidc/` PHP 服务上二次开发，支持一套服务接入多个 OpenAI ChatGPT Business「team 母号」SSO。

---

## 0. 背景与目标

### 背景
业务为 OpenAI ChatGPT Business「team 母号」席位批发：买入多个 team 母号（每个母号是一个 OpenAI workspace，可容纳多个席位），通过 Custom OIDC 接入自建身份提供方（IdP），终端用户用**卡密 + 邮箱前缀**自助登录进入对应母号。

现有 `oidc/` 是一套自研 PHP OIDC 服务，已实现单母号的卡密登录闭环（OIDC 协议端点、卡密体系、admin 后台、安全机制）。历史上还试过 Authentik 双实例方案，现已放弃。

### 目标
1. 一套自研 PHP OIDC 服务，**单域名、单库**，同时给**多个** team 母号做 SSO。
2. 每个母号对应**独立的邮箱域名**（OpenAI 硬约束，详见第 10 节）。
3. **新增母号 0 部署**：后台/API 新建母号即可接入，不重新部署。
4. 母号管理同时支持 **admin 后台**和**开放 API**（对接 WebUI/sub2api 自动化开号）。
5. 保留现有**卡密发号**变现模式。

### 非目标（明确不做）
- 用户、卡密按母号**隔离**（全局共享，不隔离）。
- 迁移历史数据（全新部署，旧数据不要）。
- Authentik / 成熟 IdP 方案。
- 母号级独立统计报表、卡密绑定到特定母号（预留扩展位，本期不做，见第 13 节）。

---

## 1. 关键决策摘要

| 维度 | 决策 |
|---|---|
| 实现载体 | **二次开发**现有 `oidc/`（复用 OIDC 协议/卡密/后台/安全） |
| 认证方式 | 卡密 + 邮箱前缀自助绑定（沿用现有） |
| 多母号映射 | **每母号一个独立 client**，落在新表 `oidc_clients` |
| 用户 / 卡密 | **全局共享，不隔离** |
| 母号管理 | admin 后台 + 开放管理 API（Bearer api_key） |
| client_secret 存储 | `app_key` 派生密钥 **AES-256-GCM 加密存储，可解密回显** |
| OIDC issuer / discovery | **全局唯一一个**，所有母号共用 |
| 母号域名 | 每母号独立、唯一域名；子域名 + 独立顶级域名**混合**；DNS TXT 验证 |
| 部署 | 单域名、单 MySQL、全新安装，不迁旧数据 |

---

## 2. 架构总览

一套 PHP OIDC 服务部署在**单一域名**（如 `id.example.com`），对外暴露一组**全局唯一**的 OIDC 端点：`/.well-known/openid-configuration`、`/jwks.json`、`/authorize`、`/token`、`/userinfo`。所有母号共用同一个 `issuer`。

多母号通过新表 `oidc_clients` 区分：每母号一行，持有自己的 `client_id` / `client_secret` / 回调白名单 / 允许域名。用户与卡密是全局池，不挂母号。

### 两层域名（关键区分，勿混）

| | 数量 | 例子 | 说明 |
|---|---|---|---|
| **OIDC 服务域名**（issuer/discovery） | 永远 1 个 | `id.example.com` | 自定义，所有母号共用 |
| **母号邮箱域名**（用户 email 域名） | 每母号 ≥1 个，各不相同 | 母号A=`1bool.com`、母号B=`b.example.org` | OpenAI 要求独立的是这个，配在 `oidc_clients.allowed_domains` |

### 数据流（两个母号，独立域名，一套服务）

```
母号A 的 ChatGPT 登录
  → OpenAI 用母号A的 client_id 调 id.example.com/authorize（login_hint=alice@1bool.com）
  → 服务按 client_id 查 oidc_clients → 登录页锁定 1bool.com 域名
  → 用户输入卡密 + 前缀 alice → 绑定/校验 → 回 母号A 的 callback

母号B 的 ChatGPT 登录
  → OpenAI 用母号B的 client_id 调 同一个 /authorize（login_hint=bob@b.example.org）
  → 登录页锁定 b.example.org → 卡密绑定 → 回 母号B 的 callback
```

`iss` 全部相同、`aud` 为各自 `client_id`、callback 各自唯一，符合 OIDC「一个 IdP 多个 client」标准。

---

## 3. 数据模型

### 3.1 新增表 `oidc_clients`

```sql
CREATE TABLE IF NOT EXISTS oidc_clients (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    client_id VARCHAR(128) NOT NULL,            -- 分配给该母号、填到 OpenAI 的 Client ID（随机生成）
    client_secret_enc TEXT NOT NULL,            -- AES-256-GCM 加密后的 secret（base64(iv|tag|cipher)）
    name VARCHAR(190) NOT NULL,                 -- 母号备注名（如「母号A-1bool.com」）
    redirect_uris TEXT NOT NULL,                -- JSON 数组：OpenAI 回调白名单
    allowed_domains TEXT NOT NULL,              -- JSON 数组：该母号允许的邮箱域名（1 或多个）
    status VARCHAR(16) NOT NULL DEFAULT 'active', -- active / disabled
    note VARCHAR(255) NULL,
    created_by_admin_id BIGINT UNSIGNED NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    UNIQUE KEY uq_oidc_clients_client_id (client_id),
    KEY idx_oidc_clients_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

### 3.2 `users` 表改动
- 新增 `origin_client_id VARCHAR(128) NULL`：记录该用户**首次激活**来自哪个母号（取自 authorize 的 client_id），**仅作统计用途，不做任何约束**。
- 其余不变：`email` 仍全局 `UNIQUE`，`oidc_subject` 全局 `UNIQUE`。

### 3.3 沿用不变的表
- `card_keys`：全局卡密池，**不挂母号**。生成/绑定/吊销/补发逻辑不变。
- `auth_codes` / `access_tokens`：已有 `client_id` 字段，保留；token 端点据此做归属校验。
- `admins` / `audit_logs`：不变。

---

## 4. OIDC 端点行为

| 端点 | 改动 | 说明 |
|---|---|---|
| `/.well-known/openid-configuration` | 不变 | 全局一份，`issuer` 取自配置，所有母号共用 |
| `/jwks.json` | 不变 | 全局 RSA 公钥 |
| `/authorize` | **改造** | 不再比对单个 config client_id；改为**按请求 `client_id` 查 `oidc_clients`**：① 母号存在且 `status=active`；② `redirect_uri ∈ 该母号 redirect_uris`；③ 把该母号 `allowed_domains` 一并存入 pending 会话，供登录页使用 |
| `/token` | **改造** | 按请求 `client_id` 查 `oidc_clients`，**解密 `client_secret_enc` 后比对**；`auth_codes.client_id` 必须等于请求 client_id；其余（PKCE、code 过期/复用）不变 |
| `/userinfo` | 不变 | 按 access_token 找 user，返回 `sub/email/email_verified/name/given_name/family_name` |
| `/sso` 登录页 | **改造** | 域名后缀来源从「全局 config」改为「pending 的 `allowed_domains`」；有 `login_hint` 时锁定该邮箱 |

### id_token 声明
保持现有签发：`iss`（全局 issuer）、`sub`、`aud`（= 该母号 client_id）、`exp/iat/auth_time/nonce`、`email`、`email_verified=true`、`name/given_name/family_name`。满足 OpenAI 必需 claims（见第 10 节）。

---

## 5. 卡密与域名校验

- **卡密流程完全不变**：全局池，生成/导出/绑定/吊销/补发逻辑沿用。一张卡仍是「首次绑定一个邮箱、之后该卡只认该邮箱」。
- **唯一变化是域名校验来源**：
  - 从 OpenAI 发起（有 pending）→ 允许域名 = **当前母号 `allowed_domains`**。
  - 直接访问 `/sso`（无 pending 上下文）→ 回退到**所有 `active` 母号 `allowed_domains` 的并集**。
  - 激活/登录时校验：用户邮箱域名必须 ∈ 上述允许集合，否则拒绝。
- `origin_client_id` 在用户**首次激活**时写入（取 pending client_id）。

> 说明：因每母号独立域名 + OpenAI 侧域名归属（第 10 节），「母号A的卡被拿去登录母号B」在 OpenAI 路由层即被拦截，OIDC 层无需额外隔离即满足「不隔离但不串号」。

---

## 6. 母号管理 API

统一 `Bearer api_key` 鉴权（沿用现有机制）。

| 方法 | 路径 | 用途 |
|---|---|---|
| `POST` | `/api/clients` | 新建母号。入参 `name`、`redirect_uris[]`、`allowed_domains[]`、`note?`。生成随机 `client_id` + `client_secret`，加密入库；返回 `client_id`、`client_secret`（明文）、`openai_config`（issuer/discovery/authorize/token/userinfo/jwks/scopes 复制块） |
| `GET` | `/api/clients` | 母号列表（默认**不含** secret 明文） |
| `GET` | `/api/clients/{id}` | 母号详情；带 `?reveal=1` 时解密返回 `client_secret` 明文 |
| `PATCH` | `/api/clients/{id}` | 改 `name` / `redirect_uris` / `allowed_domains` / `status`；可选 `rotate_secret=1` 重新生成并返回新 secret |

保留现有 `/api/status`、`/api/cards/generate`、`/api/cards/lookup`。

---

## 7. admin 后台

新增「母号管理」页：
- **列表**：母号名、client_id、域名、状态、创建时间；操作=查看/编辑/停用/启用/轮换 secret。
- **新建**：表单填 `name`、`redirect_uris`（多行，每行一个）、`allowed_domains`（多行）。提交后展示 `client_id` + `client_secret`（明文）+ **「OpenAI 配置复制块」**（一键复制 issuer/discovery/各端点/scopes）。
- **详情**：可点击「显示 secret」解密回显（决策 A）；可编辑域名/回调；可停用/启用/轮换 secret。

现有「卡密生成/删除/补发」「卡密查询」「用户列表」「审计日志」「系统设置」页保留。系统设置中**移除写死的单 client 字段**（`oidc_client_id`/`oidc_client_secret`/`oidc_redirect_uris`），改由母号管理接管；同时**移除 `allowed_email_domains` 全局项**，统一以母号 `allowed_domains` 为准，无母号上下文时按第 5 节回退到所有 `active` 母号域名并集。

---

## 8. 安全设计

- **client_secret 加密**：以 `app_key` 派生 32 字节密钥，`AES-256-GCM`（`openssl_encrypt`）加密；存储 `base64(iv | tag | ciphertext)`。token 端点解密后用 `hash_equals` 比对。库被脱时 secret 不以明文暴露。
- **母号停用**：`status=disabled` 的母号，`/authorize` 与 `/token` 一律拒绝。
- 沿用现有：RSA(RS256) id_token 签名、CSRF、限流（登录/管理）、审计日志、可选 PKCE(S256)、session 安全。
- 管理 API 仅 `Bearer api_key`；`reveal=1` / `rotate_secret` 等敏感操作写审计日志。

---

## 9. 域名供给与验证策略

- 每母号绑定 **1 个或多个独立、唯一**的已验证域名；**同一域名不得跨母号复用**（OpenAI 硬约束）。
- 域名来源**混合**：
  - **子域名切分**：一个主域名 `example.com` 切 `m1.example.com` / `m2.example.com`…，各自加 DNS TXT。买一个域名近乎无限母号，边际成本极低。
  - **独立顶级域名**：每母号一个独立域名。
  - 两类都可加进任意母号的 `allowed_domains`（JSON 数组，天然支持混合与多个）。
- 邮箱**无需真实收件**：OpenAI 在 Custom OIDC 下只用 email 值做账号匹配，虚拟前缀即可（见第 10 节）。

### 新增母号 SOP（定版）
1. OpenAI `admin.openai.com/identity` 为该母号验证域名（加 DNS TXT，子域名需各自单独记录）。
2. 本服务后台/API「新建母号」，生成专属 `client_id` / `client_secret`。
3. OpenAI → Set up SSO → Custom OIDC，填本服务 `issuer` / `discovery` + 该母号 `client_id` / `client_secret`。
4. 把 OpenAI 给的 callback URL 填进该母号 `redirect_uris`，把域名填进 `allowed_domains`。
5. 建议先用 OpenAI **测试沙箱**验证连接 → 生产保持 SSO=Optional、开两个浏览器窗口防锁死 → 发对应域名卡密。

---

## 10. OpenAI 官方约束（已核实）

**官方原文确认**（已抓取 help.openai.com 正文）：
- 支持 **Custom OIDC**（Business/Enterprise 向导可选）。
- **一个母号可挂多个已验证邮箱域名**（FAQ：「more than one verified email domain per workspace? Yes」）→ 子域名 + 独立顶级域名混合挂同一母号可行。
- 域名验证 = **DNS TXT**，入口 `admin.openai.com/identity`。
- **同一域名只能被一个 org 验证**（「once one organization executes the domain verification, no other organizations can verify the same domain」）→ 每母号必须独立域名。
- **邮箱无需真实收件**：email 仅用于匹配既有 profile，否则新建账号（「links the sign-in to the existing profile … A new account is spun up only if the SSO response supplies a different email」）。
- **必需 claims**：`sub / email / given_name / family_name`（`email_verified` 非必需，本服务照发无害）。
- 提供**测试沙箱**，可在不影响生产的前提下验证配置。
- 设置期保持 **SSO=Optional + 双窗口**防锁死；reset SSO 连接会改变 URL，需回本服务同步。

**二手提炼**（搜索摘要，未逐字抓到官方原文，但与机制一致且实践印证）：
- 子域名需各自单独 TXT；子域名被 CNAME 占用则无法验证。
- 每 org 最多 99 个验证域名；验证有约 7 天完成期。
- Business 新 workspace 需先完成 $1 promo 付款才能开 SSO。
- ChatGPT 与 API Platform 共享域名验证；开 SSO 影响同域名下 API Platform 密码登录。

**对架构的结论**：「单 issuer + 每母号独立 client_id + 每母号独立域名」与 OpenAI 完全兼容，且是其约束下的标准解。官方未明文背书「一个自建 IdP 服务多 workspace」（非标准批发玩法），但也无任何禁止；唯一硬约束「同域名跨 org」被「每母号独立域名」规避。

来源：
- https://help.openai.com/en/articles/11489188-sso-for-chatgpt-business-faq
- https://help.openai.com/en/articles/9534785-configuring-sso
- https://help.openai.com/en/articles/8871611-domain-verification

---

## 11. 二次开发边界（受影响文件）

| 类别 | 文件 / 内容 |
|---|---|
| **复用（基本不动）** | OIDC 协议（`app/oidc.php` 的 discovery/jwks/id_token 签发/PKCE）、卡密体系（`app/cards.php`）、admin 框架（`app/admin.php` 大部）、`app/security.php`/`app/session.php`/`app/http.php`/`app/db.php`、RSA 密钥、`cli/*` |
| **改造** | `app/oidc.php`：`app_oidc_validate_authorize_request` / `app_oidc_client_authenticated` / `app_oidc_exchange_code` 改为查 `oidc_clients` 表 + 解密 secret；`public/index.php`：`/authorize`、`/sso` 域名来源；`app/users.php`：域名校验取自 client + 写 `origin_client_id`；安装/设置表单移除单 client 字段 |
| **新增** | `app/clients.php`（母号 CRUD + secret 加解密 + 校验 helper）、`/api/clients` 路由（`app/api.php`）、admin 母号管理页（`app/admin.php` + `app/views.php`）、`sql/schema.sql` 加 `oidc_clients` 表与 `users.origin_client_id` |

---

## 12. 部署

- 环境：PHP 7.4+、MySQL 5.7+，扩展 `pdo_mysql` / `openssl`。
- 形态：单域名（issuer）、单 MySQL、宝塔站点指向 `oidc/public`。
- 全新安装：走安装向导建库导表、生成 `app_key`/`app_pepper`/`api_key`、生成 RSA 密钥、建管理员；**安装向导不再要求填单 client**，装好后在「母号管理」新建第一个母号。
- 不迁移旧数据。

---

## 13. YAGNI 与未来扩展

本期不做（预留扩展位）：
- 用户/卡密按母号隔离。
- 卡密绑定到特定母号（未来可给 `card_keys` 加 `client_id`）。
- 母号级独立统计报表（`origin_client_id` 已预留数据）。
- SCIM / 自动 provisioning。

---

## 14. 测试策略

关键测试点：
1. **多 client 串扰**：母号A、母号B 各自 `/authorize`→`/token` 走通，A 的 code 不能用 B 的 client_id 兑换。
2. **回调白名单**：非该母号 `redirect_uris` 内的 `redirect_uri` 被拒。
3. **域名锁定**：从母号A进入时登录页只接受 A 的域名；他域名邮箱被拒。
4. **secret 加解密**：加密入库→解密比对往返一致；`rotate_secret` 后旧 secret 失效。
5. **母号停用**：`disabled` 母号 `/authorize`、`/token` 均拒。
6. **卡密**：全局唯一 email、绑定与复用规则不变。
7. **管理 API**：CRUD + `Bearer api_key` 鉴权 + `reveal`/`rotate` 审计。
8. **discovery/jwks**：全局一份，`iss` 与签名校验通过。
