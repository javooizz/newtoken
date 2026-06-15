import concurrent.futures
import json
import os
from dataclasses import dataclass, replace
from hashlib import sha256
from urllib.parse import urlsplit

from sub2api_runtime import get_app_dir
from sub2api_converter_core import (
    AccountCandidate,
    calculate_average_remaining_quota,
    extract_candidate_records_from_payload,
    normalize_http_error_body_for_display,
    request_json,
    validate_account_candidate,
)

SUB2API_CONNECTION_TEST_PATH = "/api/v1/admin/accounts?page=1&page_size=1"
SUB2API_CODEX_IMPORT_PATH = "/api/v1/admin/accounts/import/codex-session"
SUB2API_DATA_IMPORT_PATH = "/api/v1/admin/accounts/data"
SUB2API_ACCOUNTS_LIST_PATH = "/api/v1/admin/accounts"
SUB2API_ACCOUNTS_DATA_PATH = "/api/v1/admin/accounts/data?platform=openai&type=oauth&include_proxies=false"
SUB2API_DASHBOARD_STATS_PATH = "/api/v1/admin/dashboard/stats"
SUB2API_DASHBOARD_TREND_HOURLY_PATH = "/api/v1/admin/dashboard/trend?granularity=hour"
SUB2API_ACCOUNT_DELETE_PATH_TEMPLATE = "/api/v1/admin/accounts/{account_id}"
SUB2API_ACCOUNT_SET_PRIVACY_PATH_TEMPLATE = (
    "/api/v1/admin/accounts/{account_id}/set-privacy"
)
SUB2API_BULK_UPDATE_PATH = "/api/v1/admin/accounts/bulk-update"
SUB2API_GROUPS_LIST_PATH = "/api/v1/admin/groups?page=1&page_size=200"
DEFAULT_IMPORT_UPDATE_EXISTING = True
DEFAULT_IMPORT_SKIP_DEFAULT_GROUP_BIND = False
DEFAULT_IMPORT_CONFIRM_MIXED_CHANNEL_RISK = False
REMOTE_DELETE_CONCURRENCY = 10
DEFAULT_OPENAI_IMPORT_GROUP_NAME = "cc"
DEFAULT_OPENAI_IMPORT_CONCURRENCY = 50
DEFAULT_OPENAI_ACCOUNT_STATUS = "active"
DEFAULT_OPENAI_OAUTH_WS_MODE = "passthrough"


@dataclass
class RemoteAccountEntry:
    """保存远程账号的 ID、名称和完整凭据记录。"""

    account_id: int
    name: str
    record: dict


@dataclass
class Sub2APIRemoteConfig:
    """保存远程 Sub2API 导入所需的管理员接口配置。"""

    base_url: str
    admin_api_key: str
    group_ids: list[int]
    proxy_id: int | None = None
    concurrency: int | None = None
    priority: int | None = None
    update_existing: bool = DEFAULT_IMPORT_UPDATE_EXISTING
    skip_default_group_bind: bool = DEFAULT_IMPORT_SKIP_DEFAULT_GROUP_BIND
    confirm_mixed_channel_risk: bool = (
        DEFAULT_IMPORT_CONFIRM_MIXED_CHANNEL_RISK
    )


