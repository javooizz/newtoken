# 多母号 OIDC 设计文档（卡密模式 · 二次开发 oidc/）

- 状态：待评审（已纳入第一轮设计审查修订）
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
- 卡密**绑定**到特定母号（本期不做，仅采纳轻量加固，见第 5 / 13 节）。
- 迁移历史数据（全新部署，旧数据不要）。
- Authentik / 成熟 IdP 方案。
- API Platform 接入（Business 不覆盖，见第 10 节）。

---

## 1. 关键决策摘要

| 维度 | 决策 |
|---|---|
| 实现载体 | **二次开发**现有 `oidc/`（复用 OIDC 协议/卡密/后台/安全） |
| 认证方式 | 卡密 + 邮箱前缀自助绑定（沿用现有） |
| 多母号映射 | **每母号一个独立 client**，落在新表 `oidc_clients` |
| 用户 / 卡密 | **全局共享，不隔离** |
| 卡密首次激活 | **必须有 pending client 上下文**（从 OpenAI 进来）；直接 `/sso` 仅允许已绑定卡登录（审查档 2） |
| 母号域名 | 独立表 `oidc_client_domains`，归一化 + **全局唯一索引**；子域名 + 独立顶级域名混合 |
| 母号管理鉴权 | **拆分** `cards_api_key`（发卡）与 `clients_admin_api_key`（母号管理） |
| client_secret 存储 | `app_key` 派生密钥 AES-256-GCM 加密；可解密回显，但**默认禁用 reveal**、需高权限 key + 审计 |
| OIDC issuer / discovery | **全局唯一一个**，所有母号共用 |
| 部署 | 单域名、单 MySQL、全新安装，不迁旧数据 |

---

## 2. 架构总览

一套 PHP OIDC 服务部署在**单一域名**（如 `id.example.com`），对外暴露一组**全局唯一**的 OIDC 端点：`/.well-known/openid-configuration`、`/jwks.json`、`/authorize`、`/token`、`/userinfo`。所有母号共用同一个 `issuer`。

多母号通过新表 `oidc_clients` 区分：每母号一行，持有自己的 `client_id` / `client_secret` / 回调白名单；其**允许域名**落在独立表 `oidc_client_domains`（带全局唯一索引）。用户与卡密是全局池，不挂母号。

### 两层域名（关键区分，勿混）

| | 数量 | 例子 | 说明 |
|---|---|---|---|
| **OIDC 服务域名**（issuer/discovery） | 永远 1 个 | `id.example.com` | 自定义，所有母号共用 |
| **母号邮箱域名**（用户 email 域名） | 每母号 ≥1 个，各不相同 | 母号A=`1bool.com`、母号B=`b.example.org` | OpenAI 要求独立的是这个，落在 `oidc_client_domains` |

### 数据流（两个母号，独立域名，一套服务）

