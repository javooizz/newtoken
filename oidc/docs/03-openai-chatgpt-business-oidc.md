# OpenAI ChatGPT Business OIDC 接入文档

## 1. 目标

本项目要为 `ChatGPT Business` 提供可联调、可上线的 `OIDC Identity Provider` 能力。

OpenAI 在这个场景中的角色是：

- `OIDC Client`
- `Relying Party`

本系统在这个场景中的角色是：

- `OIDC Provider`
- `Authorization Server`
- `Identity Provider`

## 2. 基于 OpenAI 官方文档已确认的事实

已由用户提供文档确认：

1. `ChatGPT Business` 支持 `SAML` 和 `OIDC`
2. 本项目固定采用 `OIDC`
3. `ChatGPT Business` 的 SSO 是自助配置
4. 配置入口位于 `https://chatgpt.com/admin/identity`
5. 启用 SSO 前必须先完成至少一个域名验证
6. `Business` 版无 `SCIM`
7. `Business` 版 SSO 仅作用于 `ChatGPT`，不作用于 `platform.openai.com`
8. 配置向导中可以选择 `Custom OIDC`
9. OpenAI 官方建议先将 SSO 设置为 `Optional` 进行测试
10. 如果 SSO 返回的邮箱与已有 OpenAI 用户档案邮箱相同，OpenAI 会把登录关联到原账户，不会自动制造重复账户

## 3. 接入前提

接入 OpenAI 前，必须先满足以下条件：

### 3.1 OpenAI 工作区前提

- 已开通 `ChatGPT Business`
- 当前操作者具有管理员权限
- 已能访问 `https://chatgpt.com/admin/identity`
- 至少一个企业邮箱域名完成验证

### 3.2 我方系统前提

- 应用已部署在公网 HTTPS 域名下
- 已有可稳定访问的 `issuer`
- OIDC 端点已完成开发
- JWT 签名密钥已生成
- 管理员与单页卡密 SSO 登录流程已打通
- 至少一个测试卡密可以在 `/sso` 成功完成绑定或登录

### 3.3 企业管理前提

- 已明确哪些邮箱域名允许登录
- 已明确谁负责手工邀请员工进入 ChatGPT Business 工作区
- 已保留至少一个本地管理员应急入口

## 4. 重要范围限制

### 4.1 Business 版没有 SCIM

这意味着：

- 本系统不能自动把用户推送进 OpenAI 工作区
- 新用户仍需要管理员在 `ChatGPT Business` 中邀请，或使用该工作区已有的成员加入流程
- 账号停用也不能依靠 SCIM 自动回收

因此，首版的职责边界是：

- 我们负责身份认证
- OpenAI 工作区成员管理仍由管理员手工处理

### 4.2 Business 版不覆盖 API Platform

即使 `chatgpt.com` 登录完成，`platform.openai.com` 也不自动复用这个 Business 版 SSO 配置。

本项目首版不处理 API Platform。

## 5. 推荐 OIDC 模式

固定使用以下模式：

- `Authorization Code Flow`
- `PKCE S256`
- `RS256` 签名 `id_token`
- `openid profile email` 三个基础 scope

明确禁止：

- `Implicit Flow`
- `Password Grant`
- `plain` PKCE

## 6. 推荐开放的 OIDC 端点

系统必须提供以下公开端点：

- `https://sso.example.com/.well-known/openid-configuration`
- `https://sso.example.com/jwks.json`
- `https://sso.example.com/authorize`
- `https://sso.example.com/token`
- `https://sso.example.com/userinfo`

系统可额外提供：

- `https://sso.example.com/logout`

## 7. Discovery 文档设计

为了兼容 OpenAI 可能的两种配置方式，建议同时支持：

1. 通过 `Discovery URL` 自动发现
2. 手工逐项填写端点 URL

推荐 Discovery 文档核心字段：