def parse_dotenv_file(env_path):
    """按 UTF-8 解析简单 .env 文件，只支持 KEY=VALUE 结构。"""

    values = {}
    if not os.path.exists(env_path):
        return values
    with open(env_path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                values[key] = value
    return values


def parse_bool_text(raw_value, default=False):
    """把文本布尔值转成 bool，空值时回退到默认值。"""

    text = (raw_value or "").strip().lower()
    if not text:
        return default
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def parse_int_list_text(raw_value):
    """把逗号分隔的数字文本解析成 int 列表。"""

    if not isinstance(raw_value, str):
        return []
    values = []
    for part in raw_value.split(","):
        text = part.strip()
        if not text:
            continue
        values.append(int(text))
    return values


def parse_optional_int_text(raw_value):
    """把可选数字文本解析成 int 或 None。"""

    text = (raw_value or "").strip()
    if not text:
        return None
    return int(text)


def resolve_env_file_path(env_path):
    """把 .env 路径解析到当前脚本目录，避免从别的目录启动时丢配置。"""

    if os.path.isabs(env_path):
        return env_path
    project_dir = get_app_dir(__file__)
    return os.path.join(str(project_dir), env_path)


def load_remote_import_defaults(env_path=".env"):
    """从 .env 读取远程导入默认配置，避免把密钥写进代码。"""

    values = parse_dotenv_file(resolve_env_file_path(env_path))
    return {
        "base_url": values.get("SUB2API_BASE_URL", "").strip(),
        "admin_api_key": values.get("SUB2API_ADMIN_API_KEY", "").strip(),
        "group_ids": values.get("SUB2API_GROUP_IDS", "").strip(),
        "proxy_id": values.get("SUB2API_PROXY_ID", "").strip(),
        "concurrency": values.get("SUB2API_IMPORT_CONCURRENCY", "").strip(),
        "priority": values.get("SUB2API_IMPORT_PRIORITY", "").strip(),
        "update_existing": parse_bool_text(
            values.get("SUB2API_UPDATE_EXISTING", ""),
            default=DEFAULT_IMPORT_UPDATE_EXISTING,
        ),
        "skip_default_group_bind": parse_bool_text(
            values.get("SUB2API_SKIP_DEFAULT_GROUP_BIND", ""),
            default=DEFAULT_IMPORT_SKIP_DEFAULT_GROUP_BIND,
        ),
        "confirm_mixed_channel_risk": parse_bool_text(
            values.get("SUB2API_CONFIRM_MIXED_CHANNEL_RISK", ""),
            default=DEFAULT_IMPORT_CONFIRM_MIXED_CHANNEL_RISK,
        ),
    }


def normalize_sub2api_base_url(base_url):
    """规范化远程地址，保留可能存在的反向代理子路径。"""

    normalized = (base_url or "").strip().rstrip("/")
    if not normalized:
        raise ValueError("请填写 Sub2API 服务器地址")
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("服务器地址必须是 http:// 或 https:// 开头的完整地址")
    return normalized


def build_sub2api_admin_url(base_url, path):
    """拼出管理员接口完整 URL，兼容带子路径部署。"""

    normalized_base_url = normalize_sub2api_base_url(base_url)
    return f"{normalized_base_url}{path}"


def build_sub2api_admin_headers(admin_api_key):
    """生成管理员接口请求头。"""

    key = (admin_api_key or "").strip()
    if not key:
        raise ValueError("请填写管理员 API Key")
    return {"x-api-key": key, "Accept": "application/json"}


def mask_secret_value(secret):
    """把敏感值压缩成可日志展示的短格式。"""

    text = (secret or "").strip()
    if len(text) <= 10:
        return "*" * len(text)
    return f"{text[:6]}...{text[-4:]}"


def build_remote_config(
    base_url,
    admin_api_key,
    group_ids_text="",
    proxy_id_text="",
    concurrency_text="",
    priority_text="",
    update_existing=DEFAULT_IMPORT_UPDATE_EXISTING,
    skip_default_group_bind=DEFAULT_IMPORT_SKIP_DEFAULT_GROUP_BIND,
    confirm_mixed_channel_risk=DEFAULT_IMPORT_CONFIRM_MIXED_CHANNEL_RISK,
):
    """把界面输入整理成远程导入配置对象。"""

    normalized_api_key = (admin_api_key or "").strip()
    if not normalized_api_key:
        raise ValueError("请填写管理员 API Key")
    return Sub2APIRemoteConfig(
        base_url=normalize_sub2api_base_url(base_url),
        admin_api_key=normalized_api_key,
        group_ids=parse_int_list_text(group_ids_text),
        proxy_id=parse_optional_int_text(proxy_id_text),
        concurrency=parse_optional_int_text(concurrency_text),
        priority=parse_optional_int_text(priority_text),
        update_existing=bool(update_existing),
        skip_default_group_bind=bool(skip_default_group_bind),
        confirm_mixed_channel_risk=bool(confirm_mixed_channel_risk),
    )


def fetch_remote_groups(config):
    """读取远程分组列表，供自动解析默认分组 ID 使用。"""

    url = build_sub2api_admin_url(config.base_url, SUB2API_GROUPS_LIST_PATH)
    status_code, body_text, payload = request_json(
        url,
        headers=build_sub2api_admin_headers(config.admin_api_key),
    )
    if status_code < 200 or status_code >= 300:
        raise RuntimeError(
            build_remote_error_message("读取远程分组列表", status_code, body_text, payload)
        )
    data = unwrap_sub2api_response(payload)
    if not isinstance(data, dict):
        raise RuntimeError("远程分组列表返回格式不符合预期")
    return data.get("items") or []


def resolve_openai_import_group_ids(config):
    """解析 OpenAI 一键导入默认分组，优先使用显式配置，否则自动找 cc。"""

    if config.group_ids:
        return list(config.group_ids)
    for item in fetch_remote_groups(config):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip().lower()
        platform = str(item.get("platform", "")).strip().lower()
        group_id = int(item.get("id", 0) or 0)
        if (
            group_id > 0
            and name == DEFAULT_OPENAI_IMPORT_GROUP_NAME
            and platform == "openai"
        ):
            return [group_id]
    raise RuntimeError("未找到名为 cc 的 OpenAI 分组，请先在远程后台确认分组")


def build_effective_openai_import_config(config):
    """为 OpenAI 一键导入补齐默认分组和并发。"""

    return replace(
        config,
        group_ids=resolve_openai_import_group_ids(config),
        concurrency=config.concurrency or DEFAULT_OPENAI_IMPORT_CONCURRENCY,
    )


def extract_import_records_from_payload_text(payload_text):
    """从缓存 JSON 文本提取可供 Sub2API 导入的 CAP 账号数组。"""

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"缓存结果不是合法 JSON: {exc}") from exc
    records = extract_candidate_records_from_payload(payload)
    if not records:
        raise ValueError("缓存结果里没有可导入的账号")
    return records


def parse_payload_text(payload_text):
    """把缓存 JSON 文本解析为对象，失败时抛出可读错误。"""

    try:
        return json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"缓存结果不是合法 JSON: {exc}") from exc


