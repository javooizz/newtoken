import base64
import copy
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from sub2api_http_client import request_json as http_request_json

DEFAULT_OUTPUT_MODE = "sub"
OUTPUT_MODE_LABEL = "Sub 形式"
CAP_OUTPUT_MODE = "cap"
CAP_OUTPUT_MODE_LABEL = "CAP 形式"
OUTPUT_MODE_LABELS = {
    DEFAULT_OUTPUT_MODE: OUTPUT_MODE_LABEL,
    CAP_OUTPUT_MODE: CAP_OUTPUT_MODE_LABEL,
}
ACTION_SAVE = "save"
ACTION_COPY = "copy"
MAX_CONCURRENT_CHECKS = 50
HTTP_TIMEOUT_SECONDS = 25
TOKEN_REFRESH_SKEW_SECONDS = 300
TOKEN_ENDPOINT = "https://auth.openai.com/oauth/token"
USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
AUTH_FAILURE_KEYWORDS = (
    "invalid_grant",
    "unauthorized",
    "unauthenticated",
    "invalid authentication",
    "refresh_token_reused",
    "refresh_token_expired",
    "refresh_token_invalidated",
    "invalid refresh token",
)
QUOTA_FAILURE_KEYWORDS = (
    "usage_limit_reached",
    "limit reached",
    "insufficient_quota",
    "quota exceeded",
    "selected model is at capacity",
    "model is at capacity",
)
HTTP_ERROR_BODY_DISPLAY_MAX_CHARS = 300


@dataclass
class AccountCandidate:
    """保存待校验账号的来源信息，便于并发后还原顺序和日志。"""

    order: int
    folder_name: str
    file_name: str
    file_path: str
    record: dict


@dataclass
class InputSource:
    """统一表示一种输入来源，兼容单文件和递归目录扫描。"""

    folder_path: str
    source_name: str
    file_names: list[str]


@dataclass
class AccountCheckResult:
    """保存单个账号的校验结果，只让可用账号进入最终导出。"""

    order: int
    folder_name: str
    file_name: str
    email: str
    status: str
    reason: str
    account: dict | None = None
    remaining_quota: int | None = None


class AccountCheckFailure(Exception):
    """统一封装账号校验失败原因，方便按授权/额度/其他错误分类。"""

    def __init__(self, category, reason, status_code=None):
        super().__init__(reason)
        self.category = category
        self.reason = reason
        self.status_code = status_code


def decode_jwt_payload(token):
    """解码 JWT payload，失败时返回空字典，避免整个流程中断。"""

    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, json.JSONDecodeError, TypeError, ValueError):
        return {}


def normalize_text(value):
    """把可能为空的字符串字段标准化成可安全使用的文本。"""

    if not isinstance(value, str):
        return ""
    return value.strip()


def extract_chatgpt_account_id(access_token):
    """从 access_token 里提取 ChatGPT-Account-Id，和 cockpit-tools 保持一致。"""

    auth_info = decode_jwt_payload(access_token).get("https://api.openai.com/auth", {})
    return normalize_text(
        auth_info.get("chatgpt_account_id") or auth_info.get("account_id") or ""
    )


def extract_account_email(record):
    """优先从原始记录和 token 元信息里拿邮箱，保证日志里能定位账号。"""

    email = normalize_text(record.get("email", ""))
    if email:
        return email
    profile = decode_jwt_payload(record.get("access_token", "")).get(
        "https://api.openai.com/profile", {}
    )
    return normalize_text(profile.get("email", ""))


def is_token_expired(access_token):
    """按 cockpit-tools 的逻辑，提前 5 分钟把 token 当成即将过期。"""

    payload = decode_jwt_payload(access_token)
    exp = payload.get("exp")
    if not isinstance(exp, int):
        return True
    return (
        exp <= int(datetime.now(timezone.utc).timestamp()) + TOKEN_REFRESH_SKEW_SECONDS
    )


def clamp_percentage(value):
    """把百分比约束到 0-100，避免异常返回值污染额度判断。"""

    try:
        numeric = int(value)
    except (TypeError, ValueError):
        numeric = 0
    return max(0, min(100, numeric))


def normalize_remaining_percentage(window):
    """把 usage 里的 used_percent 换算成剩余额度百分比。"""

    used = clamp_percentage(window.get("used_percent"))
    return 100 - used


def normalize_window_minutes(window):
    """把秒级窗口长度转成分钟，方便日志和导出附带观察。"""

    seconds = window.get("limit_window_seconds")
    if not isinstance(seconds, int) or seconds <= 0:
        return None
    return (seconds + 59) // 60


