# Python 服务全链路日志改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 WebUI 服务链路加统一、可追溯、敏感数据脱敏的全链路日志，堵死三个吞栈点。

**Architecture:** 新建中央模块 `newtoken/common/logging_setup.py`（标准库 `logging`，轮转文件+控制台+`contextvars` 关联 ID + 脱敏 Filter）；各服务模块改用其 logger，关键异常改 `logger.exception` 落完整栈；HTTP 全量日志只接 `register._retry_request` 单点；run_id 经 contextvars 自动贯穿，线程边界显式接力。

**Tech Stack:** Python 3.11 标准库 `logging` / `logging.handlers.RotatingFileHandler` / `contextvars`；测试用 pytest 8.3（已装于 `.venv`）。

参考 spec：`docs/superpowers/specs/2026-06-16-python-service-logging-design.md`

---

## 文件结构

| 文件 | 责任 | 动作 |
|---|---|---|
| `newtoken/common/logging_setup.py` | 唯一日志入口：配置、logger、run_id 上下文、脱敏 | 新建 |
| `tests/test_logging_setup.py` | 中央模块单测 | 新建 |
| `newtoken/webui/server.py` | 启动即 setup_logging；do_POST 落栈；banner→logger | 改 |
| `newtoken/webui/tasks.py` | 后台任务 run_id 上下文 + 异常落栈 | 改 |
| `newtoken/webui/register.py` | `_log`→logger；HTTP 单点日志；register_one 落栈 + run_id | 改 |
| `newtoken/webui/auto.py` | 周期 run_id + phase 日志 + 异常落栈 | 改 |
| `newtoken/webui/scheduler.py` | tick / 提交任务 / 异常日志 | 改 |
| `newtoken/webui/monitor.py` | 异常落栈 | 改 |
| `newtoken/webui/config.py` | 4 个日志 env 默认值 | 改 |
| `.env.example` | 日志 env 注释 | 改 |

---

## Task 1: 中央日志模块 + 单测（TDD）

**Files:**
- Create: `newtoken/common/logging_setup.py`
- Test: `tests/test_logging_setup.py`

- [ ] **Step 1: 写失败测试** — `tests/test_logging_setup.py`

