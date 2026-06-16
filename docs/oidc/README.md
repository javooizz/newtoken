# 多母号 OIDC 文档

本目录为「多母号 OIDC（二次开发 `oidc/`）」的正式文档归档：一套自研 PHP OIDC 服务，让单一服务为多个 OpenAI ChatGPT Business「team 母号」做 SSO（每母号独立 client + 独立域名，卡密全局共享）。

## 文档索引

| 文档 | 内容 |
|---|---|
| [01-设计方案](./01-设计方案.md) | 架构、数据模型、OIDC 端点、卡密与域名校验、管理 API、安全、OpenAI 官方约束核实（含来源） |
| [02-实施计划](./02-实施计划.md) | 逐 task TDD 实施计划（12 个 task，含完整代码与验证步骤） |
| [03-落地部署与运维指南](./03-落地部署与运维指南.md) | 部署步骤、新增母号 SOP、配置项、测试矩阵、安全要点、故障排查 |

## 状态

已实现并测试通过（PHP 8.5 + MySQL 实测：纯逻辑 11/11 + 全栈端到端 + 边界 + 管理面 + final review）。代码位于 `feat/javoo` 分支，二次开发于 `oidc/`：新增 `oidc_clients` / `oidc_client_domains` 表、`app/clients.php`、`/api/clients`、admin 母号管理页、`cli/tests/` 测试套件。