def normalize_reset_timestamp(window):
    """把窗口里的 reset_at 或 reset_after_seconds 统一换成时间戳。"""

    reset_at = window.get("reset_at")
    if isinstance(reset_at, int) and reset_at > 0:
        return reset_at
    reset_after = window.get("reset_after_seconds")
    if not isinstance(reset_after, int) or reset_after < 0:
        return None
    return int(datetime.now(timezone.utc).timestamp()) + reset_after


def parse_usage_quota(payload):
    """解析 wham/usage 响应，只保留当前脚本筛账号需要的核心额度字段。"""

    rate_limit = payload.get("rate_limit") or {}
    primary_window = rate_limit.get("primary_window") or {}
    secondary_window = rate_limit.get("secondary_window") or {}
    has_primary = isinstance(primary_window, dict) and bool(primary_window)
    has_secondary = isinstance(secondary_window, dict) and bool(secondary_window)
    return {
        "allowed": rate_limit.get("allowed"),
        "limit_reached": rate_limit.get("limit_reached"),
        "hourly_percentage": normalize_remaining_percentage(primary_window)
        if has_primary
        else 100,
        "hourly_reset_time": normalize_reset_timestamp(primary_window)
        if has_primary
        else None,
        "hourly_window_minutes": normalize_window_minutes(primary_window)
        if has_primary
        else None,
        "hourly_window_present": has_primary,
        "weekly_percentage": normalize_remaining_percentage(secondary_window)
        if has_secondary
        else 100,
        "weekly_reset_time": normalize_reset_timestamp(secondary_window)
        if has_secondary
        else None,
        "weekly_window_minutes": normalize_window_minutes(secondary_window)
        if has_secondary
        else None,
        "weekly_window_present": has_secondary,
    }


def resolve_remaining_quota(quota):
    """按 cockpit-tools 的做法，取存在窗口里的最小剩余额度作为可用值。"""

    percentages = []
    if quota.get("hourly_window_present"):
        percentages.append(clamp_percentage(quota.get("hourly_percentage")))
    if quota.get("weekly_window_present"):
        percentages.append(clamp_percentage(quota.get("weekly_percentage")))
    if percentages:
        return min(percentages)
    if quota.get("allowed") is False or quota.get("limit_reached") is True:
        return 0
    return 100


def calculate_average_remaining_quota(results):
    """计算可用账号的平均剩余额度，保留两位小数。"""

    quotas = [
        result.remaining_quota
        for result in results
        if isinstance(getattr(result, "remaining_quota", None), int)
    ]
    if not quotas:
        return 0.0
    return round(sum(quotas) / len(quotas), 2)


def normalize_http_error_body_for_display(body):
    """压缩错误正文，避免日志和弹窗被超长 HTML 或 JSON 淹没。"""

    compact = " ".join((body or "").split()).strip()
    if not compact:
        return "<empty>"
    if len(compact) <= HTTP_ERROR_BODY_DISPLAY_MAX_CHARS:
        return compact
    return f"{compact[:HTTP_ERROR_BODY_DISPLAY_MAX_CHARS]}...(truncated)"


def extract_error_code_from_payload(payload):
    """尽量从错误响应里抽出 error_code，方便快速识别失败类型。"""

    if not isinstance(payload, dict):
        return ""
    detail = payload.get("detail")
    if isinstance(detail, dict):
        code = normalize_text(detail.get("code", ""))
        if code:
            return code
    error = payload.get("error")
    if isinstance(error, dict):
        code = normalize_text(error.get("code", "") or error.get("type", ""))
        if code:
            return code
    return normalize_text(payload.get("code", ""))


def build_http_error_message(prefix, status_code, body_text, payload):
    """把 HTTP 状态和响应体整理成一行可读错误，方便日志和结果统计。"""

    message = f"{prefix} HTTP {status_code}"
    error_code = extract_error_code_from_payload(payload)
    if error_code:
        message += f" [error_code:{error_code}]"
    message += f" [body:{normalize_http_error_body_for_display(body_text)}]"
    return message


def classify_failure(status_code, detail, body_text=""):
    """按 cockpit-tools 的标准把失败归到授权失效、额度不足或其他错误。"""

    lower = f"{detail} {body_text}".lower()
    if status_code == 401 or any(keyword in lower for keyword in AUTH_FAILURE_KEYWORDS):
        return "auth_error"
    if any(keyword in lower for keyword in QUOTA_FAILURE_KEYWORDS):
        return "quota_error"
    if status_code in (403, 429):
        return "quota_error"
    return "other_error"