def is_sub2api_data_payload(payload):
    """判断当前 JSON 是否是 Sub2API 原生聚合结构。"""

    return (
        isinstance(payload, dict)
        and payload.get("type") == "sub2api-data"
        and isinstance(payload.get("accounts"), list)
    )


def build_codex_session_import_request(payload_text, config):
    """按官方 import/codex-session 契约构造请求体。"""

    records = extract_import_records_from_payload_text(payload_text)
    request_body = {
        "content": json.dumps(records, ensure_ascii=False),
        "update_existing": config.update_existing,
        "skip_default_group_bind": config.skip_default_group_bind,
        "confirm_mixed_channel_risk": config.confirm_mixed_channel_risk,
    }
    if config.group_ids:
        request_body["group_ids"] = config.group_ids
    if config.proxy_id is not None:
        request_body["proxy_id"] = config.proxy_id
    if config.concurrency is not None:
        request_body["concurrency"] = config.concurrency
    if config.priority is not None:
        request_body["priority"] = config.priority
    return request_body


def build_data_import_request(payload, config):
    """按 Sub2API 原生 /accounts/data 契约构造请求体。"""

    if not is_sub2api_data_payload(payload):
        raise ValueError("当前 JSON 不是可直接导入的 Sub2API 聚合结构")
    return {
        "data": payload,
        "skip_default_group_bind": config.skip_default_group_bind,
    }


def extract_imported_account_ids(items):
    """从导入结果里提取成功落库的账号 ID。"""

    account_ids = []
    seen = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        try:
            account_id = int(item.get("account_id", 0) or 0)
        except (TypeError, ValueError):
            account_id = 0
        if account_id <= 0 or account_id in seen:
            continue
        seen.add(account_id)
        account_ids.append(account_id)
    return account_ids


def build_openai_post_import_update_payload(config, account_ids):
    """构造 OpenAI 导入后自动批量更新配置。"""

    payload = {
        "account_ids": account_ids,
        "concurrency": config.concurrency or DEFAULT_OPENAI_IMPORT_CONCURRENCY,
        "status": DEFAULT_OPENAI_ACCOUNT_STATUS,
        "group_ids": list(config.group_ids),
        "extra": {
            "openai_passthrough": True,
            "openai_oauth_responses_websockets_v2_mode": DEFAULT_OPENAI_OAUTH_WS_MODE,
            "openai_oauth_responses_websockets_v2_enabled": True,
        },
    }
    if config.confirm_mixed_channel_risk:
        payload["confirm_mixed_channel_risk"] = True
    return payload


def fingerprint_secret(value):
    """对敏感 token 做稳定指纹，避免把原文直接拿来做匹配键。"""

    text = str(value or "").strip()
    if not text:
        return ""
    return sha256(text.encode("utf-8")).hexdigest()


def normalize_remote_identity_text(value):
    """把身份字段压成稳定小写文本，方便跨接口匹配。"""

    return str(value or "").strip().lower()


def build_openai_account_match_keys(name, credentials):
    """构造远程账号匹配键，优先按 user_id 和 email 识别账号。"""

    credentials = credentials or {}
    if not isinstance(credentials, dict):
        credentials = {}
    keys = []
    user_id = normalize_remote_identity_text(credentials.get("chatgpt_user_id", ""))
    email = normalize_remote_identity_text(
        credentials.get("email", "") or name or ""
    )
    refresh_fingerprint = fingerprint_secret(credentials.get("refresh_token", ""))
    access_fingerprint = fingerprint_secret(credentials.get("access_token", ""))
    if user_id:
        keys.append(f"user:{user_id}")
    if email:
        keys.append(f"email:{email}")
    if refresh_fingerprint:
        keys.append(f"refresh:{refresh_fingerprint}")
    if access_fingerprint:
        keys.append(f"access:{access_fingerprint}")
    return keys


def build_remote_account_lookup(list_items):
    """把远程账号列表整理成可按 user_id/email/token 回查的索引。"""

    lookup = {}
    for item in list_items or []:
        if not isinstance(item, dict):
            continue
        try:
            account_id = int(item.get("id", 0) or 0)
        except (TypeError, ValueError):
            account_id = 0
        if account_id <= 0:
            continue
        for key in build_openai_account_match_keys(
            item.get("name", ""),
            item.get("credentials"),
        ):
            lookup.setdefault(key, account_id)
    return lookup


def find_existing_remote_account_id(lookup, account):
    """按 user_id/email/token 匹配本地账号是否已存在于远程。"""

    if not isinstance(account, dict):
        return 0
    for key in build_openai_account_match_keys(
        account.get("name", ""),
        account.get("credentials"),
    ):
        account_id = int(lookup.get(key, 0) or 0)
        if account_id > 0:
            return account_id
    return 0


def build_account_display_name(account, fallback_index):
    """提取日志展示名，尽量让用户能定位具体账号。"""

    if not isinstance(account, dict):
        return f"account-{fallback_index}"
    name = str(account.get("name", "")).strip()
    if name:
        return name
    credentials = account.get("credentials") or {}
    if isinstance(credentials, dict):
        email = str(credentials.get("email", "")).strip()
        if email:
            return email
    return f"account-{fallback_index}"


