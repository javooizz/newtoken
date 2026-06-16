# 多母号 OIDC 文档

本目录为「多母号 OIDC（二次开发 `oidc/`）」的正式文档归档：一套自研 PHP OIDC 服务，让单一服务为多个 OpenAI ChatGPT Business「team 母号」做 SSO（每母号独立 client + 独立域名，卡密全局共享）。

## 文档索引

| 文档 | 内容 |
|---|---|
| [01-设计方案](./01-设计方案.md) | 架构、数据模型、OIDC 端点、卡密与域名校验、管理 API、安全、OpenAI 官方约束核实（含来源） |
| [02-实施计划](./02-实施计划.md) | 逐 task TDD 实施计划（12 个 task，含完整代码与验证步骤） |
| [03-落地部署与运维指南](./03-落地部署与运维指南.md) | 部署步骤、新增母号 SOP、配置项、测试矩阵、安全要点、故障排查 |
| [04-sharktech1-部署执行手册](./04-sharktech1-部署执行手册.md) | **本次生产部署**实际 runbook：数据盘 `server-data`、PHP8.2/MySQL8.0、Cloudflare+泛域名证书、完成记录、部署中修复 |
| [mother-accounts/](./mother-accounts/) | 各母号接入记录（含 client_secret，**已 `.gitignore` 不提交**）。首个：`ai.1bool.com` |

## 状态

**已实现 + 已生产部署上线**（2026-06-16）。

- **代码**：`feat/javoo` 分支，二次开发于 `oidc/`（新增 `oidc_clients` / `oidc_client_domains` 表、`app/clients.php`、`/api/clients`、admin 母号管理页、`cli/tests/`）。
- **测试**：纯逻辑 11/11 + 全栈端到端 + 边界 + 管理面 + final review。
- **生产部署**：sharktech1（Debian12 + 宝塔），`https://oidc.1bool.com`（经 Cloudflare），PHP 8.2.31 + MySQL 8.0.45，数据落数据盘 `/home/server-data`。详见 [04 部署执行手册](./04-sharktech1-部署执行手册.md)。
- **首个母号接入**：`ai.1bool.com`（OpenAI RaoChris430）—— Custom OIDC 6 步配置 + **真实登录端到端验证成功**（终端用户「卡密 + SSO」进 workspace 成为 ChatGPT-seat member）。详见 [mother-accounts/ai.1bool.com](./mother-accounts/ai.1bool.com.md)。
- **WebUI**（`newtoken/` Python）：暂未部署（待调试重构）。

> 部署中对 `oidc/` 的两处生产加固已提交（commit `05d6e63`）：`bootstrap.php` 按 `app_debug` 关 `display_errors`（防 warning 污染 JSON 端点）、`views.php` 旧字段读取 `?? ` 兜底。