```json
{
  "issuer": "https://sso.example.com",
  "authorization_endpoint": "https://sso.example.com/authorize",
  "token_endpoint": "https://sso.example.com/token",
  "userinfo_endpoint": "https://sso.example.com/userinfo",
  "jwks_uri": "https://sso.example.com/jwks.json",
  "response_types_supported": ["code"],
  "subject_types_supported": ["public"],
  "id_token_signing_alg_values_supported": ["RS256"],
  "scopes_supported": ["openid", "profile", "email"],
  "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
  "code_challenge_methods_supported": ["S256"],
  "claims_supported": [
    "sub",
    "iss",
    "aud",
    "exp",
    "iat",
    "auth_time",
    "nonce",
    "email",
    "email_verified",
    "name",
    "given_name",
    "family_name"
  ]
}
```

## 8. 我方建议向 OpenAI 提供的配置值

当 OpenAI 后台选择 `Custom OIDC` 后，建议准备以下值：

- `Issuer URL`：`https://sso.example.com`
- `Discovery URL`：`https://sso.example.com/.well-known/openid-configuration`
- `Authorization Endpoint`：`https://sso.example.com/authorize`
- `Token Endpoint`：`https://sso.example.com/token`
- `Userinfo Endpoint`：`https://sso.example.com/userinfo`
- `JWKS URL`：`https://sso.example.com/jwks.json`
- `Client ID`：由 OpenAI 创建后填写到我方配置
- `Client Secret`：由 OpenAI 创建后填写到我方配置
- `Scopes`：`openid profile email`

说明：

- 如果 OpenAI 只支持 Discovery 方式，则我们填 `Discovery URL`
- 如果 OpenAI 支持手工填写，则我们同步支持
- 代码实现阶段以 OpenAI 控制台的实际字段为准

## 9. 我方对 OpenAI Client 的约束

首版仅支持一个 OpenAI Client，配置为单租户单用途：

- 单个 `client_id`
- 单个 `client_secret`
- 单个或固定集合的 `redirect_uri`

建议将 `redirect_uri` 白名单写入配置文件，不开放后台随意编辑。

## 10. 需要返回的身份信息

### 10.1 必填

- `email`
- `sub`
- `iss`
- `aud`
- `exp`
- `iat`

### 10.2 推荐

- `email_verified`
- `name`
- `given_name`
- `family_name`
- `auth_time`
- `nonce`

### 10.3 属性映射原则

OpenAI 文档已明确：

- 邮箱是决定登录到哪个 OpenAI 账户的关键字段
- 姓名字段不是硬性必填，但建议提供
- 邮箱一旦变化，OpenAI 可能视为新的用户档案

因此，我方设计要求：

- 卡密绑定后邮箱默认不可随意自助修改
- 如确需改邮箱，必须走管理员流程
- 对于发生并购或更名的情况，要预估 OpenAI 侧账号迁移影响

## 11. 用户主体 `sub` 设计

`sub` 必须满足：

- 稳定
- 不可预测
- 不随显示名变化
- 不建议直接暴露数据库自增 ID

建议：

- 在 `users` 表中保存一个单独的 `oidc_subject`
- 该值在用户创建时一次生成，终身不变

## 12. 授权请求校验要求

`/authorize` 至少校验：

- `client_id`
- `redirect_uri`
- `response_type=code`
- `scope` 至少包含 `openid`
- `state`
- `nonce`
- `code_challenge`
- `code_challenge_method=S256`

必须拒绝：

- 缺少 `state`
- 缺少 `nonce`
- 缺少 `code_challenge`
- `code_challenge_method` 非 `S256`
- `redirect_uri` 不在白名单中

## 13. Token 端点要求

`/token` 必须：

- 校验 `grant_type=authorization_code`
- 校验授权码未过期、未使用、未被篡改
- 校验 `redirect_uri` 与授权阶段一致
- 校验 `client_id`、`client_secret`
- 校验 `code_verifier`
- 校验授权码对应的 PKCE 挑战

建议返回：

