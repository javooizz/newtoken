"""One-step OpenAI OAuth account creation actions for the WebUI."""

from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import newtoken.acc.seat_client as seat_core

from newtoken.sub2api.remote_oauth import (
    DEFAULT_OAUTH_REDIRECT_URI,
    PendingOpenAIOAuthSession,
    complete_openai_oauth_account_creation,
    generate_random_oauth_account_name,
    load_openai_oauth_defaults,
    normalize_oauth_concurrency,
)
from newtoken.webui.config import WebState, write_env_file
from newtoken.webui.oidc_client import oidc_status

OAUTH_CALLBACK_PATH = "/oauth/callback"


def build_public_oauth_redirect_uri(state: WebState, form: dict[str, str]) -> str:
    """Resolve the browser-reachable WebUI OAuth callback URL."""

    explicit = (form.get("redirect_uri") or "").strip()
    if explicit and explicit != DEFAULT_OAUTH_REDIRECT_URI:
        parsed = urlsplit(explicit)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return explicit
    public_base = (
        form.get("public_base_url")
        or state.load_config().get("SUB2API_WEB_PUBLIC_BASE_URL", "")
        or ""
    ).strip()
    if public_base:
        base = public_base.rstrip("/")
    else:
        values = state.load_config()
        host = values.get("SUB2API_WEB_HOST", "127.0.0.1").strip() or "127.0.0.1"
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1"
        port = values.get("SUB2API_WEB_PORT", "28463").strip() or "28463"
        base = f"http://{host}:{port}"
    return f"{base}{OAUTH_CALLBACK_PATH}"