```python
"""newtoken.common.logging_setup 单元测试。"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from newtoken.common import logging_setup as ls


@pytest.fixture(autouse=True)
def _reset():
    ls.reset_logging()
    yield
    ls.reset_logging()


def test_mask_token_keeps_prefix_hides_rest():
    out = ls.mask_token("eyJhbGciOiJ" + "x" * 200)
    assert out.startswith("eyJhbG")
    assert "x" * 20 not in out
    assert "masked,len=" in out


def test_mask_token_short_and_empty():
    assert ls.mask_token("") == ""
    assert ls.mask_token("abc") == "***"


def test_mask_card_and_password():
    assert ls.mask_card("ABCD1234EFGH") == "ABCD****"
    assert ls.mask_card("") == ""
    assert ls.mask_password("hunter2") == "***"
    assert ls.mask_password("") == ""


def test_mask_text_redacts_jwt_in_body():
    body = 'prefix {"access_token":"eyJabc.' + "y" * 40 + '.zzz"} suffix'
    out = ls.mask_text(body)
    assert "y" * 40 not in out
    assert "prefix" in out and "suffix" in out


def test_log_run_context_sets_and_resets():
    assert ls._run_id_var.get() == "-"
    with ls.log_run_context("auto203500"):
        assert ls._run_id_var.get() == "auto203500"
        with ls.log_run_context("auto203500/r1"):
            assert ls._run_id_var.get() == "auto203500/r1"
        assert ls._run_id_var.get() == "auto203500"
    assert ls._run_id_var.get() == "-"


def test_setup_logging_creates_file_and_writes(tmp_path: Path):
    log_path = ls.setup_logging(level="DEBUG", log_dir=str(tmp_path))
    assert log_path == tmp_path / "sub2api.log"
    ls.get_logger("webui.test").info("hello-line")
    logging.getLogger(ls.LOGGER_ROOT).handlers[0].flush()
    assert "hello-line" in log_path.read_text(encoding="utf-8")


def test_setup_logging_idempotent(tmp_path: Path):
    ls.setup_logging(level="INFO", log_dir=str(tmp_path))
    n1 = len(logging.getLogger(ls.LOGGER_ROOT).handlers)
    ls.setup_logging(level="INFO", log_dir=str(tmp_path))
    n2 = len(logging.getLogger(ls.LOGGER_ROOT).handlers)
    assert n1 == n2 == 2


def test_run_id_appears_in_file(tmp_path: Path):
    log_path = ls.setup_logging(level="DEBUG", log_dir=str(tmp_path))
    with ls.log_run_context("auto999"):
        ls.get_logger("webui.test").info("with-context")
    logging.getLogger(ls.LOGGER_ROOT).handlers[0].flush()
    assert "auto999" in log_path.read_text(encoding="utf-8")


def test_exception_writes_traceback(tmp_path: Path):
    log_path = ls.setup_logging(level="DEBUG", log_dir=str(tmp_path))
    log = ls.get_logger("webui.test")
    try:
        raise RuntimeError("boom-xyz")
    except RuntimeError:
        log.exception("caught failure")
    logging.getLogger(ls.LOGGER_ROOT).handlers[0].flush()
    text = log_path.read_text(encoding="utf-8")
    assert "Traceback (most recent call last)" in text
    assert "boom-xyz" in text


def test_masking_filter_redacts_token_in_emitted_log(tmp_path: Path):
    log_path = ls.setup_logging(level="DEBUG", log_dir=str(tmp_path))
    secret = "eyJsecret." + "q" * 60 + ".tail"
    ls.get_logger("webui.test").info("token=%s done", secret)
    logging.getLogger(ls.LOGGER_ROOT).handlers[0].flush()
    text = log_path.read_text(encoding="utf-8")
    assert "q" * 60 not in text
    assert "done" in text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_logging_setup.py -q`
Expected: FAIL（`ModuleNotFoundError: newtoken.common.logging_setup` 或属性缺失）

- [ ] **Step 3: 写实现** — `newtoken/common/logging_setup.py`