- `access_token`
- `id_token`
- `token_type=bearer`
- `expires_in`
- `scope`

首版不返回 `refresh_token`，以减小攻击面。

## 14. Userinfo 端点要求

`/userinfo` 用于返回用户信息，至少包含：

```json
{
  "sub": "usr_xxx",
  "email": "employee@example.com",
  "email_verified": true,
  "name": "Zhang San",
  "given_name": "San",
  "family_name": "Zhang"
}
```

## 15. OpenAI 后台配置步骤

### 15.1 域名验证

1. 进入 `https://chatgpt.com/admin/identity`
2. 在 `Identity & Provisioning` 中添加公司域名
3. 根据 OpenAI 提供的 TXT 值完成 DNS 验证
4. 等待状态变为 `Verified`

### 15.2 创建自定义 OIDC 连接

根据你提供的最新 OpenAI 文档，当前向导步骤应按下面理解：

1. `Provide an Identity Provider Name`
2. `Create an Application`
3. `Add Claims`
4. `Provide your OIDC Configuration`
5. `Configure Application Link`
6. `Test Single Sign-On`

其中最关键的是第 2 步和第 4 步。

### 15.3 Create an Application

OpenAI 最新文档要求你的应用：

- 支持 `authorization code grant type`
- 把 OpenAI 提供的 `Login redirect URI` 加入你的 OIDC 应用回调白名单

这意味着：

- OpenAI 会为当前连接生成一条唯一的 `Login redirect URI`
- 这条地址必须加入本系统的 `oidc_allowed_redirect_uris`
- 应通过安装页或后台设置页配置，不要硬编码进源码
- 如果你在 OpenAI 后台重置连接，新的回调地址可能会变化，需要同步更新白名单

### 15.4 Add Claims

建议至少保证以下 Claims 可被 OpenAI 读取：

- `email`
- `email_verified`
- `name`
- `given_name`
- `family_name`
- `sub`

对应到当前源码：

- `sub`：来自 `users.oidc_subject`
- `email`：来自 `users.email`
- `given_name`：来自 `users.given_name`
- `family_name`：来自 `users.family_name`

当前实现已经在以下两个地方返回这些 Claim：

1. `id_token`
2. `/userinfo`

并且已经做了兜底：

- 如果用户没有手工填写姓名，系统会自动用邮箱前缀生成显示名
- 如果 `family_name` 为空，会自动回退到 `given_name`

也就是说，Step 3 的要求在当前源码里已经处理，不需要你另外再做一个页面或新增一套配置界面。

### 15.5 Provide your OIDC Configuration

在 OpenAI 后台填写：

- `Issuer URL`
- `Discovery URL`
- 或手工填写 `Authorization Endpoint`、`Token Endpoint`、`Userinfo Endpoint`、`JWKS URL`

当前系统对应值：

- `Issuer URL`：`https://你的域名`
- `Discovery URL`：`https://你的域名/.well-known/openid-configuration`
- `Authorization Endpoint`：`https://你的域名/authorize`
- `Token Endpoint`：`https://你的域名/token`
- `Userinfo Endpoint`：`https://你的域名/userinfo`
- `JWKS URL`：`https://你的域名/jwks.json`

### 15.6 Configure Application Link

这一步是**可选项**，不是 OIDC 核心协议必需项。

OpenAI 这一步的意思是：

- OIDC 本身不支持传统的 `IdP initiated flow`
- 但 OpenAI 允许你在身份提供方的“应用门户”里放一个应用入口链接
- 用户点击这个链接后，可以直接跳到 OpenAI 的 SSO 登录入口

你拿到的内容通常会是：

- `Application Name`
- `Application login URL`

例如：

- `Application Name`：`ChatGPT`
- `Application login URL`：OpenAI 提供的一条 `https://chatgpt.com/auth/login?sso=true&connection=...` 链接

这一步是拿来做什么的：

