# NewToken / Sub2API WebUI 项目文档

> 本目录是对 `newtoken/`、`scripts/`、`tools/` 全部源码的深度复盘文档，覆盖架构规划、业务理解、运行时序与每一个实现细节。
>
> 文档基于 `main` 分支源码（截至 commit `22e39d9`）逐文件逐函数分析生成。

---

## 一句话理解本项目

**这是一个"ChatGPT 账号工厂 + 自动运维系统"**：它以一个 ChatGPT Business/Team **母号**为管理入口，自动批量注册全新的 ChatGPT 账号、把账号订阅转换成可用的 API token 导入到第三方 **Sub2API** 网关、对额度耗尽的账号做"降级 Codex + 停用"处理、并通过独立的 **OIDC** 服务把可用资源以**卡密**形式发放给最终用户。整个运维链路由后台调度器无人值守地循环执行。

---

## 文档地图

### 🚀 自部署 / 跑起来（最实操）

| 文档 | 内容 |
|------|------|
| [14-部署运行手册](./14-部署运行手册.md) | **从零把 WebUI 跑起来**：前置、依赖、`.env` 配置与值来源、启动、自动维护 6 阶段、逐环节验证、🔴 关键约束、故障排查、清理。**自部署直接看这篇。** |

### 📐 概览与业务（先读这两篇建立全局认知）

| 文档 | 内容 |
|------|------|
| [01-架构总览](./01-架构总览.md) | 系统定位、分层架构、三大运行形态、模块划分、技术选型与设计原则、部署拓扑、目录结构、组件交互全景 |
| [02-业务理解与核心概念](./02-业务理解与核心概念.md) | 业务背景与目标、核心概念词典（母号 / ACC 席位 / ChatGPT vs Codex / Sub2API / OIDC 卡密 / 额度窗口）、完整业务闭环、数据资产流转 |

### ⚙️ 核心流程（项目的"心脏"，含运行时序图）

| 文档 | 内容 |
|------|------|
| [03-自动维护流水线](./03-自动维护流水线.md) | 调度器 `WebScheduler`、后台任务模型 `WebTaskStore`、`run_auto_maintenance` 多阶段逐步详解、低额度降级、补号判定，**含完整时序图** |
| [04-自动注册引擎](./04-自动注册引擎.md) | `register.py` 全流程：curl_cffi TLS 指纹绕 CF、Sentinel PoW 求解器、企业 SSO 免验证码、PKCE OAuth 换 token、批量并发模型，**含注册时序图与反检测技术全汇总** |

### 🧩 模块详解（逐文件逐函数）

| 文档 | 覆盖范围 |
|------|----------|
| [05-模块详解-common基础设施](./05-模块详解-common基础设施.md) | `cf_client` / `http_client`（手写 SOCKS5）/ `runtime`，以及 `entry.py`、打包脚本 |
| [06-模块详解-acc席位管理](./06-模块详解-acc席位管理.md) | `seat_client`（席位状态机）/ `gpt_space_manager` / `cache` / `local_env` |
| [07-模块详解-sub2api对接](./07-模块详解-sub2api对接.md) | `remote`（扫描/导入主干）/ `converter_core`（token 转换）/ `remote_oauth` / `usage_bridge` / `converter_archive` |
| [08-模块详解-webui服务](./08-模块详解-webui服务.md) | `server`/`scheduler`/`tasks`/`config`(WebState)/`api`/`auth`/`oauth`/`oidc_client`/前端资产 等全部 webui 文件 |
| [09-模块详解-desktop桌面端](./09-模块详解-desktop桌面端.md) | `converter_app`/`remote_ui`/`acc_seat_ui`/`openai_oauth_ui`/`gpt_space_manager_ui`/`github_updater`/`first_run_setup`/`standalone_tool` |

### 📚 参考资料

| 文档 | 内容 |
|------|------|
| [10-配置与环境变量](./10-配置与环境变量.md) | 全部环境变量逐项详解、`.env` 读写规则、安装完成判定逻辑、代理优先级链 |
| [11-外部接口对接](./11-外部接口对接.md) | ChatGPT/OpenAI API + Sub2API 管理端 REST（18 个端点）+ OIDC 卡密 API 的完整契约汇总 |
| [12-运行时序图汇总](./12-运行时序图汇总.md) | 所有关键流程的 mermaid 时序图/状态图集中页 |
| [13-已知问题与维护要点](./13-已知问题与维护要点.md) | 真实 Bug（`run_auto_cycle` 导入崩溃）、硬编码失效点、死代码、安全风险、反检测维护清单 |

---

## 推荐阅读路径

- **第一次接触本项目** → 01 → 02 → 03 → 04
- **负责部署运维** → 01 → 10 → 03 → 13 → 根目录 `DEPLOY.md` / `oidc/DEPLOY_OIDC.md`
- **二次开发 / 改 bug** → 01 → 对应模块详解（05~09）→ 11 → 13
- **排查线上问题** → 13 → 12 → 03 → 对应模块详解

---

## 关键事实速查

| 项目 | 值 |
|------|-----|
| WebUI 启动入口 | `entry.py`（`python entry.py --host 0.0.0.0 --port 28463`） |
| WebUI 默认端口 | `28463`（刻意避开常用端口） |
| 桌面端入口 | `newtoken/desktop/standalone_tool.py` |
| 源码包路径 | **`newtoken/newtoken/`（仓库根目录下嵌套一层同名包目录）** |
| 唯一第三方运行时依赖 | `curl_cffi`（仅自动注册链路需要；其余功能纯标准库） |
| 后台维护周期 | 默认 `300` 秒（5 分钟），可配 60~86400 秒 |
| ChatGPT 席位硬上限 | `2` 个 |
| 低额度阈值 | 剩余额度 `< 10%` |
| OIDC 服务 | 独立 PHP 项目（`oidc/`，已有自带文档 `oidc/docs/`） |

> ✅ **`feat/javoo` 分支（commit `8a65f20`）已修复 WebUI 启动 Bug，并将自动注册重写为 codex oauth + OIDC 卡密 SSO（免手机验证）。**
> **自部署 / 自己跑起来，请直接看 [14-部署运行手册](./14-部署运行手册.md)**（含配置、启动、逐环节验证、关键约束、排查）。
> 注意：04/13 中描述「企业 SSO 免验证码（`team.edu.sixoner.com`/authentik）」的旧注册流程已废弃，以 14 为准。