```python
"""统一日志基础设施：轮转文件 + 控制台 + 关联 ID(run_id) + 敏感数据脱敏。

服务全链路唯一日志入口。仅依赖标准库。

用法：
    from newtoken.common.logging_setup import setup_logging, get_logger, log_run_context
    setup_logging(level="INFO")                 # 进程启动时调一次
    logger = get_logger("webui.register")       # 各模块取 logger
    with log_run_context("auto203500/r1"):      # 关联 ID 自动注入每条日志
        logger.info("...")
"""
from __future__ import annotations

import contextvars
import logging
import logging.handlers
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from newtoken.common.runtime import get_app_dir

LOGGER_ROOT = "sub2api"
_LOG_FILENAME = "sub2api.log"
_DEFAULT_LEVEL = "INFO"
_DEFAULT_MAX_BYTES = 10 * 1024 * 1024
_DEFAULT_BACKUP_COUNT = 5
_FORMAT = "%(asctime)s | %(levelname)-5s | %(threadName)-16s | %(run_id)s | %(name)s | %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

_run_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("sub2api_run_id", default="-")
_configured = False
_log_path: Path | None = None


# --- 脱敏 -------------------------------------------------------------------

def mask_token(value: str) -> str:
    """token 只留前 6 位 + 长度。"""
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 10:
        return "***"
    return f"{text[:6]}…(masked,len={len(text)})"


def mask_card(value: str) -> str:
    """卡密只留前 4 位。"""
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 4:
        return "***"
    return f"{text[:4]}****"


def mask_password(value: str) -> str:
    return "***" if value else ""


# 兜底网：抓 JWT 与 "key":"value" 形态的密钥（防 HTTP 响应体里漏密钥）。
_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{6,}(?:\.[A-Za-z0-9_-]+)?")
_KV_SECRET_RE = re.compile(
    r"(\"?(?:access_token|refresh_token|id_token|password|client_secret|api_key|card)\"?\s*[:=]\s*\"?)"
    r"([A-Za-z0-9._\-]{6,})",
    re.IGNORECASE,
)


def mask_text(text: str) -> str:
    """对一段文本做兜底脱敏。"""
    s = str(text)
    s = _JWT_RE.sub(lambda m: mask_token(m.group(0)), s)
    s = _KV_SECRET_RE.sub(lambda m: m.group(1) + mask_token(m.group(2)), s)
    return s


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = _run_id_var.get()
        return True


class _MaskingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            rendered = record.getMessage()
        except Exception:
            return True
        masked = mask_text(rendered)
        if masked != rendered:
            record.msg = masked
            record.args = ()
        return True


# --- 关联 ID ----------------------------------------------------------------

@contextmanager
def log_run_context(run_id: str) -> Iterator[str]:
    token = _run_id_var.set(str(run_id or "-"))
    try:
        yield _run_id_var.get()
    finally:
        _run_id_var.reset(token)


# --- 配置 -------------------------------------------------------------------

def _resolve_level(level: object) -> int:
    raw = level if level not in (None, "") else os.environ.get("SUB2API_LOG_LEVEL") or _DEFAULT_LEVEL
    if isinstance(raw, int):
        return raw
    return logging.getLevelName(str(raw).strip().upper()) if isinstance(
        logging.getLevelName(str(raw).strip().upper()), int
    ) else logging.INFO


def _resolve_int(value: object, env_key: str, default: int) -> int:
    raw = value if value not in (None, "") else os.environ.get(env_key)
    try:
        out = int(str(raw).strip())
        return out if out > 0 else default
    except (TypeError, ValueError):
        return default


def _resolve_log_dir(log_dir: object) -> Path:
    raw = log_dir if log_dir not in (None, "") else os.environ.get("SUB2API_LOG_DIR")
    if raw:
        return Path(str(raw)).expanduser()
    return get_app_dir(__file__) / "logs"


def setup_logging(
    *,
    level: object = None,
    log_dir: object = None,
    max_bytes: object = None,
    backup_count: object = None,
) -> Path:
    """配置 sub2api 根 logger（幂等）。返回日志文件路径。"""
    global _configured, _log_path
    root = logging.getLogger(LOGGER_ROOT)
    resolved_level = _resolve_level(level)
    if _configured and _log_path is not None:
        root.setLevel(resolved_level)
        return _log_path

    target_dir = _resolve_log_dir(log_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / _LOG_FILENAME

    formatter = logging.Formatter(_FORMAT, _DATEFMT, defaults={"run_id": "-"})
    ctx_filter = _ContextFilter()
    mask_filter = _MaskingFilter()

    file_handler = logging.handlers.RotatingFileHandler(
        path,
        maxBytes=_resolve_int(max_bytes, "SUB2API_LOG_MAX_BYTES", _DEFAULT_MAX_BYTES),
        backupCount=_resolve_int(backup_count, "SUB2API_LOG_BACKUP_COUNT", _DEFAULT_BACKUP_COUNT),
        encoding="utf-8",
    )
    console_handler = logging.StreamHandler()
    for handler in (file_handler, console_handler):
        handler.setFormatter(formatter)
        handler.addFilter(ctx_filter)
        handler.addFilter(mask_filter)
        root.addHandler(handler)

    root.setLevel(resolved_level)
    root.propagate = False
    _configured = True
    _log_path = path
    return path


def get_logger(name: str) -> logging.Logger:
    clean = str(name or "").strip()
    if not clean or clean == LOGGER_ROOT:
        return logging.getLogger(LOGGER_ROOT)
    if clean.startswith(LOGGER_ROOT + "."):
        return logging.getLogger(clean)
    return logging.getLogger(f"{LOGGER_ROOT}.{clean}")


def reset_logging() -> None:
    """清空配置（供测试与重配置使用）。"""
    global _configured, _log_path
    root = logging.getLogger(LOGGER_ROOT)
    for handler in list(root.handlers):
        try:
            handler.close()
        except Exception:
            pass
        root.removeHandler(handler)
    _configured = False
    _log_path = None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_logging_setup.py -q`