def detect_shared_chatgpt_account_ids(accounts):
    """识别共享 chatgpt_account_id 的批次，便于切换安全导入链路。"""

    owners_by_account_id = {}
    for index, account in enumerate(accounts or [], start=1):
        if not isinstance(account, dict):
            continue
        credentials = account.get("credentials") or {}
        if not isinstance(credentials, dict):
            continue
        account_id = normalize_remote_identity_text(
            credentials.get("chatgpt_account_id", "")
        )
        if not account_id:
            continue
        owner_key = (
            normalize_remote_identity_text(credentials.get("chatgpt_user_id", ""))
            or normalize_remote_identity_text(credentials.get("email", ""))
            or normalize_remote_identity_text(account.get("name", ""))
            or f"access:{fingerprint_secret(credentials.get('access_token', ''))}"
            or f"row:{index}"
        )
        owners_by_account_id.setdefault(account_id, set()).add(owner_key)
    return {
        account_id: len(owner_keys)
        for account_id, owner_keys in owners_by_account_id.items()
        if len(owner_keys) > 1
    }


def build_sub2api_data_import_plan(payload, remote_list_items):
    """为 /accounts/data 导入生成创建集合和远程复用集合。"""

    if not is_sub2api_data_payload(payload):
        raise ValueError("当前 JSON 不是可直接导入的 Sub2API 聚合结构")
    accounts = [
        item for item in (payload.get("accounts") or []) if isinstance(item, dict)
    ]
    remote_lookup = build_remote_account_lookup(remote_list_items)
    import_accounts = []
    reused_items = []
    reused_account_ids = []
    reused_seen = set()
    for index, account in enumerate(accounts, start=1):
        existing_account_id = find_existing_remote_account_id(remote_lookup, account)
        if existing_account_id > 0:
            if existing_account_id not in reused_seen:
                reused_account_ids.append(existing_account_id)
                reused_seen.add(existing_account_id)
            reused_items.append(
                {
                    "index": index,
                    "name": build_account_display_name(account, index),
                    "action": "reused",
                    "account_id": existing_account_id,
                    "message": "远程已存在同 user_id/email 的账号，本次复用已有账号",
                }
            )
            continue
        import_accounts.append(account)
    import_payload = dict(payload)
    import_payload["accounts"] = import_accounts
    return {
        "total_accounts": len(accounts),
        "import_payload": import_payload,
        "import_accounts": import_accounts,
        "reused_items": reused_items,
        "reused_account_ids": reused_account_ids,
        "shared_account_ids": detect_shared_chatgpt_account_ids(accounts),
    }


def resolve_sub2api_data_account_ids(accounts, remote_list_items):
    """根据最新远程列表回查本地 Sub 账号对应的远程 ID。"""

    lookup = build_remote_account_lookup(remote_list_items)
    account_ids = []
    seen = set()
    for account in accounts or []:
        account_id = find_existing_remote_account_id(lookup, account)
        if account_id <= 0 or account_id in seen:
            continue
        seen.add(account_id)
        account_ids.append(account_id)
    return account_ids


def import_sub2api_data_payload(config, payload):
    """调用 /accounts/data 原生导入 Sub 聚合 JSON。"""

    url = build_sub2api_admin_url(config.base_url, SUB2API_DATA_IMPORT_PATH)
    request_body = build_data_import_request(payload, config)
    status_code, body_text, response_payload = request_json(
        url,
        method="POST",
        headers=build_sub2api_admin_headers(config.admin_api_key),
        json_body=request_body,
    )
    if status_code < 200 or status_code >= 300:
        raise RuntimeError(
            build_remote_error_message(
                "上传 Sub 聚合 JSON", status_code, body_text, response_payload
            )
        )
    data = unwrap_sub2api_response(response_payload)
    if not isinstance(data, dict):
        raise RuntimeError("Sub 聚合 JSON 导入成功但返回结果格式不符合预期")
    return {
        "url": url,
        "request_body": request_body,
        "proxy_created": int(data.get("proxy_created", 0)),
        "proxy_reused": int(data.get("proxy_reused", 0)),
        "proxy_failed": int(data.get("proxy_failed", 0)),
        "account_created": int(data.get("account_created", 0)),
        "account_failed": int(data.get("account_failed", 0)),
        "errors": data.get("errors") or [],
    }


def bulk_update_remote_accounts(config, update_payload):
    """调用远程 bulk-update 接口批量更新账号属性。"""

    url = build_sub2api_admin_url(config.base_url, SUB2API_BULK_UPDATE_PATH)
    status_code, body_text, payload = request_json(
        url,
        method="POST",
        headers=build_sub2api_admin_headers(config.admin_api_key),
        json_body=update_payload,
    )
    if status_code < 200 or status_code >= 300:
        raise RuntimeError(
            build_remote_error_message("批量更新远程账号", status_code, body_text, payload)
        )
    data = unwrap_sub2api_response(payload)
    if not isinstance(data, dict):
        raise RuntimeError("批量更新成功但返回结果格式不符合预期")
    return {
        "url": url,
        "success": int(data.get("success", 0)),
        "failed": int(data.get("failed", 0)),
        "success_ids": data.get("success_ids") or [],
        "failed_ids": data.get("failed_ids") or [],
        "results": data.get("results") or [],
    }


