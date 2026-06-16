# Python 服务全链路日志改造 — 设计文档

- 日期：2026-06-16
- 范围：WebUI 服务链路（`entry.py → server.py → scheduler.py → auto.py → register.py → tasks.py → monitor.py`）
- 目标读者：运维 / 排障时 `tail -f` 日志的人
- 实现路线：**方案 A（中央 logging 模块 + contextvars 关联 ID + 统一拦截点）**

---

## 1. 背景与问题

服务即将进入真实使用，要求「出问题时日志清晰、方便追溯排查」。现状评估（探索结论）：

整条链路 **零 `logging` 模块，仅 9 个 `print`**，存在三个「吞掉堆栈」的致命盲点：

| # | 位置 | 问题 |
|---|---|---|
| 1 | `server.py:95-96` `do_POST` | 所有异常只 `str(exc)` 回前端，traceback 完全丢失 |
| 2 | `tasks.py:58-61` runner | 后台任务（注册/导入/维护）异常只存 `task["error"]`，不打印、不落盘、无栈 |
| 3 | `register.py:1074` `register_one` | 注册失败只返回 `f"{type(exc).__name__}: {exc}"`，无栈、看不出哪一步 |

次要问题：

- **无持久化日志**：全 `print` 到 stdout，刷过即丢；`auto.py` 的 `report{phases,errors}` 结构化数据只进内存任务字典（≤80 条，会被裁剪）。
- **后台静默**：`scheduler.py` 后台线程定时跑维护，`last_error=str(exc)`，无法 `tail -f` 观测。
- **无级别/无日期**：`register._log` 只有 `HH:MM:SS`、无 INFO/ERROR 分级、不能开关 DEBUG。
- **敏感数据风险**：服务处理 refresh_token / 卡密 / 密码 / 邮箱，日志必须默认脱敏。

可复用的地基：

- `common/runtime.py:get_app_dir()` 在源码 / PyInstaller 两种模式都能给出正确基目录 → 日志文件落地。
- `register.py:399` `self._session.request = _retry_request` 是**所有 HTTP 请求的唯一拦截点** → HTTP 全量日志一处接入即可全覆盖。
- `auto.py` 的 phase/report 结构是现成的可观测原料。

---

## 2. 目标与非目标

**目标**
- 统一 `logging` 基础设施：轮转文件 + 控制台、级别、时间日期、线程名、关联 ID。
- 堵死三个吞栈点：每个异常都有完整 traceback 落盘。
- 全链路埋点：调度 tick → 维护 phase → 单账号注册 → 每个 HTTP 请求/响应，靠唯一 run_id 串起来。
- 敏感字段默认脱敏（token/卡密/密码），邮箱保留。
- env 驱动配置，贴合现有工程习惯。

**非目标（YAGNI）**
- 不做结构化 JSON 日志（与「人类可读文本」诉求冲突，可作后续增量）。
- 不接外部日志系统（ELK / Loki 等）。
- 不改 desktop 桌面端（`newtoken/desktop/*`）的输出——本次只覆盖「服务」链路。
- 不改业务流程与返回值语义，只加观测。

---

## 3. 已确认决策

| 决策点 | 结论 |
|---|---|
| 实现路线 | 方案 A：中央模块 + contextvars + 统一拦截点 |
| 输出 | 轮转文件 `<app_dir>/logs/sub2api.log`（10MB×5）+ 控制台 |
| 格式 | 人类可读文本，带时间/级别/线程/run_id/logger |
| 默认级别 | 文件 & 控制台 `INFO`；全链路 DEBUG 埋点内建，`SUB2API_LOG_LEVEL=DEBUG` 开启 |
| token/卡密/密码 | 脱敏 |
| 邮箱 | **不脱敏**（随机一次性地址，且是关联账号的主键） |
| 依赖 | 仅标准库 `logging`（保持依赖极简） |

---

## 4. 架构设计

### 4.1 新增中央模块 `newtoken/common/logging_setup.py`

职责单一：配置与提供日志能力，不含业务逻辑。

```
setup_logging(level=None, log_dir=None) -> None
    幂等。配置 root logger：
      - RotatingFileHandler(<log_dir>/sub2api.log, maxBytes, backupCount)
      - StreamHandler(stderr/stdout)
      - 统一 Formatter
      - 挂载 ContextFilter + MaskingFilter
    重复调用只生效一次（用模块级 _CONFIGURED 标志守卫）。

get_logger(name) -> logging.Logger
    薄封装 logging.getLogger，统一命名前缀 "sub2api.*"。

log_run_context(run_id, **fields) -> contextmanager
    进入时 set contextvar，退出时 reset。支持嵌套（周期 → 单账号）。

mask_token(s) / mask_card(s) / mask_password(s) -> str
    集中脱敏函数。
```

**Filter 设计**
- `ContextFilter`：从 contextvar 读 `run_id`，注入 `record.run_id`（无则 `-`）。
- `MaskingFilter`：对 `record.getMessage()` 结果做正则脱敏兜底（token/卡密/密码模式），作为「忘了手动脱敏」的安全网；主路径仍优先在调用处用 `mask_*()` 显式脱敏。

**格式串**
```
%(asctime)s | %(levelname)-5s | %(threadName)-16s | %(run_id)s | %(name)s | %(message)s
```
示例：
```
2026-06-16 20:35:01 | INFO  | webui-reg-0       | auto203500/r1 | sub2api.webui.register | [codex] authorize landed 302
2026-06-16 20:35:04 | ERROR | webui-reg-0       | auto203500/r1 | sub2api.webui.register | 注册失败 email=ab12@ai.1bool.com
Traceback (most recent call last):
  ...
```

### 4.2 关联 ID（run_id）全链路贯穿