Expected: PASS（10 passed）

- [ ] **Step 5: 提交**

```bash
git add newtoken/common/logging_setup.py tests/test_logging_setup.py
git commit -m "feat(logging): 新增中央日志模块 logging_setup（轮转文件+关联ID+脱敏）"
```

---

## Task 2: 接入 server.py（启动 + 堵 do_POST 吞栈点）

**Files:** Modify `newtoken/webui/server.py`

- [ ] **Step 1: 加导入与模块 logger**（文件顶部 import 区，`from newtoken.webui.utils import json_safe` 之后）

```python
from newtoken.common.logging_setup import get_logger, setup_logging

logger = get_logger("webui.server")
```

- [ ] **Step 2: `log_message` 路由到 logger（DEBUG）** — 替换 `server.py:39-40`

```python
    def log_message(self, fmt: str, *args) -> None:
        logger.debug("%s %s", self.address_string(), fmt % args)
```

- [ ] **Step 3: do_POST 异常落完整栈** — 替换 `server.py:95-96`

```python
        except Exception as exc:  # noqa: BLE001
            logger.exception("API 处理失败 path=%s", path)
            self._send_json({"ok": False, "error": str(exc)}, status=400)
```

- [ ] **Step 4: main() 启动即配置日志 + banner 改 logger** — 在 `main()` 内 `values = state.load_config()` 之后插入 setup_logging，并把 `server.py:214-218`、`223` 的 print 换成 logger

```python
    state = WebState(env_path)
    values = state.load_config()
    setup_logging(
        level=values.get("SUB2API_LOG_LEVEL"),
        log_dir=values.get("SUB2API_LOG_DIR"),
        max_bytes=values.get("SUB2API_LOG_MAX_BYTES"),
        backup_count=values.get("SUB2API_LOG_BACKUP_COUNT"),
    )
    host, port = resolve_server_bind(args, values)
    scheduler = WebScheduler(state)
    state.scheduler = scheduler
    server = Sub2APIWebServer((host, port), WebUIHandler, state)
    logger.info("Sub2API WebUI 监听 http://%s:%s", host, port)
    if values.get("SUB2API_OUTBOUND_PROXY_URL"):
        logger.info("出站代理 %s", mask_proxy_url(values.get("SUB2API_OUTBOUND_PROXY_URL")))
    if not state.auth_secret:
        logger.warning("SUB2API_WEB_SECRET 为空；WebUI 无密码保护。")
    scheduler.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("正在停止 Sub2API WebUI …")
    finally:
        scheduler.stop()
        server.server_close()
        state.tasks.shutdown(wait=False)
    return 0
```

- [ ] **Step 5: 冒烟（import 不报错）+ 提交**

Run: `.venv/bin/python -c "import newtoken.webui.server"`
Expected: 无输出无异常

```bash
git add newtoken/webui/server.py
git commit -m "feat(logging): server 启动接入日志，do_POST 异常落完整栈"
```

---

## Task 3: 接入 tasks.py（后台任务 run_id + 落栈）

**Files:** Modify `newtoken/webui/tasks.py`

- [ ] **Step 1: 加导入与 logger**（顶部 import 区）

```python
from newtoken.common.logging_setup import get_logger, log_run_context

logger = get_logger("webui.tasks")
```

- [ ] **Step 2: runner 包 run_id 上下文 + 异常落栈** — 替换 `tasks.py:52-71` 的 `def runner()` 整体