def unwrap_sub2api_response(payload):
    """解开 Sub2API 标准响应壳，失败时抛出可读异常。"""

    if not isinstance(payload, dict):
        raise RuntimeError("Sub2API 返回了非 JSON 对象")
    if payload.get("code") not in (0, None):
        raise RuntimeError(payload.get("message") or "Sub2API 返回失败")
    return payload.get("data")


def build_remote_error_message(action_label, status_code, body_text, payload):
    """把远程接口错误整理成一行易读消息。"""

    if isinstance(payload, dict) and payload.get("message"):
        detail = str(payload["message"]).strip()
    else:
        detail = normalize_http_error_body_for_display(body_text)
    return f"{action_label}失败 HTTP {status_code} [{detail}]"


def build_remote_account_identity(name, credentials):
    """为远程账号构建稳定标识，便于列表和导出结果做匹配。"""

    credentials = credentials or {}
    if not isinstance(credentials, dict):
        credentials = {}
    return "||".join(
        [
            str(credentials.get("chatgpt_account_id", "")).strip().lower(),
            str(credentials.get("chatgpt_user_id", "")).strip().lower(),
            str(credentials.get("email", "")).strip().lower(),
            str(name or "").strip().lower(),
        ]
    )


def extract_remote_record(account_item):
    """从 Sub2API 导出账号中提取本地校验所需的 CAP 结构。"""

    credentials = account_item.get("credentials") or {}
    if not isinstance(credentials, dict):
        credentials = {}
    return {
        "access_token": str(credentials.get("access_token", "")).strip(),
        "refresh_token": str(credentials.get("refresh_token", "")).strip(),
        "id_token": str(credentials.get("id_token", "")).strip(),
        "email": str(
            credentials.get("email", "") or account_item.get("name", "")
        ).strip(),
    }


def fetch_remote_account_list(config):
    """读取远程 OpenAI OAuth 账号列表，用于拿到账号 ID 和基础信息。"""

    account_items = []
    page = 1
    headers = build_sub2api_admin_headers(config.admin_api_key)
    while True:
        path = (
            f"{SUB2API_ACCOUNTS_LIST_PATH}?platform=openai&type=oauth"
            f"&page={page}&page_size=1000&sort_by=name&sort_order=asc"
        )
        url = build_sub2api_admin_url(config.base_url, path)
        status_code, body_text, payload = request_json(url, headers=headers)
        if status_code < 200 or status_code >= 300:
            raise RuntimeError(
                build_remote_error_message("读取远程账号列表", status_code, body_text, payload)
            )
        data = unwrap_sub2api_response(payload)
        if not isinstance(data, dict):
            raise RuntimeError("远程账号列表返回格式不符合预期")
        items = data.get("items") or []
        account_items.extend(item for item in items if isinstance(item, dict))
        total = int(data.get("total", len(account_items)))
        if len(account_items) >= total or not items:
            break
        page += 1
    return account_items


def fetch_remote_account_export_data(config):
    """导出远程 OpenAI OAuth 账号完整凭据数据。"""

    url = build_sub2api_admin_url(config.base_url, SUB2API_ACCOUNTS_DATA_PATH)
    status_code, body_text, payload = request_json(
        url,
        headers=build_sub2api_admin_headers(config.admin_api_key),
    )
    if status_code < 200 or status_code >= 300:
        raise RuntimeError(
            build_remote_error_message("导出远程账号数据", status_code, body_text, payload)
        )
    data = unwrap_sub2api_response(payload)
    if not isinstance(data, dict):
        raise RuntimeError("远程账号导出数据格式不符合预期")
    return data.get("accounts") or []


def fetch_remote_dashboard_stats(config):
    """读取远程管理台总览统计，用于拿今日 Token。"""

    url = build_sub2api_admin_url(config.base_url, SUB2API_DASHBOARD_STATS_PATH)
    status_code, body_text, payload = request_json(
        url,
        headers=build_sub2api_admin_headers(config.admin_api_key),
    )
    if status_code < 200 or status_code >= 300:
        raise RuntimeError(
            build_remote_error_message(
                "读取远程总览统计", status_code, body_text, payload
            )
        )
    data = unwrap_sub2api_response(payload)
    if not isinstance(data, dict):
        raise RuntimeError("远程总览统计返回格式不符合预期")
    return data


def fetch_remote_dashboard_hourly_trend(config):
    """读取远程管理台小时趋势，用于拿最近一小时 Token。"""

    url = build_sub2api_admin_url(config.base_url, SUB2API_DASHBOARD_TREND_HOURLY_PATH)
    status_code, body_text, payload = request_json(
        url,
        headers=build_sub2api_admin_headers(config.admin_api_key),
    )
    if status_code < 200 or status_code >= 300:
        raise RuntimeError(
            build_remote_error_message(
                "读取远程小时趋势", status_code, body_text, payload
            )
        )
    data = unwrap_sub2api_response(payload)
    if not isinstance(data, dict):
        raise RuntimeError("远程小时趋势返回格式不符合预期")
    trend_items = data.get("trend") or []
    return [item for item in trend_items if isinstance(item, dict)]


