# GPT Team OIDC 项目文档

本目录用于沉淀 `ChatGPT Business` 专用单点登录系统的首版设计文档。

项目目标：

- 使用 `PHP 7.3 + MySQL` 实现一个轻量、少依赖的单点登录系统
- 用户侧只保留一个入口：`/sso`
- 用户通过 `卡密 + 邮箱前缀 + 邮箱后缀` 完成登录
- 新卡首次使用时自动绑定到邮箱
- 作为 `OIDC Identity Provider` 对接 `OpenAI ChatGPT Business`
- 控制实现体量，目标落在 `20 个文件内`
- 以安全为前提，优先规避 SQL 注入、会话固定、开放重定向、弱随机数、明文卡密泄露等常见问题

当前文档列表：

1. `01-product-scope.md`：产品范围、角色、业务规则、验收标准
2. `02-architecture.md`：总体架构、模块拆分、流程、路由与文件预算
3. `03-openai-chatgpt-business-oidc.md`：OpenAI ChatGPT Business 的 OIDC 接入设计
4. `04-database-design.md`：数据库表设计、字段建议、状态流转
5. `05-security-design.md`：安全设计、威胁模型、上线检查项
6. `06-deployment-installation.md`：部署、初始化、联调和上线步骤
7. `07-admin-and-employee-guides.md`：管理员手册与新员工使用教程

已确认的 OpenAI 官方约束：

- `ChatGPT Business` 支持 `SAML` 和 `OIDC`
- 本项目固定选择 `OIDC`
- Business 版 SSO 仅作用于 `ChatGPT`，不作用于 `platform.openai.com`
- Business 版没有 `SCIM`
- 启用 SSO 之前必须先完成至少一个域名验证
- OpenAI 官方建议先将 SSO 保持为 `Optional` 进行测试，避免将管理员锁死
- 后台入口位于 `https://chatgpt.com/admin/identity`
- 配置向导中存在 `Custom OIDC` 选项

文档阶段边界：

- 当前先产出设计与操作文档，不包含业务代码
- 文档中出现的脚本、路由、表结构、配置项均以首版实现目标为准
- 等代码阶段开始后，如 OpenAI 后台字段名与当前假设存在差异，以实际控制台为准微调

推荐阅读顺序：

1. 先读 `01-product-scope.md`
2. 再读 `03-openai-chatgpt-business-oidc.md`
3. 然后读 `05-security-design.md`
4. 最后结合 `06-deployment-installation.md` 与 `07-admin-and-employee-guides.md` 落地使用