```
母号A 的 ChatGPT 登录
  → OpenAI 用母号A的 client_id 调 id.example.com/authorize（login_hint=alice@1bool.com）
  → 服务按 client_id 查 oidc_clients + oidc_client_domains → 登录页锁定 1bool.com 域名
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
    status VARCHAR(16) NOT NULL DEFAULT 'active', -- active / disabled
    note VARCHAR(255) NULL,
    created_by_admin_id BIGINT UNSIGNED NULL,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    UNIQUE KEY uq_oidc_clients_client_id (client_id),
    KEY idx_oidc_clients_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

### 3.2 新增表 `oidc_client_domains`（审查第 3 条）

把母号允许域名从 JSON 字段提升为独立表，用唯一索引在**数据层强制**「同一域名不跨母号」。

```sql
CREATE TABLE IF NOT EXISTS oidc_client_domains (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    client_id VARCHAR(128) NOT NULL,            -- 关联 oidc_clients.client_id
    domain_normalized VARCHAR(255) NOT NULL,    -- 归一化域名（见下）
    domain_raw VARCHAR(255) NOT NULL,           -- 原始输入，仅展示用
    created_at DATETIME NOT NULL,
    UNIQUE KEY uq_client_domains_norm (domain_normalized),  -- 全局唯一：强制同域名不跨母号
    KEY idx_client_domains_client (client_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

**域名归一化规则**（落库与校验前统一执行）：`trim` → 转小写 → 去末尾点 `.` → IDN 转 punycode（`idn_to_ascii`，失败则拒绝）。校验登录邮箱时，对邮箱域名做同样归一化后再比对。

### 3.3 `users` 表改动
- 新增 `origin_client_id VARCHAR(128) NULL`：记录该用户**首次激活**来自哪个母号，**仅作统计用途，不做约束**。
- 其余不变：`email` 全局 `UNIQUE`，`oidc_subject` 全局 `UNIQUE`。

### 3.4 沿用不变的表
- `card_keys`：全局卡密池，**不挂母号**（本期不做卡-母号绑定，见第 13 节）。
- `auth_codes` / `access_tokens`：已有 `client_id` 字段，保留；token 端点据此做归属校验。
- `admins` / `audit_logs`：不变。

---

## 4. OIDC 端点行为

| 端点 | 改动 | 说明 |
|---|---|---|
| `/.well-known/openid-configuration` | 不变 | 全局一份，`issuer` 取自配置，所有母号共用 |
| `/jwks.json` | 不变 | 全局 RSA 公钥 |
| `/authorize` | **改造** | 按请求 `client_id` 查 `oidc_clients`：① 母号存在且 `status=active`；② `redirect_uri ∈ 该母号 redirect_uris`；③ 查 `oidc_client_domains` 取该母号域名集合，连同 `client_id` 存入 pending 会话 |
| `/token` | **改造** | 按请求 `client_id` 查 `oidc_clients`，**解密 `client_secret_enc` 后比对**；`auth_codes.client_id` 必须等于请求 client_id；其余（PKCE、code 过期/复用）不变 |
| `/userinfo` | 不变 | 按 access_token 找 user，返回 `sub/email/email_verified/name/given_name/family_name` |
| `/sso` 登录页 | **改造** | 见第 5 节：域名来源为 pending 的母号域名集合；**首次激活必须有 pending**，否则仅允许已绑定卡登录 |

### id_token 声明
保持现有签发：`iss`（全局 issuer）、`sub`、`aud`（= 该母号 client_id）、`exp/iat/auth_time/nonce`、`email`、`email_verified=true`、`name/given_name/family_name`。满足 OpenAI 必需 claims（见第 10 节）。

---

## 5. 卡密与域名校验（已按审查档 2 加固）

卡密体系（生成/导出/吊销/补发）逻辑不变，仍为全局池。登录行为按是否有 pending client 上下文分两种：

### 5.1 从 OpenAI 发起（有 pending）
- 允许域名 = 当前母号在 `oidc_client_domains` 的域名集合。
- 用户输入卡密 + 邮箱前缀，邮箱域名必须 ∈ 该集合。
- 卡未绑定 → **首次激活**：建 user（`origin_client_id` = pending client_id），绑卡。
- 卡已绑定 → 校验输入邮箱 == 绑定邮箱 → 登录。

### 5.2 直接访问 `/sso`（无 pending）——审查第 1 条修复
- **不允许首次激活**。卡未绑定时拒绝，提示「请从 ChatGPT 发起登录以完成首次绑定」。
- 仅允许**已绑定卡登录**：按卡找到绑定 user，校验输入邮箱 == `user.email` → 登录。此路径不依赖域名并集（不再需要「所有 active 母号域名并集」）。登录页此时邮箱后缀改为**自由输入**，不展示母号域名清单，避免向匿名访问者暴露已接入域名。

### 5.3 修正与残余风险（删除原错误论断）
- **删除**原第 5 节「母号A的卡被拿去登录母号B 在 OpenAI 路由层即被拦截 …… 无需额外隔离即满足不串号」——该论断过强且错误。
- 档 2 堵住了「直接 `/sso` 把任意卡绑到任意已接入域名」的旁路。
- **残余风险（接受）**：若终端用户已知**多个**母号的 ChatGPT 入口，仍可能从母号B发起、把本应用于母号A的未绑定卡绑到母号B域名。完全锁死需「卡绑母号」（档 3），本期不做（YAGNI，见第 13 节）；卡-母号对应靠运营约定（按域名发对应卡）。

---

## 6. 母号管理 API（已按审查第 2 条拆分鉴权）

两套独立 Bearer key：

- **`cards_api_key`**（沿用现有用途）：`/api/status`、`/api/cards/generate`、`/api/cards/lookup`。供 WebUI 发卡/查询。
- **`clients_admin_api_key`**（新增，高权限）：母号管理全部接口。

| 方法 | 路径 | 鉴权 | 用途 |
|---|---|---|---|
| `POST` | `/api/clients` | clients_admin | 新建母号。入参 `name`、`redirect_uris[]`、`allowed_domains[]`、`note?`。生成随机 `client_id` + `client_secret`，加密入库；域名归一化后写 `oidc_client_domains`（命中唯一索引冲突即报错并指出占用母号）。返回 `client_id`、`client_secret`（明文，仅本次）、`openai_config` 复制块 |
| `GET` | `/api/clients[/{id}]` | clients_admin | 母号列表/详情（**默认不含 secret 明文**） |
| `GET` | `/api/clients/{id}?reveal=1` | clients_admin | 解密返回 `client_secret`；**默认禁用**，需配置显式开启；写审计 |
| `PATCH` | `/api/clients/{id}` | clients_admin | 改 `name` / `redirect_uris` / 域名 / `status`；可选 `rotate_secret=1`（写审计） |

- 敏感接口（`reveal` / `rotate_secret`）支持**可选 IP allowlist**；命中失败一律拒绝并审计。
- `clients_admin_api_key` 未配置时，母号管理 API 整体关闭（仅后台可用）。

---

## 7. admin 后台

新增「母号管理」页：
- **列表**：母号名、client_id、域名、状态、创建时间；操作=查看/编辑/停用/启用/轮换 secret。
- **新建**：表单填 `name`、`redirect_uris`（多行）、允许域名（多行）。提交后展示 `client_id` + `client_secret`（明文，仅本次）+「OpenAI 配置复制块」。域名写入即做归一化与唯一性校验，冲突给出明确提示。
- **详情**：`client_secret` 默认隐藏，点击「显示」需二次确认并写审计（决策 A + 审查第 2 条）；可编辑域名/回调；可停用/启用/轮换 secret。

现有「卡密生成/删除/补发」「卡密查询」「用户列表」「审计日志」「系统设置」页保留。系统设置中**移除写死的单 client 字段**（`oidc_client_id`/`oidc_client_secret`/`oidc_redirect_uris`）与全局 `allowed_email_domains`，统一由母号管理 + `oidc_client_domains` 接管。

---

## 8. 安全设计

- **client_secret 加密**：以 `app_key` 派生 32 字节密钥，`AES-256-GCM`（`openssl_encrypt`），存储 `base64(iv | tag | ciphertext)`。token 端点解密后比对。
- **鉴权分权（审查第 2 条）**：`cards_api_key` 与 `clients_admin_api_key` 分离；`reveal` 默认禁用、`reveal`/`rotate_secret` 强制审计、敏感接口可选 IP allowlist。最小权限：WebUI 只持 `cards_api_key`，泄露也读不到/改不了母号 secret。
- **域名唯一性（审查第 3 条）**：`oidc_client_domains.domain_normalized` 全局唯一索引，数据层兜底防跨母号重复。
- **首次激活护栏（审查第 1 条）**：首次绑卡必须经由 `/authorize` 的 pending client 上下文；直接 `/sso` 不得首次激活。
- **母号停用**：`status=disabled` 的母号，`/authorize` 与 `/token` 一律拒绝。
- 沿用现有：RSA(RS256) id_token 签名、CSRF、限流、审计、可选 PKCE(S256)、session 安全。

---

## 9. 域名供给与验证策略

- 每母号绑定 **1 个或多个独立、唯一**的已验证域名；**同一域名不得跨母号复用**（OpenAI 硬约束 + `oidc_client_domains` 唯一索引双重保证）。
- 来源**混合**：子域名切分（一主域名切 `m1.` / `m2.`…各自 TXT）+ 独立顶级域名，都可加进任意母号。
- 邮箱**无需真实收件**：OpenAI 在 Custom OIDC 下只用 email 值做账号匹配，虚拟前缀即可（见第 10 节）。

### 新增母号 SOP（按审查第 4 条修正顺序）
1. OpenAI `admin.openai.com/identity` 为该母号验证域名（加 DNS TXT，子域名需各自单独记录）。
2. 本服务后台/API「新建母号」，生成 `client_id` / `client_secret`，**`redirect_uris` 可先留空/草稿**。
3. OpenAI → Set up SSO → Custom OIDC，填本服务 `issuer`/`discovery` + 该母号 `client_id`/`client_secret`；OpenAI 生成**唯一 Login redirect URI（callback）**。
4. 把该 callback **回填**到本服务该母号 `redirect_uris`，并把域名写入该母号允许域名。
5. 用 OpenAI **测试沙箱**验证连接 → 生产保持 SSO=Optional、开两窗口防锁死 → 发对应域名卡密。

> 依据 `oidc/docs/03-openai-chatgpt-business-oidc.md:310-317`：OpenAI 先生成唯一 redirect URI，再要求加入我方白名单——故必须「先建 client（草稿 redirect）→ 拿 callback → 回填」。

---

## 10. OpenAI 官方约束（已核实）

**官方原文确认**（已抓取 help.openai.com 正文）：
- 支持 **Custom OIDC**（Business/Enterprise 向导可选）。
- **一个母号可挂多个已验证邮箱域名**（FAQ：「more than one verified email domain per workspace? Yes」）→ 子域名 + 独立顶级域名混合挂同一母号可行。
- 域名验证 = **DNS TXT**，入口 `admin.openai.com/identity`。
- **同一域名只能被一个 org 验证**（「once one organization executes the domain verification, no other organizations can verify the same domain」）→ 每母号必须独立域名。
- **邮箱无需真实收件**：email 仅用于匹配既有 profile，否则新建账号。
- **必需 claims**：`sub / email / given_name / family_name`（`email_verified` 非必需，本服务照发无害）。
- 提供**测试沙箱**，可在不影响生产前提下验证配置。
- 设置期保持 **SSO=Optional + 双窗口**防锁死；reset SSO 连接会改变 URL，需回本服务同步。

**二手提炼**（搜索摘要，未逐字抓到官方原文，与机制一致 + 实践印证）：
- 子域名需各自单独 TXT；子域名被 CNAME 占用则无法验证。
- 每 org 最多 99 个验证域名；验证有约 7 天完成期。
- Business 新 workspace 需先完成 $1 promo 付款才能开 SSO。

**需再次核实、不作为架构依据（审查第 5 条）**：
- 「开 SSO 影响同域名 API Platform 密码登录」属 **Enterprise**（org 级共享 SSO）场景。本项目是 **Business**，仓库文档 `oidc/docs/03-...:28、74-78` 明确 **Business SSO 不作用于 `platform.openai.com`**。故本设计**不**把该共享行为作为依据，API Platform 不在范围内。

**对架构的结论**：「单 issuer + 每母号独立 client_id + 每母号独立域名」与 OpenAI 完全兼容，是其约束下的标准解。官方唯一硬约束「同域名跨 org」被「每母号独立域名 + 唯一索引」规避。

来源：
- https://help.openai.com/en/articles/11489188-sso-for-chatgpt-business-faq
- https://help.openai.com/en/articles/9534785-configuring-sso
- https://help.openai.com/en/articles/8871611-domain-verification

---

## 11. 二次开发边界（受影响文件）

| 类别 | 文件 / 内容 |
|---|---|
| **复用（基本不动）** | OIDC 协议（`app/oidc.php` 的 discovery/jwks/id_token 签发/PKCE）、卡密体系（`app/cards.php`）、admin 框架（`app/admin.php` 大部）、`app/security.php`/`app/session.php`/`app/http.php`/`app/db.php`、RSA 密钥、`cli/*` |
| **改造** | `app/oidc.php`：authorize/token client 校验改查 `oidc_clients` + 解密 secret；`app/api.php`：拆 `cards_api_key`/`clients_admin_api_key`、加 `/api/clients`；`public/index.php`：`/authorize` 注入 pending 域名集合、`/sso` 首次激活需 pending；`app/users.php`：域名校验取自母号域名表 + 写 `origin_client_id`；安装/设置表单移除单 client 与全局域名字段 |
| **新增** | `app/clients.php`（母号 CRUD + secret 加解密 + 域名归一化/唯一性校验 + reveal/rotate 审计）、admin 母号管理页（`app/admin.php` + `app/views.php`）、`sql/schema.sql` 加 `oidc_clients`、`oidc_client_domains`、`users.origin_client_id` |

---

## 12. 部署

- 环境：PHP 7.4+、MySQL 5.7+，扩展 `pdo_mysql` / `openssl` / `intl`（`idn_to_ascii` 归一化需要）。
- 形态：单域名（issuer）、单 MySQL，宝塔站点指向 `oidc/public`。
- 配置新增项：`cards_api_key`、`clients_admin_api_key`、可选 `clients_admin_ip_allowlist`、`clients_secret_reveal_enabled`（默认 false）。
- 全新安装：向导建库导表、生成 `app_key`/`app_pepper`/两个 api_key、生成 RSA 密钥、建管理员；**安装向导不再要求填单 client**，装好后在「母号管理」新建第一个母号。
- 不迁移旧数据。

---

## 13. YAGNI 与未来扩展

本期不做（预留扩展位）：
- 用户/卡密按母号隔离。
- **卡密绑定到特定母号（档 3）**：已采纳轻量加固（档 2：首次激活需 pending），完全锁死串卡留待未来（给 `card_keys` 加 `client_id`）。残余风险见第 5.3 节。
- 母号级独立统计报表（`origin_client_id` 已预留数据）。
- SCIM / 自动 provisioning（Business 无 SCIM）。
- API Platform 接入。

---

## 14. 测试策略

关键测试点：
1. **多 client 串扰**：母号A、母号B 各自 `/authorize`→`/token` 走通，A 的 code 不能用 B 的 client_id 兑换。
2. **回调白名单**：非该母号 `redirect_uris` 内的 `redirect_uri` 被拒。
3. **域名锁定**：从母号A进入时登录页只接受 A 的域名；他域名邮箱被拒。
4. **首次激活护栏（档 2）**：直接 `/sso` + 未绑定卡 → 拒绝首次激活；直接 `/sso` + 已绑定卡 + 正确邮箱 → 登录成功。
5. **域名唯一性（审查第 3 条）**：同一域名插入第二个母号 → 唯一索引拒绝；`EXAMPLE.com` / `example.com.` / ` example.com ` 归一化后视为同一。
6. **secret 加解密**：加密入库→解密比对往返一致；`rotate_secret` 后旧 secret 失效。
7. **鉴权分权（审查第 2 条）**：`cards_api_key` 不能调用 `/api/clients`；`reveal` 默认禁用时被拒；`reveal`/`rotate` 命中 IP allowlist 外被拒；敏感操作均写审计。
8. **母号停用**：`disabled` 母号 `/authorize`、`/token` 均拒。
9. **discovery/jwks**：全局一份，`iss` 与签名校验通过。

---

## 15. 修订记录

- **2026-06-16 v2（第一轮设计审查）**：
  - 审查 1（高）：删除「OpenAI 路由层拦截保证不串号」错误论断；采纳档 2——首次激活必须有 pending client 上下文，直接 `/sso` 仅登录已绑定卡；残余风险显式记录。
  - 审查 2（中高）：拆分 `cards_api_key` / `clients_admin_api_key`；`reveal` 默认禁用 + 敏感操作审计 + 可选 IP allowlist。
  - 审查 3（中）：域名从 JSON 改为独立表 `oidc_client_domains`，归一化 + 全局唯一索引。
  - 审查 4（中）：新增母号 SOP 改为「先建 client（草稿 redirect）→ OpenAI 拿 callback → 回填」。
  - 审查 5（低/中）：API Platform 影响降级为 Enterprise 专属、对 Business 不适用，移出架构依据。
- **2026-06-16 v1**：初版设计。