def start_oauth_flow(state: WebState, form: dict[str, str]) -> dict[str, Any]:
    """Create one pending OAuth flow and return the login URL."""

    defaults = load_openai_oauth_defaults(str(state.env_path))
    group_ids = _parse_group_ids(form.get("group_ids") or defaults.get("group_ids", ""))
    redirect_uri = build_public_oauth_redirect_uri(state, form)
    result = create_openai_oauth_pending_session(
        base_url=form.get("base_url") or defaults.get("base_url", ""),
        admin_api_key=form.get("admin_api_key") or defaults.get("admin_api_key", ""),
        proxy_id=form.get("proxy_id") or defaults.get("proxy_id", ""),
        proxy_url=form.get("proxy_url") or defaults.get("proxy_url", ""),
        proxy_name=form.get("proxy_name") or defaults.get("proxy_name", "default"),
        redirect_uri=redirect_uri,
        account_name=form.get("account_name") or "",
        group_ids=group_ids,
        group_name=form.get("group_name") or defaults.get("group_name", "cc"),
        concurrency=normalize_oauth_concurrency(
            form.get("concurrency") or defaults.get("concurrency", "")
        ),
    )
    pending = result["pending_session"]
    session = {
        "remote_config": result["remote_config"],
        "pending_session": pending,
        "status": "waiting_callback",
        "error": "",
        "result": None,
        "callback_url": "",
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    with state.oauth_lock:
        state.last_oauth_session = session
    return build_oauth_status(state, include_auth_url=True)


def start_blind_oauth_import(
    state: WebState,
    form: dict[str, str],
    *,
    _task_logger=None,
) -> dict[str, Any]:
    """Run the full server-side OAuth import flow for screen-reader use."""

    emit = _task_logger or (lambda _message: None)
    emit("开始检查席位限制和并发任务")
    _assert_blind_oauth_import_allowed(state)
    login_email = _build_random_login_email(state)
    account_name = generate_random_oauth_account_name(prefix="openai-blind")
    emit(f"随机登录邮箱：{login_email}")
    emit(f"随机账号名：{account_name}")
    runtime_dir = state.env_path.parent / ".webui-runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    task_suffix = str(time.time_ns())
    state_file = runtime_dir / f"blind_oauth_import_{task_suffix}.json"
    temp_env_path = runtime_dir / f"blind_oauth_import_{task_suffix}.env"
    merged_env = state.load_config()
    defaults = load_openai_oauth_defaults(str(state.env_path))
    merged_env.update(
        {
            "SUB2API_BASE_URL": form.get("base_url") or defaults.get("base_url", ""),
            "SUB2API_ADMIN_API_KEY": form.get("admin_api_key") or defaults.get("admin_api_key", ""),
            "SUB2API_OAUTH_PROXY_ID": form.get("proxy_id") or defaults.get("proxy_id", ""),
            "SUB2API_OAUTH_PROXY_URL": form.get("proxy_url") or defaults.get("proxy_url", ""),
            "SUB2API_OAUTH_GROUP_IDS": form.get("group_ids") or defaults.get("group_ids", ""),
            "SUB2API_OAUTH_GROUP_NAME": defaults.get("group_name", "cc"),
            "SUB2API_OAUTH_ACCOUNT_CONCURRENCY": str(
                normalize_oauth_concurrency(
                    form.get("concurrency") or defaults.get("concurrency", "")
                )
            ),
        }
    )
    write_env_file(temp_env_path, merged_env)
    emit("已生成本次自动链临时配置")

    command = [sys.executable, "tools/run_openai_camoufox_callback_solver.py"]
    app_dir = state.env_path.parent
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(app_dir),
            "ENV_PATH": str(temp_env_path),
            "OIDC_ENV_PATH": str(app_dir / "oidc" / ".env"),
            "STATE_FILE": str(state_file),
            "OPENAI_LOGIN_EMAIL": login_email,
            "OPENAI_ACCOUNT_NAME": account_name,
            "SUB2API_TARGET_STATUS": "active",
            "PW_HEADLESS": "1",
            "CAMOUFOX_OS": "windows",
            "CAMOUFOX_HUMANIZE": "1",
        }
    )

    try:
        emit("开始执行一键注册登录导入脚本")
        process = subprocess.Popen(
            command,
            cwd=str(app_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        last_stage = ""
        last_page = ""
        callback_logged = False
        deadline = time.time() + 1800
        while process.poll() is None:
            if time.time() > deadline:
                process.kill()
                raise RuntimeError("自动链执行超时")
            payload = _read_blind_oauth_state(state_file)
            state_payload = payload.get("state") if isinstance(payload.get("state"), dict) else {}
            stage = str(state_payload.get("stage") or "").strip()
            page_url = str(state_payload.get("current_page_url") or "").strip()
            callback_url = str(state_payload.get("callback_url") or "").strip()
            result = payload.get("result") if isinstance(payload.get("result"), dict) else None
            if stage and stage != last_stage:
                emit(f"阶段：{stage}")
                last_stage = stage
            if page_url and page_url != last_page:
                emit(f"页面：{page_url}")
                last_page = page_url
            if callback_url and not callback_logged:
                emit("已拿到 localhost callback，正在回填 Sub2API")
                callback_logged = True
            if callback_url and not (
                stage == "import_completed"
                and isinstance(result, dict)
                and int(result.get("account_id", 0) or 0) > 0
            ):
                remote_config = state.build_remote_config()
                pending_session = _pending_session_from_state_payload(
                    payload,
                    fallback_account_name=account_name,
                )
                forced_result = _complete_blind_oauth_from_callback(
                    state,
                    remote_config,
                    pending_session,
                    callback_url,
                    login_email,
                    account_name,
                    emit,
                )
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass
                return forced_result
            if stage == "import_completed" and isinstance(result, dict) and int(result.get("account_id", 0) or 0) > 0:
                emit(f"已导入 Sub2API，账号 ID：{result.get('account_id')}")
                result["account_created"] = 1
                result["account_failed"] = 0
                result["login_email"] = login_email
                result["account_name"] = account_name
                state.map_blind_oauth_account(
                    int(result.get("account_id", 0) or 0),
                    login_email,
                )
                try:
                    process.terminate()
                    process.wait(timeout=5)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass
                return result
            time.sleep(1)
        stdout_text, stderr_text = process.communicate()
        payload = _read_blind_oauth_state(state_file)
        state_payload = payload.get("state") if isinstance(payload.get("state"), dict) else {}
        stage = str(state_payload.get("stage") or "").strip()
        page_url = str(state_payload.get("current_page_url") or "").strip()
        if stage and stage != last_stage:
            emit(f"阶段：{stage}")
        if page_url and page_url != last_page:
            emit(f"页面：{page_url}")
        if process.returncode == 0:
            result = payload.get("result") if isinstance(payload, dict) else None
            if isinstance(result, dict) and int(result.get("account_id", 0) or 0) > 0:
                result["account_created"] = 1
                result["account_failed"] = 0
                result["login_email"] = login_email
                result["account_name"] = account_name
                emit(f"已导入 Sub2API，账号 ID：{result.get('account_id')}")
                return result
        raise RuntimeError(_build_blind_oauth_error(process.returncode, payload, stdout_text, stderr_text))
    finally:
        try:
            temp_env_path.unlink(missing_ok=True)
        except Exception:
            pass


def _assert_blind_oauth_import_allowed(state: WebState) -> None:
    with state.oauth_lock:
        session = dict(state.last_oauth_session or {})
    current_status = str(session.get("status") or "")
    if current_status in {"waiting_callback", "creating_account"}:
        raise RuntimeError("当前已有其他 OAuth 建号流程正在运行，请先等它结束")
    chatgpt_count = _load_stable_chatgpt_count(state)
    if chatgpt_count >= seat_core.CHATGPT_SEAT_LIMIT:
        raise RuntimeError(
            f"当前 ChatGPT 席位已达上限 {seat_core.CHATGPT_SEAT_LIMIT}，禁止再执行一键建号"
        )


def _build_random_login_email(state: WebState) -> str:
    status = oidc_status(state.load_config())
    if not bool(status.get("ok")):
        raise RuntimeError(str(status.get("error") or "OIDC 状态读取失败"))
    domains = status.get("allowed_email_domains")
    if not isinstance(domains, list) or not domains:
        raise RuntimeError("OIDC 没有可用邮箱后缀，无法自动生成登录邮箱")
    domain = str(domains[0] or "").strip().lower()
    if not domain:
        raise RuntimeError("OIDC 返回的邮箱后缀为空")
    prefix = "u" + secrets.token_hex(6)
    return f"{prefix}@{domain}"


def _load_stable_chatgpt_count(state: WebState) -> int:
    client = state.build_seat_client()
    counts: list[int] = []
    for attempt in range(3):
        users = seat_core.list_all_users(client)
        counts.append(seat_core.count_chatgpt_seats(users))
        if counts[-1] < seat_core.CHATGPT_SEAT_LIMIT:
            return counts[-1]
        if attempt < 2:
            time.sleep(1)
    return max(counts) if counts else seat_core.CHATGPT_SEAT_LIMIT


def _read_blind_oauth_state(state_file: Path) -> dict[str, Any]:
    if not state_file.exists():
        return {}
    try:
        payload = json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _build_blind_oauth_error(
    returncode: int,
    payload: dict[str, Any],
    stdout_text: str,
    stderr_text: str,
) -> str:
    state = payload.get("state") if isinstance(payload.get("state"), dict) else {}
    page_url = str(state.get("current_page_url") or "").strip()
    stage = str(state.get("stage") or "").strip()
    state_error = str(state.get("error") or "").strip()
    body_text = str(state.get("current_body_text") or "").strip()
    if "/add-phone" in page_url or "Phone number required" in body_text:
        return "自动链已推进到手机号验证页，当前还差手机号验证码，暂时无法直接导入 Sub2API"
    if "/sso" in page_url:
        return "自动链停在 SSO 页面，请检查登录邮箱、卡密后门和允许域名配置"
    if "security verification" in body_text.lower():
        return "自动链卡在 OpenAI 安全验证页，请稍后重试或更换更稳的代理环境"
    output_tail = (stderr_text or stdout_text or "").strip()[-800:]
    detail = state_error or output_tail or f"returncode={returncode}"
    if stage:
        return f"自动链失败：{stage} | {detail}"
    return f"自动链失败：{detail}"


def _pending_session_from_state_payload(
    payload: dict[str, Any],
    *,
    fallback_account_name: str,
) -> PendingOpenAIOAuthSession:
    state_payload = payload.get("state") if isinstance(payload.get("state"), dict) else {}
    pending_raw = (
        state_payload.get("pending_session")
        if isinstance(state_payload.get("pending_session"), dict)
        else {}
    )
    session_id = str(pending_raw.get("session_id") or "").strip()
    state = str(pending_raw.get("state") or "").strip()
    auth_url = str(state_payload.get("auth_url") or "").strip()
    redirect_uri = str(pending_raw.get("redirect_uri") or DEFAULT_OAUTH_REDIRECT_URI).strip()
    if not session_id or not state or not auth_url:
        raise RuntimeError("自动链状态文件缺少 pending session 信息，无法继续回填 Sub2API")
    return PendingOpenAIOAuthSession(
        session_id=session_id,
        state=state,
        auth_url=auth_url,
        account_name=str(pending_raw.get("account_name") or fallback_account_name).strip() or fallback_account_name,
        proxy_id=pending_raw.get("proxy_id"),
        proxy_name=str(pending_raw.get("proxy_name") or "").strip(),
        group_ids=[int(item) for item in (pending_raw.get("group_ids") or []) if int(item) > 0],
        redirect_uri=redirect_uri,
        concurrency=int(pending_raw.get("concurrency") or normalize_oauth_concurrency("10")),
    )


def _complete_blind_oauth_from_callback(
    state: WebState,
    remote_config,
    pending_session: PendingOpenAIOAuthSession,
    callback_url: str,
    login_email: str,
    account_name: str,
    emit,
) -> dict[str, Any]:
    emit("父任务直接回填 Sub2API")
    result = complete_openai_oauth_account_creation(
        remote_config=remote_config,
        pending_session=pending_session,
        auth_input=callback_url,
        target_status="active",
    )
    result["account_created"] = 1
    result["account_failed"] = 0
    result["login_email"] = login_email
    result["account_name"] = account_name
    state.map_blind_oauth_account(
        int(result.get("account_id", 0) or 0),
        login_email,
    )
    emit(f"已导入 Sub2API，账号 ID：{result.get('account_id')}")
    return result


def _parse_group_ids(group_ids_text: str) -> list[int]:
    group_ids: list[int] = []
    for part in group_ids_text.split(","):
        text = part.strip()
        if not text:
            continue
        try:
            gid = int(text)
        except ValueError:
            continue
        if gid > 0:
            group_ids.append(gid)
    return group_ids


def complete_oauth_from_callback(state: WebState, callback_url: str) -> dict[str, Any]:
    """Complete the pending OAuth flow from the browser callback URL."""

    return _complete_pending_oauth(state, callback_url, source="callback")


def complete_oauth_manually(state: WebState, auth_input: str) -> dict[str, Any]:
    """Manual fallback when the public callback cannot reach the WebUI."""

    return _complete_pending_oauth(state, auth_input, source="manual")


def _complete_pending_oauth(state: WebState, auth_input: str, *, source: str) -> dict[str, Any]:
    auth_input = str(auth_input or "").strip()
    if not auth_input:
        raise RuntimeError("请粘贴回调链接或 Code")
    with state.oauth_lock:
        session = state.last_oauth_session
        if not session:
            raise RuntimeError("当前没有等待中的 OAuth 授权流程")
        current_status = str(session.get("status") or "")
        if current_status == "creating_account":
            return _build_oauth_status_from_session(session, include_auth_url=False)
        if current_status == "done":
            return _build_oauth_status_from_session(session, include_auth_url=False)
        session["status"] = "creating_account"
        session["callback_url"] = auth_input
        session["updated_at"] = time.time()

    try:
        target_status = _resolve_pending_account_remote_status(
            state,
            session["pending_session"],
        )
    except Exception as exc:  # noqa: BLE001
        with state.oauth_lock:
            session["status"] = "error"
            session["error"] = str(exc)
            session["updated_at"] = time.time()
        raise

    try:
        result = complete_openai_oauth_account_creation(
            remote_config=session["remote_config"],
            pending_session=session["pending_session"],
            auth_input=auth_input,
            target_status=target_status,
        )
    except Exception as exc:  # noqa: BLE001
        with state.oauth_lock:
            session["status"] = "error"
            session["error"] = str(exc)
            session["updated_at"] = time.time()
        raise

    with state.oauth_lock:
        session["status"] = "done"
        session["result"] = result
        session["source"] = source
        session["updated_at"] = time.time()
    return _build_oauth_status_from_session(session, include_auth_url=False)


def _normalize_email(value: Any) -> str:
    return str(value or "").strip().lower()


def _resolve_pending_account_remote_status(
    state: WebState,
    pending_session: Any,
) -> str:
    account_email = _normalize_email(getattr(pending_session, "account_name", ""))
    if not account_email:
        raise RuntimeError("OAuth 账号名为空，无法在导入前判断 Sub2API 状态")
    client = state.build_seat_client()
    users = seat_core.list_all_users(client)
    matched_user = next(
        (
            user
            for user in users
            if _normalize_email(user.get("email")) == account_email
        ),
        None,
    )
    if matched_user is None:
        raise RuntimeError(f"ACC 中未找到 {account_email}，已阻止导入 Sub2API")
    if seat_core.is_chatgpt_seat_type(matched_user.get("seat_type")):
        return "active"
    return "inactive"


def build_oauth_status(state: WebState, *, include_auth_url: bool = False) -> dict[str, Any]:
    with state.oauth_lock:
        session = dict(state.last_oauth_session or {})
    return _build_oauth_status_from_session(session, include_auth_url=include_auth_url)


def _build_oauth_status_from_session(
    session: dict[str, Any],
    *,
    include_auth_url: bool = False,
) -> dict[str, Any]:
    if not session:
        return {"status": "idle"}
    pending = session.get("pending_session")
    result = session.get("result") if isinstance(session.get("result"), dict) else None
    payload = {
        "status": session.get("status") or "idle",
        "error": session.get("error") or "",
        "callback_url": session.get("callback_url") or "",
        "created_at": session.get("created_at"),
        "updated_at": session.get("updated_at"),
    }
    if pending is not None:
        payload.update(
            {
                "session_id": pending.session_id,
                "state": pending.state,
                "account_name": pending.account_name,
                "proxy_name": pending.proxy_name,
                "proxy_id": pending.proxy_id,
                "group_ids": pending.group_ids,
                "redirect_uri": pending.redirect_uri,
            }
        )
        if include_auth_url:
            payload["auth_url"] = pending.auth_url
    if result:
        payload["account_id"] = result.get("account_id")
        payload["account_name"] = result.get("account_name")
        payload["account_email"] = result.get("account_email")
        payload["post_update_error"] = result.get("post_update_error") or ""
    return payload