def parse_remote_int_value(raw_value):
    """把远程接口里的数字安全转成 int，失败时回退到 0。"""

    try:
        return int(raw_value or 0)
    except (TypeError, ValueError):
        return 0


def extract_recent_hour_tokens_from_trend(trend_items, limit=2):
    """从小时趋势里提取最近几个有效小时桶的 Token 数。"""

    valid_items = []
    for item in trend_items or []:
        if not isinstance(item, dict):
            continue
        date_text = str(item.get("date", "")).strip()
        if not date_text:
            continue
        valid_items.append((date_text, item))
    if not valid_items:
        return []
    valid_items.sort(key=lambda pair: pair[0], reverse=True)
    return [
        parse_remote_int_value(item.get("total_tokens", 0))
        for _date_text, item in valid_items[: max(int(limit or 0), 0)]
    ]


def fetch_remote_token_usage_summary(config):
    """读取远程今日 Token 和最近两小时 Token，单项失败不影响另一项。"""

    summary = {
        "today_tokens": None,
        "last_hour_tokens": None,
        "previous_hour_tokens": None,
        "token_stats_error": "",
    }
    errors = []

    try:
        dashboard_stats = fetch_remote_dashboard_stats(config)
        summary["today_tokens"] = parse_remote_int_value(
            dashboard_stats.get("today_tokens", 0)
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))

    try:
        hourly_trend = fetch_remote_dashboard_hourly_trend(config)
        recent_hour_tokens = extract_recent_hour_tokens_from_trend(hourly_trend, limit=2)
        if recent_hour_tokens:
            summary["last_hour_tokens"] = recent_hour_tokens[0]
        if len(recent_hour_tokens) > 1:
            summary["previous_hour_tokens"] = recent_hour_tokens[1]
    except Exception as exc:  # noqa: BLE001
        errors.append(str(exc))

    if errors:
        summary["token_stats_error"] = "；".join(errors)
    return summary


def merge_remote_accounts(list_items, export_accounts):
    """把远程列表 ID 和导出凭据数据按身份字段匹配到一起。"""

    export_map = {}
    fallback_items = []
    for account_item in export_accounts:
        if not isinstance(account_item, dict):
            continue
        identity = build_remote_account_identity(
            account_item.get("name", ""),
            account_item.get("credentials"),
        )
        if identity and identity not in export_map:
            export_map[identity] = account_item
        else:
            fallback_items.append(account_item)

    merged_accounts = []
    unmatched_names = []
    for order, list_item in enumerate(list_items):
        identity = build_remote_account_identity(
            list_item.get("name", ""),
            list_item.get("credentials"),
        )
        export_item = export_map.pop(identity, None) if identity else None
        if export_item is None and fallback_items:
            export_item = fallback_items.pop(0)
        if export_item is None:
            unmatched_names.append(str(list_item.get("name", "")).strip() or f"#{order + 1}")
            continue
        merged_accounts.append(
            RemoteAccountEntry(
                account_id=int(list_item.get("id", 0)),
                name=str(list_item.get("name", "")).strip() or f"remote-{order + 1}",
                record=extract_remote_record(export_item),
            )
        )
    return merged_accounts, unmatched_names


def scan_remote_accounts(config):
    """拉取远程账号并按现有额度校验逻辑统计活号、死号和平均额度。"""

    token_usage_summary = fetch_remote_token_usage_summary(config)
    list_items = fetch_remote_account_list(config)
    export_accounts = fetch_remote_account_export_data(config)
    remote_entries, unmatched_names = merge_remote_accounts(list_items, export_accounts)
    candidates = [
        AccountCandidate(
            order=index,
            folder_name="sub2api-remote",
            file_name=entry.name,
            file_path=f"remote://{entry.account_id}",
            record=entry.record,
        )
        for index, entry in enumerate(remote_entries)
    ]
    results = []
    dead_items = []
    no_quota_items = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=DEFAULT_OPENAI_IMPORT_CONCURRENCY
    ) as executor:
        future_map = {
            executor.submit(validate_account_candidate, candidate): entry
            for candidate, entry in zip(candidates, remote_entries, strict=False)
        }
        for future in concurrent.futures.as_completed(future_map):
            entry = future_map[future]
            result = future.result()
            results.append((entry, result))
            if result.status != "ok":
                item = {
                    "account_id": entry.account_id,
                    "name": entry.name,
                    "email": result.email,
                    "status": result.status,
                    "reason": result.reason,
                }
                if is_remote_no_quota_item(item):
                    no_quota_items.append(item)
                else:
                    dead_items.append(item)

    usable_results = [
        result for _entry, result in results if result.status == "ok"
    ]
    return {
        "total_count": len(remote_entries),
        "alive_count": len(usable_results),
        "dead_count": len(dead_items),
        "no_quota_count": len(no_quota_items),
        "average_remaining_quota": calculate_average_remaining_quota(usable_results),
        "today_tokens": token_usage_summary.get("today_tokens"),
        "last_hour_tokens": token_usage_summary.get("last_hour_tokens"),
        "previous_hour_tokens": token_usage_summary.get("previous_hour_tokens"),
        "token_stats_error": token_usage_summary.get("token_stats_error", ""),
        "dead_items": sorted(dead_items, key=lambda item: item["name"].lower()),
        "no_quota_items": sorted(
            no_quota_items, key=lambda item: item["name"].lower()
        ),
        "unmatched_names": unmatched_names,
    }