```python
        def runner() -> None:
            with self._lock:
                task["status"] = "running"
                task["started_at"] = time.time()
            with log_run_context(f"task-{task_id}"):
                logger.info("任务开始 label=%s id=%s", normalized_label, task_id)
                try:
                    result = target(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("任务失败 label=%s id=%s", normalized_label, task_id)
                    with self._lock:
                        task["status"] = "error"
                        task["error"] = str(exc)
                        task["finished_at"] = time.time()
                        self._active_by_label.pop(normalized_label, None)
                        self._trim_locked()
                    return
                with self._lock:
                    task["status"] = "done"
                    task["result"] = result
                    task["finished_at"] = time.time()
                    self._active_by_label.pop(normalized_label, None)
                    self._trim_locked()
                logger.info("任务完成 label=%s id=%s", normalized_label, task_id)
```

- [ ] **Step 3: 冒烟 + 提交**

Run: `.venv/bin/python -c "import newtoken.webui.tasks"`
Expected: 无异常

```bash
git add newtoken/webui/tasks.py
git commit -m "feat(logging): 后台任务 run_id 上下文 + 异常落完整栈"
```

---

## Task 4: 接入 register.py（_log→logger / HTTP 单点 / 落栈 / run_id）

**Files:** Modify `newtoken/webui/register.py`

- [ ] **Step 1: 加导入与 logger**（顶部 import 区，`from urllib.parse import ...` 之后）

```python
from newtoken.common.logging_setup import get_logger, log_run_context, mask_text, mask_token

logger = get_logger("webui.register")
```

- [ ] **Step 2: URL 短化助手** — 在模块函数区（如 `_make_trace_headers` 上方）新增

```python
def _short_url(url: str) -> str:
    """日志用：去掉 query（可能含 code/token），只留 scheme://host/path。"""
    try:
        parsed = urlparse(str(url))
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    except Exception:
        return str(url)[:80]
```

- [ ] **Step 3: `_log` 改路由 logger** — 替换 `register.py:399-402`

```python
    def _log(self, msg: str) -> None:
        logger.info("%s", msg)
```

- [ ] **Step 4: `_retry_request` 接 HTTP 全量日志** — 替换 `register.py:372-385` 的 `_retry_request` 函数体

```python
        def _retry_request(method, url, *args, **kwargs):
            last_exc = None
            for attempt in range(5):
                started = time.time()
                try:
                    resp = _orig_request(method, url, *args, **kwargs)
                except Exception as exc:  # noqa: BLE001
                    if not any(m in str(exc) for m in _retry_markers):
                        logger.debug("HTTP %s %s 异常(不重试): %s", method, _short_url(url), exc)
                        raise
                    last_exc = exc
                    logger.debug("HTTP %s %s 传输失败(重试%d): %s", method, _short_url(url), attempt + 1, exc)
                    if attempt < 4:
                        time.sleep(min(0.5 * (2 ** attempt), 5.0) + random.uniform(0, 0.4))
                    continue
                elapsed_ms = (time.time() - started) * 1000
                status = getattr(resp, "status_code", "-")
                if isinstance(status, int) and status >= 400:
                    body = mask_text(str(getattr(resp, "text", ""))[:200])
                    logger.warning("HTTP %s %s -> %s (%.0fms) body=%s", method, _short_url(url), status, elapsed_ms, body)
                else:
                    logger.debug("HTTP %s %s -> %s (%.0fms)", method, _short_url(url), status, elapsed_ms)
                return resp
            raise last_exc
```

- [ ] **Step 5: `register_one` 加 run_id 参数 + 包上下文 + 失败落栈** — 替换 `register.py:1037-1079` 的 `register_one` 整体