1. 如果你的身份系统有“用户门户”或“应用列表页”
2. 你可以在里面放一个 `ChatGPT` 按钮
3. 按钮点击后跳到 OpenAI 提供的这条 `Application login URL`

对于当前这套源码：

- 当前没有实现一个“企业应用门户首页”
- 所以这一步**不是必须做**
- 不做也不影响 `ChatGPT Business` 通过 OIDC 正常登录

当前项目里你只需要保证：

- 用户可以从 `chatgpt.com` 正常发起登录
- OpenAI 可以跳到 `/authorize`
- 用户可以在 `/sso` 完成卡密登录

只有在你后续想做“统一应用入口页”时，才需要把这条 `Application login URL` 放进你自己的门户页面。

注意：

- 这条 `Application login URL` 由 OpenAI 当前连接生成
- 如果你在 OpenAI 后台重置 SSO 连接，里面的 `connection=...` 也可能会变
- 因此这条 URL 不要硬编码到源码里，最多只作为后台文档或手工配置项保存

### 15.7 Test Single Sign-On

联调时建议：

1. 使用一个隐身窗口测试用户通过 `/sso` 登录
2. 另一个普通窗口保留管理员登录态
3. 如果测试失败，优先回滚 SSO 设置
4. 测试通过后，再向更多用户开放

### 15.8 你这边必须同步的配置点

你当前这套系统里，和 OpenAI 最新 OIDC 向导直接对应的配置点有：

1. `allowed_email_domains`
2. `oidc_client_id`
3. `oidc_client_secret`
4. `oidc_allowed_redirect_uris`
5. `oidc_issuer`

其中最容易漏的是：

- `oidc_allowed_redirect_uris`

它必须包含 OpenAI 给你的那条真实回调地址，否则 `/authorize` 会因为 `redirect_uri` 不匹配而直接拒绝。

## 16. 联调测试用例

### 16.1 成功路径

1. OpenAI 输入公司邮箱
2. 跳转到本系统 `/sso`
3. 输入正确卡密、邮箱前缀和邮箱后缀
4. 成功返回 OpenAI
5. 进入 ChatGPT Business 工作区

### 16.2 失败路径

1. 错误卡密
2. 已禁用用户账号
3. 邮箱域名不允许
4. `redirect_uri` 不匹配
5. `code_verifier` 错误
6. 授权码重复使用
7. 过期授权码

## 17. 上线前检查清单

- 域名已验证
- HTTPS 正常
- Discovery 文档可访问
- JWKS 可访问
- OpenAI 工作区已有测试成员
- 至少一个测试卡密可在 `/sso` 成功绑定或登录
- 本地管理员应急账号可登录
- SSO 仍处于 `Optional`
- 审计日志正常记录
- 失败回滚方案已确认

## 18. 常见风险与处理

### 18.1 域名已被其他工作区验证

处理：

- 需由公司 IT 和 OpenAI 协调工作区归属
- 首版代码层面无法绕过该限制

### 18.2 邮箱不一致导致 OpenAI 新建档案

处理：

- 本系统必须强约束用户邮箱
- 邮箱变更由管理员审批后执行

### 18.3 SSO 错配锁死管理员

处理：

- 联调期间保持 `Optional`
- 保留本地管理员账号
- 使用双窗口测试

### 18.4 无法自动预配工作区席位

处理：

- 通过管理员手工邀请流程解决
- 文档中明确告知管理员这不是系统缺陷，而是 Business 版能力边界

## 19. 实施时必须再次核实的点

虽然 OIDC 路线已确认，但代码阶段仍需在 OpenAI 控制台核实：

1. `Custom OIDC` 页面是否支持 `Discovery URL`
2. `client_secret_basic` 还是 `client_secret_post` 为首选
3. 是否要求固定的回调地址格式
4. 是否会在 `id_token` 与 `userinfo` 之间偏向某一处取姓名字段
5. 是否对 `issuer` 或 `sub` 有特殊格式要求

这些都属于联调细节，不影响当前架构方向。