def delete_remote_account(config, account_id):
    """删除一个远程账号。"""

    path = SUB2API_ACCOUNT_DELETE_PATH_TEMPLATE.format(account_id=account_id)
    url = build_sub2api_admin_url(config.base_url, path)
    status_code, body_text, payload = request_json(
        url,
        method="DELETE",
        headers=build_sub2api_admin_headers(config.admin_api_key),
    )
    if status_code < 200 or status_code >= 300:
        raise RuntimeError(
            build_remote_error_message("删除远程账号", status_code, body_text, payload)
        )
    if isinstance(payload, dict) and payload.get("code") not in (0, None):
        raise RuntimeError(payload.get("message") or f"删除账号 {account_id} 失败")
    return {"account_id": account_id, "url": url}


def extract_remote_account_privacy_mode(account_payload):
    """从隐私接口返回的账号对象里提取 privacy_mode。"""

    if not isinstance(account_payload, dict):
        return ""
    privacy_mode = str(account_payload.get("privacy_mode", "")).strip()
    if privacy_mode:
        return privacy_mode
    extra = account_payload.get("extra")
    if isinstance(extra, dict):
        return str(extra.get("privacy_mode", "")).strip()
    return ""


def set_remote_account_privacy(config, account_id, name=""):
    """调用远程单账号隐私接口。"""

    path = SUB2API_ACCOUNT_SET_PRIVACY_PATH_TEMPLATE.format(account_id=account_id)
    url = build_sub2api_admin_url(config.base_url, path)
    status_code, body_text, payload = request_json(
        url,
        method="POST",
        headers=build_sub2api_admin_headers(config.admin_api_key),
    )
    if status_code < 200 or status_code >= 300:
        raise RuntimeError(
            build_remote_error_message("设置账号隐私", status_code, body_text, payload)
        )
    data = unwrap_sub2api_response(payload)
    return {
        "account_id": account_id,
        "name": name,
        "url": url,
        "privacy_mode": extract_remote_account_privacy_mode(data),
    }


def set_all_remote_openai_account_privacy(config):
    """先拉取远程 OpenAI OAuth 账号，再逐个设置隐私。"""

    account_items = fetch_remote_account_list(config)
    results = []
    for order, account_item in enumerate(account_items, start=1):
        account_id = int(account_item.get("id", 0) or 0)
        name = str(account_item.get("name", "")).strip() or f"remote-{order}"
        if account_id <= 0:
            results.append(
                {
                    "account_id": account_id,
                    "name": name,
                    "success": False,
                    "privacy_mode": "",
                    "error": "远程账号缺少有效 id",
                }
            )
            continue
        try:
            privacy_result = set_remote_account_privacy(config, account_id, name)
            results.append(
                {
                    "account_id": account_id,
                    "name": name,
                    "success": True,
                    "privacy_mode": privacy_result.get("privacy_mode", ""),
                    "error": "",
                }
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "account_id": account_id,
                    "name": name,
                    "success": False,
                    "privacy_mode": "",
                    "error": str(exc),
                }
            )
    success = sum(1 for item in results if item["success"])
    failed = len(results) - success
    return {
        "total": len(results),
        "success": success,
        "failed": failed,
        "items": results,
    }


def is_remote_no_quota_item(item):
    """判断远程扫描项是否属于“无可用额度”，而不是死号。"""

    if not isinstance(item, dict):
        return False
    reason = str(item.get("reason", "")).strip().lower()
    return "无可用额度" in reason or "最小剩余额度" in reason


def select_remote_accounts_without_quota(dead_items):
    """从远程扫描结果列表里筛出无可用额度账号。"""

    selected_items = []
    for item in dead_items or []:
        if not isinstance(item, dict):
            continue
        if is_remote_no_quota_item(item):
            selected_items.append(item)
    return selected_items


def select_remote_accounts_with_auth_error(dead_items):
    """从远程死号列表里筛出 401/402 这类已失效账号。"""

    selected_items = []
    keywords = (
        "http 401",
        "http 402",
        "token_invalidated",
        "token_revoked",
        "authentication token has been invalidated",
        "invalidated oauth token",
        "payment required",
    )
    for item in dead_items or []:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status", "")).strip().lower()
        reason = str(item.get("reason", "")).strip().lower()
        if status == "auth_error" or any(keyword in reason for keyword in keywords):
            selected_items.append(item)
    return selected_items


def delete_dead_remote_accounts(config, dead_items):
    """批量删除已识别为死号的远程账号。"""

    if not dead_items:
        return {"deleted": 0, "failed": 0, "items": []}
    results = []
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=REMOTE_DELETE_CONCURRENCY
    ) as executor:
        future_map = {
            executor.submit(delete_remote_account, config, item["account_id"]): item
            for item in dead_items
        }
        for future in concurrent.futures.as_completed(future_map):
            item = future_map[future]
            try:
                future.result()
                results.append(
                    {
                        "account_id": item["account_id"],
                        "name": item["name"],
                        "success": True,
                        "error": "",
                    }
                )
            except Exception as exc:  # noqa: BLE001
                results.append(
                    {
                        "account_id": item["account_id"],
                        "name": item["name"],
                        "success": False,
                        "error": str(exc),
                    }
                )
    deleted = sum(1 for item in results if item["success"])
    failed = len(results) - deleted
    return {"deleted": deleted, "failed": failed, "items": results}