```python
def register_one(idx: int, *, email_domain: str = "", proxy_url: str = "",
                 oidc_api_url: str = "", oidc_api_key: str = "", account_id: str = "",
                 tag_prefix: str = "r", run_id: str = "") -> RegisterResult:
    """直接 codex oauth + 自建 OIDC 卡密 SSO 注册单个账号，换取 codex token。

    流程：发卡 → codex auth_url(login_hint) → SSO → 卡密首次激活 → consent →
    workspace/select → code → 换 token。全程不碰 chatgpt 网页（避免手机验证）。
    """
    tag = f"{tag_prefix}{idx}"
    context_id = f"{run_id}/{tag}" if run_id else tag
    with log_run_context(context_id):
        reg: TeamRegistration | None = None
        email = ""
        steps: list[str] = []
        try:
            domain = (email_domain or DEFAULT_EMAIL_DOMAIN).lstrip("@").strip()
            if not domain:
                raise RuntimeError("email_domain 为空")
            if not str(account_id or "").strip():
                raise RuntimeError("account_id（母号 workspace_id）为空")

            # 1. 发卡
            card = issue_oidc_card(oidc_api_url, oidc_api_key)
            steps.append("issue_card")

            # 2. 随机身份
            prefix = _random_prefix()
            email = f"{prefix}@{domain}"
            full_name = _random_name()

            # 3. codex oauth + 卡密 SSO 登录 → codex token
            reg = TeamRegistration(proxy_url=proxy_url, tag=tag, email_domain="@" + domain)
            logger.info("开始注册 email=%s", email)
            tokens = reg.codex_card_login(email=email, prefix=prefix, card=card,
                                          account_id=str(account_id).strip(), domain=domain,
                                          full_name=full_name, steps=steps)
            token_json = build_codex_token_json(email, tokens)
            reg._log(f"[done] email={email} rt={mask_token(str(tokens.get('refresh_token') or ''))}")
            logger.info("注册成功 email=%s steps=%s", email, ",".join(steps))
            return RegisterResult(ok=True, email=email, token_json=token_json, steps_completed=steps)

        except Exception as exc:
            logger.exception("注册失败 email=%s steps=%s", email or "-", ",".join(steps))
            return RegisterResult(ok=False, email=email, error=f"{type(exc).__name__}: {exc}", steps_completed=steps)
        finally:
            if reg is not None:
                reg.close()
```

- [ ] **Step 6: `register_batch` 透传 run_id** — 替换 `register.py:1081-1100` 的 `register_batch` 整体

```python
def register_batch(count: int, *, email_domain: str = "", proxy_url: str = "",
                   oidc_api_url: str = "", oidc_api_key: str = "", account_id: str = "",
                   max_workers: int = 1, run_id: str = "") -> list[RegisterResult]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    results: list[RegisterResult] = []
    with ThreadPoolExecutor(max_workers=min(max_workers, max(1, count)), thread_name_prefix="webui-reg-") as ex:
        futures = {
            ex.submit(register_one, i + 1, email_domain=email_domain, proxy_url=proxy_url,
                      oidc_api_url=oidc_api_url, oidc_api_key=oidc_api_key, account_id=account_id,
                      run_id=run_id): i + 1
            for i in range(count)
        }
        for fut in as_completed(futures):
            results.append(fut.result())
    return sorted(results, key=lambda r: r.ok, reverse=True)
```

- [ ] **Step 7: 冒烟 + 提交**

Run: `.venv/bin/python -c "import newtoken.webui.register"`
Expected: 无异常

```bash
git add newtoken/webui/register.py
git commit -m "feat(logging): register 接入日志（_log→logger / HTTP 单点 / 失败落栈 / run_id 贯穿）"
```

---

## Task 5: 接入 auto.py（周期 run_id + phase 日志）

**Files:** Modify `newtoken/webui/auto.py`

- [ ] **Step 1: 加导入与 logger**（顶部 import 区，`import time` 之后）

```python
from newtoken.common.logging_setup import get_logger, log_run_context

logger = get_logger("webui.auto")
```

- [ ] **Step 2: 周期包 run_id 上下文 + phase 日志 + 透传 run_id** — 在 `run_auto_maintenance` 体内：将 `run_id = f"auto{time.strftime('%H%M%S')}"` 生成并用 `with log_run_context(run_id):` 包住从 `config = state.load_config()` 到 `return report` 的全部逻辑（缩进一层）。在每个 phase 的 try 起始加 `logger.info("phase=... ...")`，每个 except 把 `report["errors"].append(...)` 旁加 `logger.exception("phase=... 失败")`。并将 Phase 4 的 `register_batch(...)` 调用追加 `run_id=run_id` 参数。