def request_json(
    url, method="GET", headers=None, json_body=None, timeout=HTTP_TIMEOUT_SECONDS
):
    """发起 JSON 请求，并把成功和 HTTP 错误都统一成可继续处理的结构。"""

    return http_request_json(
        url,
        method=method,
        headers=headers,
        json_body=json_body,
        timeout=timeout,
    )


def refresh_access_token_if_needed(record):
    """在额度查询前先续期 access_token，减少因为本地旧 token 造成的误判。"""

    access_token = normalize_text(record.get("access_token", ""))
    if not access_token:
        raise AccountCheckFailure("auth_error", "缺少 access_token")
    if not is_token_expired(access_token):
        return record

    refresh_token = normalize_text(record.get("refresh_token", ""))
    if not refresh_token:
        raise AccountCheckFailure(
            "auth_error", "access_token 已过期且缺少 refresh_token"
        )

    status_code, body_text, payload = request_json(
        TOKEN_ENDPOINT,
        method="POST",
        json_body={
            "client_id": OAUTH_CLIENT_ID,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )
    if status_code < 200 or status_code >= 300:
        reason = build_http_error_message(
            "Token 刷新失败", status_code, body_text, payload
        )
        raise AccountCheckFailure(
            classify_failure(status_code, reason, body_text), reason, status_code
        )
    if not isinstance(payload, dict):
        raise AccountCheckFailure("other_error", "Token 刷新成功但响应不是 JSON")

    next_access_token = normalize_text(payload.get("access_token", ""))
    next_id_token = normalize_text(payload.get("id_token", "")) or normalize_text(
        record.get("id_token", "")
    )
    next_refresh_token = (
        normalize_text(payload.get("refresh_token", "")) or refresh_token
    )
    if not next_access_token or not next_id_token:
        raise AccountCheckFailure(
            "other_error", "Token 刷新响应缺少 access_token 或 id_token"
        )

    updated = copy.deepcopy(record)
    updated["access_token"] = next_access_token
    updated["id_token"] = next_id_token
    updated["refresh_token"] = next_refresh_token
    return updated


def fetch_codex_usage(record):
    """请求 cockpit-tools 同款 wham/usage 接口，并返回解析后的额度信息。"""

    access_token = normalize_text(record.get("access_token", ""))
    account_id = extract_chatgpt_account_id(access_token)
    headers = {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    if account_id:
        headers["ChatGPT-Account-Id"] = account_id

    status_code, body_text, payload = request_json(USAGE_URL, headers=headers)
    if status_code < 200 or status_code >= 300:
        reason = build_http_error_message(
            "额度接口返回错误", status_code, body_text, payload
        )
        raise AccountCheckFailure(
            classify_failure(status_code, reason, body_text), reason, status_code
        )
    if not isinstance(payload, dict):
        raise AccountCheckFailure("other_error", "额度接口返回了非 JSON 数据")

    quota = parse_usage_quota(payload)
    remaining_quota = resolve_remaining_quota(quota)
    if remaining_quota <= 0:
        raise AccountCheckFailure(
            "quota_error", f"无可用额度（最小剩余额度 {remaining_quota}%）"
        )
    return quota, payload


def normalize_subscription_expiry(raw_value):
    """把订阅到期时间统一转成导出里更稳定的 UTC 文本。"""

    raw_text = normalize_text(raw_value)
    if not raw_text:
        return ""
    if raw_text.isdigit():
        timestamp = int(raw_text)
        if timestamp > 1_000_000_000_000:
            timestamp //= 1000
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )
    try:
        parsed = datetime.fromisoformat(raw_text.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    except ValueError:
        return raw_text


def is_cap_account_record(record):
    """判断一条记录是否符合 CAP/Codex 账号结构。"""

    if not isinstance(record, dict):
        return False
    return bool(
        normalize_text(record.get("access_token", ""))
        and normalize_text(record.get("refresh_token", ""))
    )


def is_sub_payload(payload):
    """判断输入是否为当前工具输出的 Sub 聚合结构。"""

    return (
        isinstance(payload, dict)
        and payload.get("type") == "sub2api-data"
        and isinstance(payload.get("accounts"), list)
    )


def extract_cap_records_from_payload(payload):
    """从单文件 JSON 中提取 CAP 账号记录，兼容单对象和对象数组。"""

    if is_cap_account_record(payload):
        return [payload]
    if not isinstance(payload, list):
        return []
    return [record for record in payload if is_cap_account_record(record)]


def extract_sub_accounts_from_payload(payload):
    """从 Sub 聚合结构中提取账号列表。"""

    if not is_sub_payload(payload):
        return []
    return [account for account in payload["accounts"] if isinstance(account, dict)]


def extract_candidate_records_from_payload(payload):
    """把支持的输入 JSON 统一转成可校验的 CAP 账号记录列表。"""

    cap_records = extract_cap_records_from_payload(payload)
    if cap_records:
        return cap_records

    exported_at = ""
    if isinstance(payload, dict):
        exported_at = normalize_text(payload.get("exported_at", ""))
    return [
        build_cap_account(account, exported_at)
        for account in extract_sub_accounts_from_payload(payload)
    ]


def resolve_access_token_expiry(access_token, fallback=""):
    """优先从 access_token 中提取过期时间，提不到时回退到已有字段。"""

    payload = decode_jwt_payload(access_token)
    exp_ts = payload.get("exp")
    if isinstance(exp_ts, int):
        return datetime.fromtimestamp(exp_ts, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )
    return normalize_text(fallback)


def build_export_account(record):
    """把通过额度校验的账号重新组装成现有 sub 导出结构。"""

    email = extract_account_email(record)
    access_token = normalize_text(record.get("access_token", ""))
    id_token = normalize_text(record.get("id_token", ""))
    refresh_token = normalize_text(record.get("refresh_token", ""))
    access_payload = decode_jwt_payload(access_token)
    access_auth = access_payload.get("https://api.openai.com/auth", {})
    id_auth = decode_jwt_payload(id_token).get("https://api.openai.com/auth", {})

    exp_ts = access_payload.get("exp")
    expires_at = ""
    if isinstance(exp_ts, int):
        expires_at = datetime.fromtimestamp(exp_ts, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )

    return {
        "name": email,
        "platform": "openai",
        "type": "oauth",
        "credentials": {
            "access_token": access_token,
            "expires_at": expires_at,
            "refresh_token": refresh_token,
            "id_token": id_token,
            "email": email,
            "chatgpt_account_id": normalize_text(
                access_auth.get("chatgpt_account_id", "")
            ),
            "chatgpt_account_user_id": normalize_text(
                access_auth.get("chatgpt_account_user_id", "")
            ),
            "chatgpt_user_id": normalize_text(access_auth.get("chatgpt_user_id", "")),
            "plan_type": normalize_text(access_auth.get("chatgpt_plan_type", "")),
            "subscription_expires_at": normalize_subscription_expiry(
                id_auth.get("chatgpt_subscription_active_until", "")
            ),
        },
        "concurrency": 0,
        "priority": 0,
    }


def build_export_result(accounts):
    """把所有可用账号合并成单份结果，保存和复制共用同一套输出。"""

    return {
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "proxies": [],
        "accounts": accounts,
        "type": "sub2api-data",
        "version": 1,
    }


def build_cap_account(account, exported_at=None):
    """把 Sub 账号结构转换成 CAP 账号结构。"""

    credentials = account.get("credentials") or {}
    access_token = normalize_text(credentials.get("access_token", ""))
    email = normalize_text(credentials.get("email", "")) or normalize_text(
        account.get("name", "")
    )
    account_id = normalize_text(credentials.get("chatgpt_account_id", "")) or (
        extract_chatgpt_account_id(access_token)
    )
    last_refresh = normalize_text(exported_at) or datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )
    return {
        "id_token": normalize_text(credentials.get("id_token", "")),
        "access_token": access_token,
        "refresh_token": normalize_text(credentials.get("refresh_token", "")),
        "account_id": account_id,
        "last_refresh": last_refresh,
        "email": email,
        "type": "codex",
        "expired": resolve_access_token_expiry(
            access_token, credentials.get("expires_at", "")
        ),
    }


def build_cap_result(accounts, exported_at=None):
    """把 Sub 聚合账号列表转换成 CAP 数组结果。"""

    return [build_cap_account(account, exported_at) for account in accounts]


def build_output_file_name(output_mode=DEFAULT_OUTPUT_MODE):
    """按目标格式生成单文件导出名。"""

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    if output_mode == CAP_OUTPUT_MODE:
        return f"codex_accounts_cap_available_{timestamp}.json"
    return f"codex_accounts_sub2api_available_{timestamp}.json"


def build_candidate_identity(record):
    """构建账号去重键，避免同一 refresh_token 被并发刷新两次。"""

    refresh_token = normalize_text(record.get("refresh_token", ""))
    if refresh_token:
        return f"refresh:{refresh_token}"
    access_token = normalize_text(record.get("access_token", ""))
    if access_token:
        return f"access:{access_token}"
    return f"email:{extract_account_email(record)}|account:{extract_chatgpt_account_id(access_token)}"


def list_json_files_in_dir(folder_path):
    """列出目录下平铺的 JSON 文件，不递归进入子目录。"""

    return sorted(
        [
            file_name
            for file_name in os.listdir(folder_path)
            if os.path.isfile(os.path.join(folder_path, file_name))
            and file_name.lower().endswith(".json")
        ]
    )


def list_recursive_json_sources(root_path):
    """递归扫描目录下所有 JSON 文件，并按所在目录分组返回输入来源。"""

    sources = []
    normalized_root = os.path.abspath(root_path)
    for current_dir, dir_names, file_names in os.walk(normalized_root):
        dir_names.sort()
        json_files = sorted(
            [
                file_name
                for file_name in file_names
                if file_name.lower().endswith(".json")
            ]
        )
        if not json_files:
            continue
        relative_dir = os.path.relpath(current_dir, normalized_root)
        if relative_dir == ".":
            source_name = os.path.basename(normalized_root) or normalized_root
        else:
            source_name = relative_dir.replace("\\", "/")
        sources.append(
            InputSource(
                folder_path=current_dir,
                source_name=source_name,
                file_names=json_files,
            )
        )
    return sources


def resolve_input_sources(input_path):
    """把输入路径解析成统一来源列表，兼容单文件和递归目录扫描。"""

    normalized_path = os.path.abspath(input_path)
    if os.path.isfile(normalized_path):
        if not normalized_path.lower().endswith(".json"):
            raise ValueError("单文件模式只支持 JSON 文件")
        return [
            InputSource(
                folder_path=os.path.dirname(normalized_path),
                source_name=os.path.basename(normalized_path),
                file_names=[os.path.basename(normalized_path)],
            )
        ]

    if not os.path.isdir(normalized_path):
        raise ValueError("输入路径不存在")

    return list_recursive_json_sources(normalized_path)


def collect_account_candidates(input_sources):
    """扫描输入来源，收集 CAP 账号候选并顺手去重，只保留首个同源账号。"""

    candidates = []
    seen_identities = set()
    skipped_duplicates = 0
    order = 0

    for input_source in input_sources:
        for file_name in input_source.file_names:
            file_path = os.path.join(input_source.folder_path, file_name)
            try:
                with open(file_path, "r", encoding="utf-8") as handle:
                    payload = json.load(handle)
            except (OSError, json.JSONDecodeError):
                continue
            records = extract_candidate_records_from_payload(payload)
            for index, record in enumerate(records, start=1):
                identity = build_candidate_identity(record)
                if identity in seen_identities:
                    skipped_duplicates += 1
                    continue
                seen_identities.add(identity)
                display_name = f"{file_name}#{index}" if len(records) > 1 else file_name
                candidates.append(
                    AccountCandidate(
                        order,
                        input_source.source_name,
                        display_name,
                        file_path,
                        record,
                    )
                )
                order += 1
    return candidates, skipped_duplicates


def validate_account_candidate(candidate):
    """执行单个账号的 token 续期、额度刷新和可用性判断。"""

    email = extract_account_email(candidate.record) or candidate.file_name
    try:
        refreshed_record = refresh_access_token_if_needed(candidate.record)
        quota, _ = fetch_codex_usage(refreshed_record)
        remaining_quota = resolve_remaining_quota(quota)
        return AccountCheckResult(
            order=candidate.order,
            folder_name=candidate.folder_name,
            file_name=candidate.file_name,
            email=email,
            status="ok",
            reason=f"可用，最小剩余额度 {remaining_quota}%",
            account=build_export_account(refreshed_record),
            remaining_quota=remaining_quota,
        )
    except AccountCheckFailure as exc:
        return AccountCheckResult(
            order=candidate.order,
            folder_name=candidate.folder_name,
            file_name=candidate.file_name,
            email=email,
            status=exc.category,
            reason=exc.reason,
        )
    except Exception as exc:  # noqa: BLE001
        return AccountCheckResult(
            order=candidate.order,
            folder_name=candidate.folder_name,
            file_name=candidate.file_name,
            email=email,
            status="other_error",
            reason=f"未预期错误: {exc}",
        )