def test_sub2api_connection(config):
    """测试管理员 API 是否可访问且密钥有效。"""

    url = build_sub2api_admin_url(config.base_url, SUB2API_CONNECTION_TEST_PATH)
    status_code, body_text, payload = request_json(
        url,
        headers=build_sub2api_admin_headers(config.admin_api_key),
    )
    if status_code < 200 or status_code >= 300:
        raise RuntimeError(
            build_remote_error_message("连接测试", status_code, body_text, payload)
        )
    data = unwrap_sub2api_response(payload)
    return {
        "url": url,
        "account_total": (
            data.get("total") if isinstance(data, dict) else None
        ),
    }


def import_to_sub2api_codex_session(config, payload_text):
    """把缓存结果一键导入到远程 Sub2API 后台。"""

    effective_config = build_effective_openai_import_config(config)
    parsed_payload = parse_payload_text(payload_text)
    if is_sub2api_data_payload(parsed_payload):
        remote_list_before = fetch_remote_account_list(effective_config)
        import_plan = build_sub2api_data_import_plan(parsed_payload, remote_list_before)
        import_result = {
            "url": build_sub2api_admin_url(config.base_url, SUB2API_DATA_IMPORT_PATH),
            "request_body": {},
            "proxy_created": 0,
            "proxy_reused": 0,
            "proxy_failed": 0,
            "account_created": 0,
            "account_failed": 0,
            "errors": [],
        }
        warnings = []
        if import_plan["shared_account_ids"]:
            warnings.append(
                {
                    "index": 0,
                    "name": "",
                    "message": (
                        "检测到共享 chatgpt_account_id 的批次，"
                        "已自动切换为 /accounts/data 原生导入，避免 codex-session 误判重复。"
                        f"共享 account_id 数量: {len(import_plan['shared_account_ids'])}"
                    ),
                }
            )
        if import_plan["import_accounts"]:
            import_result = import_sub2api_data_payload(
                effective_config,
                import_plan["import_payload"],
            )
        remote_list_after = fetch_remote_account_list(effective_config)
        resolved_account_ids = resolve_sub2api_data_account_ids(
            parsed_payload.get("accounts") or [],
            remote_list_after,
        )
        post_import_update = None
        if resolved_account_ids:
            post_import_update = bulk_update_remote_accounts(
                effective_config,
                build_openai_post_import_update_payload(
                    effective_config,
                    resolved_account_ids,
                ),
            )
        error_items = []
        for error in import_result["errors"]:
            if not isinstance(error, dict):
                continue
            error_items.append(
                {
                    "index": 0,
                    "name": str(error.get("name", "")).strip(),
                    "message": str(error.get("message", "")).strip(),
                }
            )
        return {
            "url": import_result["url"],
            "request_body": import_result["request_body"],
            "import_strategy": "data",
            "reused": len(import_plan["reused_account_ids"]),
            "total": import_plan["total_accounts"],
            "created": import_result["account_created"],
            "updated": 0,
            "skipped": 0,
            "failed": import_result["account_failed"],
            "items": import_plan["reused_items"],
            "warnings": warnings,
            "errors": error_items,
            "applied_group_ids": list(effective_config.group_ids),
            "applied_concurrency": effective_config.concurrency,
            "post_import_update": post_import_update,
        }
    url = build_sub2api_admin_url(config.base_url, SUB2API_CODEX_IMPORT_PATH)
    request_body = build_codex_session_import_request(payload_text, effective_config)
    status_code, body_text, payload = request_json(
        url,
        method="POST",
        headers=build_sub2api_admin_headers(effective_config.admin_api_key),
        json_body=request_body,
    )
    if status_code < 200 or status_code >= 300:
        raise RuntimeError(
            build_remote_error_message("一键导入", status_code, body_text, payload)
        )
    data = unwrap_sub2api_response(payload)
    if not isinstance(data, dict):
        raise RuntimeError("导入成功但返回结果格式不符合预期")
    items = data.get("items") or []
    imported_account_ids = extract_imported_account_ids(items)
    post_import_update = None
    if imported_account_ids:
        post_import_update = bulk_update_remote_accounts(
            effective_config,
            build_openai_post_import_update_payload(
                effective_config,
                imported_account_ids,
            ),
        )
    return {
        "url": url,
        "request_body": request_body,
        "import_strategy": "codex_session",
        "reused": 0,
        "total": int(data.get("total", 0)),
        "created": int(data.get("created", 0)),
        "updated": int(data.get("updated", 0)),
        "skipped": int(data.get("skipped", 0)),
        "failed": int(data.get("failed", 0)),
        "items": items,
        "warnings": data.get("warnings") or [],
        "errors": data.get("errors") or [],
        "applied_group_ids": list(effective_config.group_ids),
        "applied_concurrency": effective_config.concurrency,
        "post_import_update": post_import_update,
    }