> 关键替换点（最小必要）——`run_auto_maintenance` 开头：

```python
def run_auto_maintenance(state: WebState) -> dict[str, Any]:
    start = time.time()
    run_id = f"auto{time.strftime('%H%M%S')}"
    with log_run_context(run_id):
        logger.info("自动维护开始 run_id=%s", run_id)
        report: dict[str, Any] = {
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start)),
            "phases": [],
            "errors": [],
        }
        # ……（原有逻辑整体缩进到此 with 块内，每个 except 增加 logger.exception；
        #     所有 `return report` 保持不变，仍在 with 块内）……
```

> Phase 4 调用改为：

```python
        register_results = register_batch(
            register_count, email_domain=email_domain, proxy_url=proxy_url,
            oidc_api_url=str(config.get("SUB2API_OIDC_API_URL") or "").strip(),
            oidc_api_key=str(config.get("SUB2API_OIDC_API_KEY") or "").strip(),
            account_id=str(config.get("OPENAI_ACCOUNT_ID") or "").strip(),
            max_workers=1, run_id=run_id,
        )
```

> 各 except 内统一追加（示例 seat_policy）：

```python
    except Exception as exc:
        logger.exception("phase=seat_policy 失败")
        report["phases"].append({**_auto_phase("seat_policy", start), "error": str(exc)})
        report["errors"].append(f"seat_policy: {exc}")
```

（remote_scan / register / import / oidc_cards 各 except 同样加一行 `logger.exception("phase=<名> 失败")`。）

- [ ] **Step 3: 冒烟 + 提交**

Run: `.venv/bin/python -c "import newtoken.webui.auto"`
Expected: 无异常

```bash
git add newtoken/webui/auto.py
git commit -m "feat(logging): auto 周期 run_id 贯穿 + phase 日志 + 异常落栈"
```

---

## Task 6: 接入 scheduler.py + monitor.py

**Files:** Modify `newtoken/webui/scheduler.py`, `newtoken/webui/monitor.py`

- [ ] **Step 1: scheduler 加导入与 logger**（顶部 import 区）

```python
from newtoken.common.logging_setup import get_logger

logger = get_logger("webui.scheduler")
```

- [ ] **Step 2: scheduler 提交/跳过/异常日志** — `_schedule_policy`（`scheduler.py:161-189`）三处加日志

```python
    def _schedule_policy(self, values: dict[str, str]) -> None:
        now = time.time()
        missing = find_missing_policy_config(values)
        if missing:
            logger.info("跳过自动策略：等待配置 %s", ", ".join(missing))
            self._update_status(
                last_tick_at=now,
                skipped_reason="等待配置：" + ", ".join(missing),
                last_error="",
            )
            return
        try:
            task_id = self.state.tasks.create(
                AUTO_MAINTENANCE_TASK_LABEL,
                run_auto_maintenance,
                self.state,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("提交策略任务失败")
            self._update_status(
                last_tick_at=now,
                last_error=str(exc),
                skipped_reason="提交策略任务失败",
            )
            return
        logger.info("已提交自动维护任务 task_id=%s", task_id)
        self._update_status(
            last_tick_at=now,
            last_task_id=task_id,
            last_error="",
            skipped_reason="",
        )
```

- [ ] **Step 3: monitor 加导入/logger + 异常落栈** — `monitor.py` 顶部加

```python
from newtoken.common.logging_setup import get_logger

logger = get_logger("webui.monitor")
```

替换 `monitor.py:70-71` 的 except：

```python
    except Exception as exc:  # noqa: BLE001
        logger.exception("auto_offline_dead 失败")
        return {"offlined": 0, "failed": len(target), "errors": [str(exc)]}
```

- [ ] **Step 4: 冒烟 + 提交**

Run: `.venv/bin/python -c "import newtoken.webui.scheduler, newtoken.webui.monitor"`
Expected: 无异常