- `contextvars.ContextVar` 在单线程内自动随调用栈传递，`ContextFilter` 自动注入——**业务函数无需加 logger/run_id 参数**。
- **线程边界处理（方案 A 唯一的坑）**：`ThreadPoolExecutor` 不自动复制 contextvar。两处显式接力：
  - `register_batch → register_one`：给 `register_one` 增加可选参数 `run_id: str = ""`，在其顶部 `with log_run_context(f"{run_id}/r{idx}")` 重新建立上下文。
  - `tasks.py` runner：在 `runner()` 内、调用 `target` 前用 `log_run_context` 包裹（run_id 取任务 label/id 派生），保证后台任务日志带 ID。
- run_id 生成：每个后台任务由 `tasks.py` runner 派生 task 级上下文（如 `task-<id>`）；`auto.run_auto_maintenance` 在其内再生成周期级 `auto<HHMMSS>` 并包住整个周期（嵌套）。这样无论**调度触发**还是**手动触发**（`/api/tasks/start` action=`auto_maintenance`）都有 run_id，不依赖 scheduler。

---

## 5. 详细改动清单（按文件）

| 文件 | 改动 |
|---|---|
| `newtoken/common/logging_setup.py` | **新增**，见 §4.1 |
| `newtoken/webui/server.py` | `main()` 开头调 `setup_logging()`；5 个启动 `print` → `logger.info`（代理走 `mask_proxy_url`）；`log_message` 接入 logger；**`do_POST` except → `logger.exception("API %s 失败", path)`**，仍回简短 error |
| `newtoken/webui/tasks.py` | `runner()` 内包 `log_run_context`；task 起/止 INFO/DEBUG；**except → `logger.exception("任务 %s(%s) 失败", label, task_id)`** |
| `newtoken/webui/scheduler.py` | 每次 tick DEBUG；提交任务时记 task_id INFO；跳过原因 INFO；`_schedule_policy` except → `logger.exception` |
| `newtoken/webui/auto.py` | 周期入口生成 `auto<HHMMSS>` 并 `log_run_context`；每 phase 进入/结果/elapsed INFO；各 except → `logger.exception`（保留 report 不变） |
| `newtoken/webui/register.py` | `register_one` 加 `run_id` 参，顶部建上下文，**except → `logger.exception`**；`_log` 改路由到 `logger.debug/info`，移除 `print`/`_PRINT_LOCK`；`_retry_request` 接入 HTTP 全量日志（method/脱敏URL/status/耗时/重试 DEBUG，失败 WARNING + 截断响应）；token 用 `mask_token` |
| `newtoken/webui/monitor.py` | `auto_offline_dead` except → `logger.exception` |
| `newtoken/webui/config.py` | 新 env 默认值（见 §7）注册进默认表 |
| `.env.example` | 追加 §7 的 4 个变量及注释 |

> 注：行号以当前 `HEAD` 为准，实施时以符号定位为准（文件可能已变动）。

---

## 6. 脱敏规则

| 字段 | 规则 | 示例 |
|---|---|---|
| refresh_token / access_token / id_token | 前 6 + `…(masked,len=N)` | `eyJhbG…(masked,len=512)` |
| 卡密 (card) | 前 4 + 掩码 | `ABCD****` |
| 密码 | 全掩码 | `***` |
| 代理 URL 凭据 | 复用现有 `mask_proxy_url` | `socks5h://***@host:port` |
| 邮箱 | **不脱敏** | `ab12@ai.1bool.com` |

`MaskingFilter` 作为兜底正则网，防止某处忘了手动脱敏；主路径在调用处显式 `mask_*()`。

---

## 7. 配置项（env）

| 变量 | 默认 | 说明 |
|---|---|---|
| `SUB2API_LOG_LEVEL` | `INFO` | 文件+控制台级别；排障时设 `DEBUG` 开 HTTP 逐请求 |
| `SUB2API_LOG_DIR` | `<app_dir>/logs` | 日志目录 |
| `SUB2API_LOG_MAX_BYTES` | `10485760` (10MB) | 单文件轮转阈值 |
| `SUB2API_LOG_BACKUP_COUNT` | `5` | 保留轮转份数 |

---

## 8. 验证 / 测试方案（TDD）

实现时先写测试。单元测试（标准库 `unittest`，不引新依赖）：

1. `MaskingFilter`：含 token 的消息经过后，原始 token 不出现、出现掩码形态。
2. `mask_token/mask_card/mask_password`：边界（空串、超短、超长）。
3. `log_run_context`：进入后 record.run_id == 给定值，退出后回 `-`；嵌套正确。
4. `setup_logging`：调用后在临时目录生成 `sub2api.log`，写一条 INFO 后文件非空；幂等（重复调用 handler 不翻倍）。
5. `logger.exception`：捕获异常后日志含 `Traceback`。
6. 手动冒烟（非自动化）：真实启动服务 → 确认 `logs/sub2api.log` 出现启动 banner、首次调度 tick、以及一次注册的全链路 run_id 串联。

---

## 9. 风险与回滚

- **风险：HTTP DEBUG 日志量大** → 默认级别 INFO，DEBUG 仅排障开启；轮转限制总量。
- **风险：脱敏遗漏导致密钥落盘** → 双层（显式 `mask_*` + `MaskingFilter` 兜底）+ 测试 1/2 守住。
- **风险：contextvar 不跨线程导致 run_id 丢失** → §4.2 两处显式接力 + 测试 3。
- **风险：改动 `register._log` / `_retry_request` 影响注册成功率** → 只加观测、不改请求参数与控制流；保留原返回值语义。
- **回滚**：改动集中、按文件可独立回退；中央模块为新增文件，移除 `setup_logging()` 调用即退回原 `print` 行为（保留的 print→logger 替换需同时回退，故建议按 commit 粒度回滚）。