```bash
git add newtoken/webui/scheduler.py newtoken/webui/monitor.py
git commit -m "feat(logging): scheduler/monitor 接入日志与异常落栈"
```

---

## Task 7: 配置默认值 + .env.example

**Files:** Modify `newtoken/webui/config.py`, `.env.example`

- [ ] **Step 1: config.py 默认表追加 4 个日志变量** — 在 `WEB_DEFAULT_ENV_VALUES`（`config.py:70`）字典内追加

```python
    "SUB2API_LOG_LEVEL": "INFO",
    "SUB2API_LOG_DIR": "",
    "SUB2API_LOG_MAX_BYTES": "10485760",
    "SUB2API_LOG_BACKUP_COUNT": "5",
```

- [ ] **Step 2: .env.example 追加注释块**（文件末尾）

```bash
# ---- 日志（排障用）----
# 级别 INFO 即可追溯；深挖时设 DEBUG 输出每个 HTTP 请求/响应
SUB2API_LOG_LEVEL=INFO
# 留空 = <应用目录>/logs/sub2api.log
SUB2API_LOG_DIR=
SUB2API_LOG_MAX_BYTES=10485760
SUB2API_LOG_BACKUP_COUNT=5
```

- [ ] **Step 3: 冒烟 + 提交**

Run: `.venv/bin/python -c "import newtoken.webui.config"`
Expected: 无异常

```bash
git add newtoken/webui/config.py .env.example
git commit -m "feat(logging): 新增日志 env 默认值与 .env.example 注释"
```

---

## Task 8: 全量回归 + 真实冒烟验证

- [ ] **Step 1: 单测全过**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: all PASS

- [ ] **Step 2: 所有改动模块可导入**

Run: `.venv/bin/python -c "import newtoken.webui.server, newtoken.webui.tasks, newtoken.webui.register, newtoken.webui.auto, newtoken.webui.scheduler, newtoken.webui.monitor, newtoken.webui.config"`
Expected: 无异常

- [ ] **Step 3: 真实启动冒烟（临时端口，后台启动→查日志→停）**

Run（示例）:
```bash
SUB2API_WEB_PORT=28999 .venv/bin/python entry.py &   # 后台
sleep 3
tail -n 20 logs/sub2api.log     # 应见「Sub2API WebUI 监听」banner 行（带时间/级别/run_id 列）
curl -s localhost:28999/login -o /dev/null -w '%{http_code}\n'
kill %1
```
Expected: `logs/sub2api.log` 出现带 `| INFO  |` 与 `| - |`（run_id 占位）列的 banner 行；HTTP 访问产生 DEBUG 行（若级别=DEBUG）。

- [ ] **Step 4: 终验提交（计划勾选）**

```bash
git add docs/superpowers/plans/2026-06-16-python-service-logging.md
git commit -m "docs(plan): 勾选日志改造实现计划完成项"
```

---

## Self-Review（写完计划后自检）

**1. Spec 覆盖**：§4.1 中央模块→Task1；§4.2 run_id 跨线程接力→Task3(tasks)/Task4(register_one)；§5 三吞栈点→server(Task2)/tasks(Task3)/register(Task4)，外加 auto/scheduler/monitor(Task5/6)；§5 HTTP 单点→Task4 Step4；§6 脱敏→Task1（mask_* + MaskingFilter）；§7 env→Task7；§8 测试→Task1 单测 + Task8 冒烟。覆盖完整，无遗漏。

**2. 占位符扫描**：无 TBD/TODO；每个代码步骤含完整可粘贴代码（auto.py 因「整体缩进」性质给出关键替换点 + 统一 except 模式，执行时照此机械套用）。

**3. 类型/签名一致性**：`setup_logging`/`get_logger`/`log_run_context`/`mask_token`/`mask_card`/`mask_password`/`mask_text`/`reset_logging`/`LOGGER_ROOT`/`_run_id_var` 在 Task1 定义，后续 Task 调用名称一致；`register_one`/`register_batch` 新增 `run_id` 参数在 auto.py 调用处匹配。
