"""集成到 Sub2API 独立工具内的 ACC 席位工具。"""

from __future__ import annotations

import argparse
import json
import threading
import tkinter as tk
import webbrowser
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk
from typing import Any, Callable
import sys

LOCAL_PROJECT_DIR = Path(__file__).resolve().parent
if str(LOCAL_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(LOCAL_PROJECT_DIR))

from sub2api_runtime import ensure_on_sys_path, get_app_dir  # noqa: E402

PROJECT_DIR = get_app_dir(__file__)
STANDALONE_DIR = get_app_dir(__file__)
ensure_on_sys_path(PROJECT_DIR)
ensure_on_sys_path(STANDALONE_DIR)

import standalone_acc_change_seat_cli as core  # noqa: E402
from sub2api_converter import DrawerSection  # noqa: E402
from standalone_acc_cache import (  # noqa: E402
    read_acc_input_cache,
    read_member_list_cache,
    read_ui_settings_cache,
    read_usage_cache,
    write_acc_input_cache,
    write_member_list_cache,
    write_ui_settings_cache,
    write_usage_cache,
)
from standalone_acc_local_env import write_env_file  # noqa: E402
from standalone_acc_local_env import read_env_file  # noqa: E402
from standalone_sub2api_usage_bridge import (  # noqa: E402
    Sub2APIRemoteAccountSummary,
    Sub2APIUsageLoadResult,
    Sub2APIUsageSnapshot,
    format_reset_eta_text,
    load_sub2api_usage_lookup,
    normalize_email,
    parse_optional_datetime,
    refresh_remote_accounts_serial,
    recover_remote_accounts_state,
    set_remote_accounts_status,
    set_remote_accounts_inactive,
)

ENV_FILE_PATH = STANDALONE_DIR / ".env"
PROJECT_ENV_FILE_PATH = PROJECT_DIR / ".env"
IMPORT_CACHE_PATH = STANDALONE_DIR / ".session_cache.json"
IMPORT_TEXT_CACHE_PATH = STANDALONE_DIR / ".acc_input_cache.txt"
USAGE_CACHE_PATH = STANDALONE_DIR / ".sub2api_usage_cache.json"
MEMBER_LIST_CACHE_PATH = STANDALONE_DIR / ".acc_member_list_cache.json"
UI_SETTINGS_CACHE_PATH = STANDALONE_DIR / ".acc_ui_settings_cache.json"
DEFAULT_WINDOW_SIZE = "1120x760"
DEFAULT_LOAD_PAGE_SIZE = 100
DEFAULT_CHATGPT_SEAT_LIMIT = 2
IMPORT_TEXT_CACHE_WRITE_DELAY_MS = 400
CHATGPT_SESSION_URL = "https://chatgpt.com/api/auth/session"
PROMOTION_PROBE_COOLDOWN_MINUTES = 15
AUTO_REFRESH_DISABLED = 0
AUTO_REFRESH_OPTIONS = (
    ("关闭", AUTO_REFRESH_DISABLED),
    ("3秒", 3),
    ("5秒", 5),
    ("10秒", 10),
)
MOTHER_ACCOUNT_TREE_TAG = "mother_account"
SEAT_ACTIONS = {
    "ChatGPT": "default",
    "Codex": "usage_based",
}


def load_private_env_value(key: str, default: str = "") -> str:
    """优先从独立工具目录，其次从项目根目录读取私密配置。"""

    for env_path in (ENV_FILE_PATH, PROJECT_ENV_FILE_PATH):
        values = read_env_file(env_path)
        value = str(values.get(key, "")).strip()
        if value:
            return value
    return default


MOTHER_ACCOUNT_EMAIL = load_private_env_value("ACC_MOTHER_ACCOUNT_EMAIL", "").strip().lower()


def build_env_values(
    access_token: str,
    account_id: str,
    device_id: str,
    session_token: str,
    client_build_number: str,
    client_version: str,
    base_url: str,
) -> dict[str, str]:
    """把当前会话状态转成 .env 键值。"""
    return {
        "OPENAI_ACCESS_TOKEN": access_token.strip(),
        "OPENAI_ACCOUNT_ID": account_id.strip(),
        "OPENAI_DEVICE_ID": device_id.strip(),
        "OPENAI_SESSION_TOKEN": session_token.strip(),
        "OPENAI_CLIENT_BUILD_NUMBER": (client_build_number.strip() or core.CLIENT_BUILD_NUMBER),
        "OPENAI_CLIENT_VERSION": (client_version.strip() or core.CLIENT_VERSION),
        "OPENAI_BASE_URL": core.normalize_base_url(base_url.strip() or core.DEFAULT_BASE_URL),
    }


def parse_import_payload(raw_text: str) -> dict[str, str]:
    """解析导入文本，兼容 JSON、HAR 和片段格式。"""
    text = raw_text.strip()
    if not text:
        raise core.SeatApiError("导入内容为空。")

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = None

    if isinstance(data, dict):
        if isinstance(data.get("log"), dict):
            return core.parse_har_session_bundle(text)
        account_data = data.get("account") if isinstance(data.get("account"), dict) else {}
        payload = {
            "warningBanner": str(data.get("WARNING_BANNER") or "").strip(),
            "accountId": str(account_data.get("id") or data.get("account_id") or "").strip(),
            "deviceId": str(
                data.get("deviceId")
                or data.get("device_id")
                or data.get("oai-did")
                or data.get("oaiDid")
                or data.get("did")
                or ""
            ).strip(),
            "accessToken": str(data.get("accessToken") or "").strip(),
            "sessionToken": str(data.get("sessionToken") or "").strip(),
            "authProvider": str(data.get("authProvider") or "").strip(),
            "clientBuildNumber": str(data.get("clientBuildNumber") or "").strip(),
            "clientVersion": str(data.get("clientVersion") or "").strip(),
        }
        if payload["accessToken"] or payload["sessionToken"]:
            return payload

    split_marker = '\",\"authProvider\"'
    split_index = text.find(split_marker)
    if split_index != -1:
        access_token = text[:split_index].strip().strip('"').strip()
        suffix = "{" + text[split_index + 2 :]
        try:
            suffix_data = json.loads(suffix)
        except json.JSONDecodeError as exc:
            raise core.SeatApiError("导入数据尾部 JSON 不完整。") from exc
        payload = {
            "warningBanner": "",
            "accountId": "",
            "deviceId": "",
            "accessToken": access_token,
            "sessionToken": str(suffix_data.get("sessionToken") or "").strip(),
            "authProvider": str(suffix_data.get("authProvider") or "").strip(),
            "clientBuildNumber": "",
            "clientVersion": "",
        }
        if payload["accessToken"] or payload["sessionToken"]:
            return payload

    if text.count(".") >= 2 and '"sessionToken"' not in text:
        return {
            "warningBanner": "",
            "accountId": "",
            "deviceId": "",
            "accessToken": text,
            "sessionToken": "",
            "authProvider": "",
            "clientBuildNumber": "",
            "clientVersion": "",
        }

    raise core.SeatApiError("无法识别导入格式。")


def read_import_cache(path: Path) -> dict[str, str]:
    """读取导入缓存。"""
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise core.SeatApiError("导入缓存文件损坏，请重新导入。") from exc

    if not isinstance(data, dict):
        raise core.SeatApiError("导入缓存文件格式无效。")

    payload = {
        "warningBanner": str(data.get("warningBanner") or "").strip(),
        "accountId": str(data.get("accountId") or "").strip(),
        "deviceId": str(data.get("deviceId") or "").strip(),
        "accessToken": str(data.get("accessToken") or "").strip(),
        "sessionToken": str(data.get("sessionToken") or "").strip(),
        "authProvider": str(data.get("authProvider") or "").strip(),
        "clientBuildNumber": str(data.get("clientBuildNumber") or "").strip(),
        "clientVersion": str(data.get("clientVersion") or "").strip(),
    }
    if not payload["accessToken"] and not payload["sessionToken"]:
        return {}
    return payload


def write_import_cache(path: Path, payload: dict[str, str]) -> None:
    """写入导入缓存。"""
    normalized = {
        "warningBanner": str(payload.get("warningBanner") or "").strip(),
        "accountId": str(payload.get("accountId") or "").strip(),
        "deviceId": str(payload.get("deviceId") or "").strip(),
        "accessToken": str(payload.get("accessToken") or "").strip(),
        "sessionToken": str(payload.get("sessionToken") or "").strip(),
        "authProvider": str(payload.get("authProvider") or "").strip(),
        "clientBuildNumber": str(payload.get("clientBuildNumber") or "").strip(),
        "clientVersion": str(payload.get("clientVersion") or "").strip(),
    }
    path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def copy_text_to_clipboard(root: tk.Misc, text: str) -> None:
    """把文本复制到系统剪贴板。"""
    root.clipboard_clear()
    root.clipboard_append(text)
    root.update_idletasks()


def default_credential_state() -> dict[str, str]:
    """返回程序内部使用的默认凭证状态。"""
    return {
        "access_token": "",
        "account_id": "",
        "device_id": "",
        "session_token": "",
        "client_build_number": core.CLIENT_BUILD_NUMBER,
        "client_version": core.CLIENT_VERSION,
        "base_url": core.DEFAULT_BASE_URL,
    }


def mask_value(value: str, prefix: int = 10, suffix: int = 6) -> str:
    """把敏感值缩略显示。"""
    text = value.strip()
    if not text:
        return "-"
    if len(text) <= prefix + suffix + 3:
        return text
    return f"{text[:prefix]}...{text[-suffix:]}"


def list_all_users(
    client: core.SeatClient,
    query: str = "",
    page_limit: int = DEFAULT_LOAD_PAGE_SIZE,
) -> list[dict[str, Any]]:
    """自动翻页拉取全部成员。"""
    users: list[dict[str, Any]] = []
    page = 0
    normalized_query = query.strip()

    while True:
        result = client.list_users(page=page, limit=page_limit, query=normalized_query)
        page_items = list(result.get("items", []))
        users.extend(page_items)
        total = int(result.get("total", len(users)))
        if not page_items or len(users) >= total:
            return users
        page += 1


def is_forbidden_session_refresh_error(error: Exception) -> bool:
    """判断是否属于应静默跳过的 403 会话刷新错误。"""

    message = str(error).strip().lower()
    return (
        "403 forbidden" in message
        or message.startswith("403 ")
        or "http 403:" in message
    )


class StandaloneAccSeatConverterApp:
    """只保留 ACC 导入和席位切换的独立桌面工具。"""

    def __init__(
        self,
        root: tk.Misc,
        *,
        embedded: bool = False,
        status_var: tk.StringVar | None = None,
        log_handler: Any | None = None,
    ) -> None:
        """初始化窗口、状态和布局。"""
        self.root = root
        self.embedded = embedded
        self.parent = root
        self.status_var = status_var or tk.StringVar(value="准备就绪")
        self.log_handler = log_handler
        if not embedded:
            self.root.title("ACC 席位转换器")
            self.root.geometry(DEFAULT_WINDOW_SIZE)
            self.root.minsize(980, 620)

        self.busy = False
        self.current_users: list[dict[str, Any]] = []
        self.import_cache: dict[str, str] = {}
        self.credentials = default_credential_state()
        self.remote_usage_lookup: dict[str, Sub2APIUsageSnapshot] = {}
        self.trusted_usage_lookup: dict[str, Sub2APIUsageSnapshot] = {}
        self.remote_account_summaries: list[Sub2APIRemoteAccountSummary] = []
        self.remote_usage_loaded = False
        self.remote_policy_sync_running = False
        self.remote_policy_sync_pending = False
        self.pending_remote_policy_lookup: dict[str, Sub2APIUsageSnapshot] = {}
        self.auto_seat_policy_running = False
        self.auto_restore_session_pending = False
        self.suspend_import_text_cache_updates = False
        self.import_text_cache_after_id: str | None = None
        self.auto_refresh_after_id: str | None = None
        self.mother_account_prompted = False
        self.promotion_probe_cooldowns: dict[str, datetime] = {}

        self.query_var = tk.StringVar()
        self.cache_var = tk.StringVar(value="ACC 缓存：未检测到")
        self.summary_var = tk.StringVar(value="未导入 ACC 数据")
        self.member_count_var = tk.StringVar(value="成员：0")
        self.chatgpt_count_var = tk.StringVar(
            value=f"ChatGPT：0/{DEFAULT_CHATGPT_SEAT_LIMIT}"
        )
        self.remote_usage_summary_var = tk.StringVar(value="Sub2API额度：未刷新")
        self.auto_refresh_var = tk.StringVar(value=AUTO_REFRESH_OPTIONS[0][0])
        self.auto_refresh_var.trace_add("write", self._handle_auto_refresh_changed)

        self._build_layout()
        self.load_ui_settings_cache()
        self.restore_import_text_cache()
        self.refresh_import_cache_state()
        self.load_remote_usage_cache()
        self.restore_member_list_cache()
        self.maybe_restore_import_session_on_startup()
        self.update_session_summary()
        self.update_member_stats()
        self.schedule_auto_refresh()
        self.update_button_states()

    def write_log(self, message: str) -> None:
        """把 ACC 相关动作写入共享运行日志。"""

        text = str(message or "").rstrip()
        if not text:
            return
        log_handler = getattr(self, "log_handler", None)
        if log_handler is not None and hasattr(log_handler, "write"):
            log_handler.write(f"{text}\n")
            return
        print(text)

    def show_error_dialog(self, title: str, message: str) -> None:
        """展示支持复制的错误弹窗。"""
        dialog = tk.Toplevel(self.root.winfo_toplevel())
        dialog.title(title)
        dialog.transient(self.root.winfo_toplevel())
        dialog.grab_set()
        dialog.geometry("760x420")
        dialog.minsize(560, 280)

        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        ttk.Label(
            frame,
            text=title,
            font=("Microsoft YaHei UI", 11, "bold"),
        ).grid(row=0, column=0, sticky="w")

        text_widget = scrolledtext.ScrolledText(frame, wrap=tk.WORD, height=16)
        text_widget.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        text_widget.insert("1.0", message)
        text_widget.focus_set()

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=2, column=0, sticky="e", pady=(12, 0))
        ttk.Button(
            button_frame,
            text="复制全部",
            command=lambda: copy_text_to_clipboard(self.root, message),
        ).pack(side=tk.LEFT)
        ttk.Button(button_frame, text="关闭", command=dialog.destroy).pack(side=tk.LEFT, padx=(8, 0))

    def _build_layout(self) -> None:
        """搭建界面布局。"""
        scroll_host = ttk.Frame(self.parent)
        scroll_host.pack(fill=tk.BOTH, expand=True)
        self.page_canvas = tk.Canvas(scroll_host, highlightthickness=0)
        self.page_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.page_scrollbar = ttk.Scrollbar(
            scroll_host,
            orient=tk.VERTICAL,
            command=self.page_canvas.yview,
        )
        self.page_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.page_canvas.configure(yscrollcommand=self.page_scrollbar.set)

        container = ttk.Frame(self.page_canvas, padding=14)
        self.page_window_id = self.page_canvas.create_window(
            (0, 0),
            window=container,
            anchor="nw",
        )
        container.bind("<Configure>", self._handle_page_container_configure)
        self.page_canvas.bind("<Configure>", self._handle_page_canvas_configure)
        self.page_canvas.bind_all("<MouseWheel>", self._handle_page_mousewheel)
        self.page_canvas.bind_all("<Button-4>", self._handle_page_mousewheel_linux_up)
        self.page_canvas.bind_all("<Button-5>", self._handle_page_mousewheel_linux_down)

        container.columnconfigure(0, weight=5)
        container.columnconfigure(1, weight=4)
        container.rowconfigure(2, weight=1)

        import_holder = ttk.Frame(container)
        import_holder.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        import_holder.columnconfigure(0, weight=1)
        import_holder.rowconfigure(0, weight=1)
        import_drawer = DrawerSection(
            import_holder,
            "ACC 原文导入",
            expanded=False,
        )
        import_frame = ttk.LabelFrame(import_drawer.content_frame, text="ACC 原文导入", padding=12)
        import_frame.pack(fill="both", expand=True)
        import_frame.columnconfigure(0, weight=1)
        import_frame.rowconfigure(0, weight=1)

        self.import_text = scrolledtext.ScrolledText(import_frame, height=10, wrap=tk.WORD)
        self.import_text.grid(row=0, column=0, sticky="nsew")
        self.import_text.bind("<<Modified>>", self.handle_import_text_modified)

        import_buttons = ttk.Frame(import_frame)
        import_buttons.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.parse_button = ttk.Button(import_buttons, text="解析 ACC", command=self.parse_acc_text)
        self.parse_button.pack(side=tk.LEFT)
        self.quick_fetch_button = ttk.Button(
            import_buttons,
            text="一键获取",
            command=self.start_quick_fetch_session,
        )
        self.quick_fetch_button.pack(side=tk.LEFT, padx=(8, 0))
        self.cache_button = ttk.Button(import_buttons, text="使用缓存", command=self.use_import_cache)
        self.cache_button.pack(side=tk.LEFT, padx=(8, 0))
        self.clear_button = ttk.Button(import_buttons, text="清空原文", command=self.clear_import_text)
        self.clear_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(import_frame, textvariable=self.cache_var).grid(row=2, column=0, sticky="w", pady=(10, 0))

        session_holder = ttk.Frame(container)
        session_holder.grid(row=0, column=1, sticky="nsew")
        session_holder.columnconfigure(0, weight=1)
        session_holder.rowconfigure(0, weight=1)
        session_drawer = DrawerSection(
            session_holder,
            "当前会话",
            expanded=False,
        )
        session_frame = ttk.LabelFrame(session_drawer.content_frame, text="当前会话", padding=12)
        session_frame.pack(fill="both", expand=True)
        session_frame.columnconfigure(0, weight=1)
        ttk.Label(
            session_frame,
            textvariable=self.summary_var,
            justify=tk.LEFT,
            anchor="nw",
        ).grid(row=0, column=0, sticky="nsew")

        account_holder = ttk.Frame(container)
        account_holder.grid(row=1, column=0, columnspan=2, sticky="nsew", pady=(12, 0))
        account_holder.columnconfigure(0, weight=1)
        account_holder.rowconfigure(0, weight=1)
        account_drawer = DrawerSection(
            account_holder,
            "Sub2API账号管理",
            expanded=False,
        )
        account_frame = ttk.LabelFrame(
            account_drawer.content_frame,
            text="Sub2API账号管理",
            padding=12,
        )
        account_frame.pack(fill="both", expand=True)
        account_frame.columnconfigure(0, weight=1)
        account_frame.rowconfigure(1, weight=1)

        remote_action_frame = ttk.Frame(account_frame)
        remote_action_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        remote_action_frame.columnconfigure(0, weight=1)
        self.remote_account_summary_var = tk.StringVar(value="远程账号：未刷新")
        ttk.Label(
            remote_action_frame,
            textvariable=self.remote_account_summary_var,
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        self.refresh_remote_accounts_button = ttk.Button(
            remote_action_frame,
            text="刷新账号",
            command=self.refresh_remote_usage,
        )
        self.refresh_remote_accounts_button.grid(row=0, column=1, sticky="e", padx=(12, 0))

        remote_table_frame = ttk.Frame(account_frame)
        remote_table_frame.grid(row=1, column=0, sticky="nsew")
        remote_table_frame.columnconfigure(0, weight=1)
        remote_table_frame.rowconfigure(0, weight=1)

        remote_columns = ("plan_type", "email", "name", "status", "account_id")
        self.remote_account_tree = ttk.Treeview(
            remote_table_frame,
            columns=remote_columns,
            show="headings",
            height=8,
            selectmode="extended",
        )
        self.remote_account_tree.heading("plan_type", text="类型")
        self.remote_account_tree.heading("email", text="邮箱")
        self.remote_account_tree.heading("name", text="账号名")
        self.remote_account_tree.heading("status", text="调用状态")
        self.remote_account_tree.heading("account_id", text="ID")
        self.remote_account_tree.column("plan_type", width=90, anchor="center")
        self.remote_account_tree.column("email", width=280, anchor="w")
        self.remote_account_tree.column("name", width=220, anchor="w")
        self.remote_account_tree.column("status", width=90, anchor="center")
        self.remote_account_tree.column("account_id", width=80, anchor="center")
        self.remote_account_tree.grid(row=0, column=0, sticky="nsew")
        self.remote_account_tree.bind(
            "<<TreeviewSelect>>",
            lambda _event: self.update_button_states(),
        )

        remote_scrollbar = ttk.Scrollbar(
            remote_table_frame,
            orient=tk.VERTICAL,
            command=self.remote_account_tree.yview,
        )
        remote_scrollbar.grid(row=0, column=1, sticky="ns")
        self.remote_account_tree.configure(yscrollcommand=remote_scrollbar.set)

        remote_button_frame = ttk.Frame(account_frame)
        remote_button_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.enable_remote_account_button = ttk.Button(
            remote_button_frame,
            text="开启调用",
            command=lambda: self.change_selected_remote_accounts_status("active"),
        )
        self.enable_remote_account_button.pack(side=tk.LEFT)
        self.disable_remote_account_button = ttk.Button(
            remote_button_frame,
            text="关闭调用",
            command=lambda: self.change_selected_remote_accounts_status("inactive"),
        )
        self.disable_remote_account_button.pack(side=tk.LEFT, padx=(8, 0))

        member_frame = ttk.LabelFrame(container, text="成员列表", padding=12)
        member_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(12, 0))
        member_frame.columnconfigure(0, weight=1)
        member_frame.rowconfigure(1, weight=1)

        action_frame = ttk.Frame(member_frame)
        action_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        action_frame.columnconfigure(1, weight=1)

        ttk.Label(action_frame, text="搜索").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(action_frame, textvariable=self.query_var).grid(row=0, column=1, sticky="ew")
        self.load_button = ttk.Button(action_frame, text="加载成员", command=self.load_members)
        self.load_button.grid(row=0, column=2, sticky="e", padx=(12, 0))
        ttk.Label(action_frame, textvariable=self.member_count_var).grid(row=0, column=3, sticky="e", padx=(12, 0))
        ttk.Label(action_frame, textvariable=self.chatgpt_count_var).grid(
            row=0,
            column=4,
            sticky="e",
            padx=(12, 0),
        )
        ttk.Label(action_frame, text="ChatGPT上限").grid(
            row=0,
            column=5,
            sticky="e",
            padx=(12, 4),
        )
        ttk.Label(action_frame, text=str(DEFAULT_CHATGPT_SEAT_LIMIT)).grid(
            row=0,
            column=6,
            sticky="e",
        )
        ttk.Label(
            action_frame,
            textvariable=self.remote_usage_summary_var,
            anchor="w",
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(8, 0))
        ttk.Label(action_frame, text="自动刷新").grid(
            row=1,
            column=4,
            sticky="e",
            padx=(12, 4),
            pady=(8, 0),
        )
        self.auto_refresh_combo = ttk.Combobox(
            action_frame,
            textvariable=self.auto_refresh_var,
            values=[label for label, _seconds in AUTO_REFRESH_OPTIONS],
            state="readonly",
            width=8,
        )
        self.auto_refresh_combo.grid(row=1, column=5, sticky="e", pady=(8, 0))
        self.refresh_remote_usage_button = ttk.Button(
            action_frame,
            text="刷新Sub2API额度",
            command=self.refresh_remote_usage,
        )
        self.refresh_remote_usage_button.grid(row=1, column=6, sticky="e", pady=(8, 0))

        table_frame = ttk.Frame(member_frame)
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        columns = (
            "user_id",
            "email",
            "seat_type",
            "quota_5h",
            "quota_7d",
            "quota_5h_refresh",
            "quota_7d_refresh",
        )
        self.tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=14)
        self.tree.heading("user_id", text="User ID")
        self.tree.heading("email", text="邮箱")
        self.tree.heading("seat_type", text="当前席位")
        self.tree.heading("quota_5h", text="5h额度")
        self.tree.heading("quota_7d", text="7日额度")
        self.tree.heading("quota_5h_refresh", text="5h刷新")
        self.tree.heading("quota_7d_refresh", text="周刷新")
        self.tree.column("user_id", width=240, anchor="w")
        self.tree.column("email", width=320, anchor="w")
        self.tree.column("seat_type", width=120, anchor="center")
        self.tree.column("quota_5h", width=100, anchor="center")
        self.tree.column("quota_7d", width=100, anchor="center")
        self.tree.column("quota_5h_refresh", width=110, anchor="center")
        self.tree.column("quota_7d_refresh", width=110, anchor="center")
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self.update_button_states())
        self.tree.tag_configure(
            MOTHER_ACCOUNT_TREE_TAG,
            foreground="#c62828",
        )

        scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)

        button_frame = ttk.Frame(member_frame)
        button_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.copy_email_button = ttk.Button(button_frame, text="复制邮箱", command=self.copy_selected_email)
        self.copy_email_button.pack(side=tk.LEFT)
        self.toggle_button = ttk.Button(button_frame, text="切换席位", command=self.toggle_selected_user)
        self.toggle_button.pack(side=tk.LEFT, padx=(8, 0))
        self.set_default_button = ttk.Button(
            button_frame,
            text="禁改 ChatGPT",
            command=lambda: self.set_selected_user_seat(SEAT_ACTIONS["ChatGPT"]),
            state=tk.DISABLED,
        )
        self.set_default_button.pack(side=tk.LEFT, padx=(8, 0))
        self.set_usage_based_button = ttk.Button(
            button_frame,
            text="设为 Codex",
            command=lambda: self.set_selected_user_seat(SEAT_ACTIONS["Codex"]),
        )
        self.set_usage_based_button.pack(side=tk.LEFT, padx=(8, 0))

        if not self.embedded:
            footer = ttk.Frame(container)
            footer.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
            footer.columnconfigure(0, weight=1)
            ttk.Label(footer, textvariable=self.status_var).grid(row=0, column=0, sticky="w")

    def _handle_page_container_configure(self, _event=None) -> None:
        """内容尺寸变化时同步滚动区域。"""

        self.page_canvas.configure(scrollregion=self.page_canvas.bbox("all"))

    def _handle_page_canvas_configure(self, event) -> None:
        """外层画布尺寸变化时让内容宽度跟随。"""

        self.page_canvas.itemconfigure(self.page_window_id, width=event.width)

    def _handle_page_mousewheel(self, event) -> None:
        """支持 Windows 和 macOS 的鼠标滚轮。"""

        delta = int(-event.delta / 120) if event.delta else 0
        if delta:
            self.page_canvas.yview_scroll(delta, "units")

    def _handle_page_mousewheel_linux_up(self, _event) -> None:
        """支持 Linux 向上滚轮。"""

        self.page_canvas.yview_scroll(-1, "units")

    def _handle_page_mousewheel_linux_down(self, _event) -> None:
        """支持 Linux 向下滚轮。"""

        self.page_canvas.yview_scroll(1, "units")

    def get_import_text(self) -> str:
        """读取 ACC 原文输入框。"""
        return self.import_text.get("1.0", tk.END).strip()

    def set_import_text(self, text: str) -> None:
        """回填 ACC 原文输入框。"""
        self.suspend_import_text_cache_updates = True
        self.import_text.delete("1.0", tk.END)
        self.import_text.insert("1.0", text)
        self.import_text.edit_modified(False)
        self.suspend_import_text_cache_updates = False

    def clear_import_text(self) -> None:
        """清空 ACC 原文输入框。"""
        self.set_import_text("")
        self.write_current_import_text_cache()
        self.mother_account_prompted = False
        self.status_var.set("已清空 ACC 原文")

    def restore_import_text_cache(self) -> None:
        """启动时恢复 ACC 原文输入缓存。"""

        cached_text = read_acc_input_cache(IMPORT_TEXT_CACHE_PATH)
        if cached_text:
            self.set_import_text(cached_text)

    def load_ui_settings_cache(self) -> None:
        """启动时恢复本地 UI 设置。"""

        settings = read_ui_settings_cache(UI_SETTINGS_CACHE_PATH)
        auto_refresh_seconds = settings.get("auto_refresh_seconds")
        if auto_refresh_seconds not in (None, ""):
            self.auto_refresh_var.set(
                self.get_auto_refresh_label_from_seconds(auto_refresh_seconds)
            )

    def persist_ui_settings(self) -> None:
        """把当前 UI 设置写入本地缓存。"""

        write_ui_settings_cache(
            UI_SETTINGS_CACHE_PATH,
            {
                "auto_refresh_seconds": self.get_auto_refresh_seconds(),
            },
        )

    def handle_import_text_modified(self, _event=None) -> None:
        """在输入框内容变化时延迟写入缓存。"""

        if not self.import_text.edit_modified():
            return
        self.import_text.edit_modified(False)
        if self.suspend_import_text_cache_updates:
            return
        self.schedule_import_text_cache_write()

    def schedule_import_text_cache_write(self) -> None:
        """为 ACC 原文输入安排一次延迟缓存写入。"""

        if self.import_text_cache_after_id is not None:
            self.root.after_cancel(self.import_text_cache_after_id)
        self.import_text_cache_after_id = self.root.after(
            IMPORT_TEXT_CACHE_WRITE_DELAY_MS,
            self.write_current_import_text_cache,
        )

    def write_current_import_text_cache(self) -> None:
        """把当前 ACC 原文输入写入缓存。"""

        self.import_text_cache_after_id = None
        write_acc_input_cache(IMPORT_TEXT_CACHE_PATH, self.get_import_text())

    def refresh_import_cache_state(self) -> None:
        """刷新本地 ACC 缓存状态。"""
        try:
            self.import_cache = read_import_cache(IMPORT_CACHE_PATH)
        except core.SeatApiError as exc:
            self.import_cache = {}
            self.cache_var.set(f"ACC 缓存：读取失败（{exc}）")
            return

        if not self.import_cache:
            self.cache_var.set("ACC 缓存：未检测到")
            return

        account_id = self.import_cache.get("accountId", "") or "-"
        device_id = self.import_cache.get("deviceId", "") or "-"
        self.cache_var.set(f"ACC 缓存：已检测到，account_id={account_id}，device_id={device_id}")

    def update_session_summary(self) -> None:
        """刷新当前会话摘要。"""
        lines = [
            f"account_id：{self.credentials['account_id'] or '-'}",
            f"device_id：{self.credentials['device_id'] or '-'}",
            f"access_token：{mask_value(self.credentials['access_token'])}",
            f"session_token：{mask_value(self.credentials['session_token'])}",
            f"client_build_number：{self.credentials['client_build_number'] or '-'}",
            f"client_version：{self.credentials['client_version'] or '-'}",
            f"base_url：{self.credentials['base_url'] or '-'}",
        ]
        self.summary_var.set("\n".join(lines))

    def _handle_auto_refresh_changed(self, *_args) -> None:
        """在自动刷新选择变化时重建定时器。"""

        self.persist_ui_settings()
        self.schedule_auto_refresh()

    def get_chatgpt_seat_limit(self) -> int:
        """读取固定的 ChatGPT 席位上限。"""

        return DEFAULT_CHATGPT_SEAT_LIMIT

    def get_auto_refresh_seconds(self) -> int:
        """读取当前自动刷新秒数。"""

        current_label = str(self.auto_refresh_var.get() or "").strip()
        for label, seconds in AUTO_REFRESH_OPTIONS:
            if label == current_label:
                return seconds
        fallback_seconds = AUTO_REFRESH_OPTIONS[0][1]
        self.auto_refresh_var.set(AUTO_REFRESH_OPTIONS[0][0])
        return fallback_seconds

    def get_auto_refresh_label_from_seconds(self, raw_seconds: object) -> str:
        """把秒数转成自动刷新选项标签。"""

        try:
            seconds = int(raw_seconds)
        except (TypeError, ValueError):
            seconds = AUTO_REFRESH_DISABLED
        for label, candidate_seconds in AUTO_REFRESH_OPTIONS:
            if candidate_seconds == seconds:
                return label
        return AUTO_REFRESH_OPTIONS[0][0]

    def cancel_auto_refresh(self) -> None:
        """取消当前自动刷新计时器。"""

        if self.auto_refresh_after_id is None:
            return
        self.root.after_cancel(self.auto_refresh_after_id)
        self.auto_refresh_after_id = None

    def schedule_auto_refresh(self) -> None:
        """根据当前设置安排下一次自动刷新。"""

        self.cancel_auto_refresh()
        seconds = self.get_auto_refresh_seconds()
        if seconds <= 0:
            return
        self.auto_refresh_after_id = self.root.after(
            seconds * 1000,
            self._handle_auto_refresh_tick,
        )

    def _handle_auto_refresh_tick(self) -> None:
        """到达自动刷新时间后触发一次远程刷新。"""

        self.auto_refresh_after_id = None
        if self.busy:
            self.schedule_auto_refresh()
            return
        self.refresh_remote_usage(announce_error=False, from_auto_refresh=True)

    def is_chatgpt_seat_type(self, seat_type: str | None) -> bool:
        """判断当前 seat_type 是否代表 ChatGPT。"""

        return str(seat_type or "").strip().lower() in {"default", "null"}

    def count_chatgpt_users(
        self,
        users: list[dict[str, Any]] | None = None,
    ) -> int:
        """统计成员列表里的 ChatGPT 席位数量。"""

        target_users = self.current_users if users is None else users
        return sum(
            1
            for user in target_users
            if self.is_chatgpt_seat_type(user.get("seat_type"))
        )

    def update_member_stats(self) -> None:
        """刷新成员总数和 ChatGPT 席位统计。"""

        total_count = len(self.current_users)
        chatgpt_count = self.count_chatgpt_users()
        limit = self.get_chatgpt_seat_limit()
        self.member_count_var.set(f"成员：{total_count}")
        self.chatgpt_count_var.set(f"ChatGPT：{chatgpt_count}/{limit}")

    def is_codex_seat_type(self, seat_type: str | None) -> bool:
        """判断当前 seat_type 是否代表 Codex。"""

        return str(seat_type or "").strip().lower() == SEAT_ACTIONS["Codex"]

    def get_user_live_remote_usage_snapshot(
        self,
        user: dict[str, Any],
    ) -> Sub2APIUsageSnapshot | None:
        """按邮箱获取当前成员对应的远程即时快照。"""

        email_address = normalize_email(user.get("email"))
        if not email_address:
            return None
        return self.remote_usage_lookup.get(email_address)

    def get_user_trusted_usage_snapshot(
        self,
        user: dict[str, Any],
    ) -> Sub2APIUsageSnapshot | None:
        """按邮箱获取当前成员对应的本地可信额度缓存。"""

        email_address = normalize_email(user.get("email"))
        if not email_address:
            return None
        return self.trusted_usage_lookup.get(email_address)

    def get_user_remote_usage_snapshot(
        self,
        user: dict[str, Any],
    ) -> Sub2APIUsageSnapshot | None:
        """按席位类型返回当前成员用于展示的额度快照。"""

        if self.is_codex_seat_type(user.get("seat_type")):
            return self.get_user_trusted_usage_snapshot(user)
        return self.get_user_live_remote_usage_snapshot(user)

    def get_user_policy_snapshot(
        self,
        user: dict[str, Any],
    ) -> Sub2APIUsageSnapshot | None:
        """按自动策略所需的可信度返回额度快照。"""

        if self.is_codex_seat_type(user.get("seat_type")):
            return self.get_user_trusted_usage_snapshot(user) or self.get_user_live_remote_usage_snapshot(user)
        return self.get_user_live_remote_usage_snapshot(user)

    def get_user_promotion_reference_snapshot(
        self,
        user: dict[str, Any],
    ) -> Sub2APIUsageSnapshot | None:
        """返回自动补位时用于决策的本地可信额度快照。"""

        if self.is_codex_seat_type(user.get("seat_type")):
            return self.get_user_trusted_usage_snapshot(user)
        return self.get_user_live_remote_usage_snapshot(user)

    def has_remaining_quota(
        self,
        snapshot: Sub2APIUsageSnapshot | None,
        *,
        window: str,
    ) -> bool:
        """判断快照在指定窗口内是否还有额度。"""

        if snapshot is None:
            return False
        if window == "5h":
            return (snapshot.quota_5h_remaining_percent or 0.0) > 0
        return (snapshot.quota_7d_remaining_percent or 0.0) > 0

    def get_current_datetime(self) -> datetime:
        """统一返回当前本地时间，方便自动策略和测试复用。"""

        return datetime.now().astimezone()

    def is_snapshot_reset_due(
        self,
        snapshot: Sub2APIUsageSnapshot | None,
        *,
        window: str,
    ) -> bool:
        """判断指定窗口的刷新时间是否已到。"""

        if snapshot is None:
            return False
        reset_at_text = snapshot.quota_5h_reset_at if window == "5h" else snapshot.quota_7d_reset_at
        reset_at = parse_optional_datetime(reset_at_text)
        if reset_at is None:
            return False
        return self.get_current_datetime() >= reset_at.astimezone()

    def should_demote_user_to_codex(
        self,
        user: dict[str, Any],
        snapshot: Sub2APIUsageSnapshot | None,
    ) -> bool:
        """判断当前成员是否应该自动降为 Codex。"""

        if not self.is_chatgpt_seat_type(user.get("seat_type")):
            return False
        if snapshot is None:
            return False
        return (
            not self.has_remaining_quota(snapshot, window="5h")
            or not self.has_remaining_quota(snapshot, window="7d")
        )

    def should_promote_user_to_chatgpt(
        self,
        user: dict[str, Any],
        snapshot: Sub2APIUsageSnapshot | None,
    ) -> bool:
        """当前底层架构禁止 Codex 自动升回 ChatGPT。"""

        return False

    def get_remote_plan_type_lookup(
        self,
        summaries: list[Sub2APIRemoteAccountSummary] | None = None,
    ) -> dict[str, str]:
        """把远程账号类型摘要整理成按邮箱可查的映射。"""

        target_summaries = self.remote_account_summaries if summaries is None else summaries
        return {
            normalize_email(item.email): str(item.plan_type or "").strip().lower()
            for item in target_summaries
            if normalize_email(item.email)
        }

    def is_remote_team_user(
        self,
        email_address: str,
        summaries: list[Sub2APIRemoteAccountSummary] | None = None,
    ) -> bool:
        """判断远程账号当前是否识别为 team 类型。"""

        plan_type_lookup = self.get_remote_plan_type_lookup(summaries)
        return plan_type_lookup.get(normalize_email(email_address)) == "team"

    def is_promotion_probe_in_cooldown(
        self,
        user: dict[str, Any],
    ) -> bool:
        """判断当前成员是否还在自动补位探测冷却中。"""

        email_address = normalize_email(user.get("email"))
        if not email_address:
            return False
        cooldown_lookup = getattr(self, "promotion_probe_cooldowns", {})
        cooldown_until = cooldown_lookup.get(email_address)
        if cooldown_until is None:
            return False
        if self.get_current_datetime() >= cooldown_until:
            self.promotion_probe_cooldowns.pop(email_address, None)
            return False
        return True

    def calculate_promotion_probe_cooldown_until(
        self,
        snapshot: Sub2APIUsageSnapshot | None,
    ) -> datetime:
        """给补位探测失败的账号计算下一次可重试时间。"""

        fallback_until = self.get_current_datetime() + timedelta(
            minutes=PROMOTION_PROBE_COOLDOWN_MINUTES
        )
        if snapshot is None:
            return fallback_until
        reset_candidates = [
            parse_optional_datetime(snapshot.quota_5h_reset_at),
            parse_optional_datetime(snapshot.quota_7d_reset_at),
        ]
        future_candidates = [
            candidate.astimezone()
            for candidate in reset_candidates
            if candidate is not None and candidate.astimezone() > fallback_until
        ]
        if not future_candidates:
            return fallback_until
        return min(future_candidates)

    def mark_promotion_probe_cooldown(
        self,
        user: dict[str, Any],
        snapshot: Sub2APIUsageSnapshot | None,
    ) -> None:
        """记录账号补位探测失败后的冷却截止时间。"""

        email_address = normalize_email(user.get("email"))
        if not email_address:
            return
        cooldown_lookup = getattr(self, "promotion_probe_cooldowns", None)
        if cooldown_lookup is None:
            cooldown_lookup = {}
            self.promotion_probe_cooldowns = cooldown_lookup
        cooldown_until = self.calculate_promotion_probe_cooldown_until(snapshot)
        cooldown_lookup[email_address] = cooldown_until
        self.write_log(
            "[AUTO][COOLDOWN] "
            f"{email_address} 冷却到 {cooldown_until.isoformat(timespec='seconds')}"
        )

    def clear_promotion_probe_cooldown(
        self,
        user: dict[str, Any],
    ) -> None:
        """探测成功后清理账号冷却状态。"""

        email_address = normalize_email(user.get("email"))
        if not email_address:
            return
        cooldown_lookup = getattr(self, "promotion_probe_cooldowns", None)
        if cooldown_lookup is None:
            return
        if email_address in cooldown_lookup:
            self.write_log(f"[AUTO][COOLDOWN][CLEAR] {email_address}")
        cooldown_lookup.pop(email_address, None)

    def remember_trusted_snapshot(
        self,
        email_address: str,
        snapshot: Sub2APIUsageSnapshot | None,
        summaries: list[Sub2APIRemoteAccountSummary] | None = None,
    ) -> None:
        """把探测得到的可信额度写回本地内存缓存。"""

        normalized_email = normalize_email(email_address)
        if not normalized_email or snapshot is None:
            return
        if not self.is_remote_team_user(normalized_email, summaries):
            self.write_log(
                f"[AUTO][CACHE][SKIP_NON_TEAM] {normalized_email} 当前非 team，跳过本地可信额度写入"
            )
            return
        self.trusted_usage_lookup[normalized_email] = snapshot
        self.write_log(
            "[AUTO][CACHE] "
            f"{normalized_email} 5h={snapshot.quota_5h_text} "
            f"7d={snapshot.quota_7d_text} status={snapshot.account_status or '--'} "
            f"updated={snapshot.usage_updated_at or '--'}"
        )

    def build_placeholder_created_account_snapshot(
        self,
        *,
        email_address: str,
        account_id: int,
        account_name: str,
    ) -> Sub2APIUsageSnapshot:
        """为刚通过 OAuth 导入的账号生成本地 100% 占位额度。"""

        return Sub2APIUsageSnapshot(
            account_id=account_id,
            name=account_name,
            email=email_address,
            quota_5h_text="剩100.00%",
            quota_7d_text="剩100.00%",
            usage_updated_at="",
            quota_5h_remaining_percent=100.0,
            quota_7d_remaining_percent=100.0,
            account_status="inactive",
        )

    def seed_created_remote_oauth_account_locally(
        self,
        *,
        email_address: str,
        account_id: int,
        account_name: str,
    ) -> None:
        """把新建远程账号写成本地占位候选，默认保持 inactive。"""

        normalized_email = normalize_email(email_address)
        if not normalized_email or account_id <= 0:
            return
        placeholder_snapshot = self.build_placeholder_created_account_snapshot(
            email_address=normalized_email,
            account_id=account_id,
            account_name=account_name,
        )
        self.remote_usage_lookup[normalized_email] = placeholder_snapshot
        self.trusted_usage_lookup[normalized_email] = placeholder_snapshot
        existing_summary_ids = {item.account_id for item in self.remote_account_summaries}
        if account_id not in existing_summary_ids:
            self.remote_account_summaries.append(
                Sub2APIRemoteAccountSummary(
                    account_id=account_id,
                    email=normalized_email,
                    name=account_name,
                    plan_type="oauth",
                    status="inactive",
                )
            )
        write_usage_cache(USAGE_CACHE_PATH, self.trusted_usage_lookup)
        self.write_log(
            f"[OAUTH][CACHE][PLACEHOLDER] {normalized_email} 已写入本地 100% 占位额度，默认关闭调度"
        )

    def rank_promotion_candidate(
        self,
        user: dict[str, Any],
    ) -> tuple[int, str]:
        """给自动补位候选账号排序，优先用已经确认有额度的号。"""

        email_address = normalize_email(user.get("email"))
        reference_snapshot = self.get_user_promotion_reference_snapshot(user)
        if self.is_codex_seat_type(user.get("seat_type")) and reference_snapshot is None:
            return (3, email_address)
        snapshot = reference_snapshot or self.get_user_policy_snapshot(user)
        if snapshot is None:
            return (4, email_address)
        has_7d_quota = self.has_remaining_quota(snapshot, window="7d")
        has_5h_quota = self.has_remaining_quota(snapshot, window="5h")
        if has_7d_quota and has_5h_quota:
            return (0, email_address)
        if has_7d_quota and self.is_snapshot_reset_due(snapshot, window="5h"):
            return (1, email_address)
        if self.is_snapshot_reset_due(snapshot, window="7d"):
            return (2, email_address)
        return (5, email_address)

    def get_snapshot_for_email(
        self,
        email_address: str,
        lookup: dict[str, Sub2APIUsageSnapshot],
    ) -> Sub2APIUsageSnapshot | None:
        """按邮箱从指定快照字典里读取账号额度。"""

        normalized_email = normalize_email(email_address)
        if not normalized_email:
            return None
        return lookup.get(normalized_email)

    def is_candidate_ready_for_chatgpt_after_probe(
        self,
        user: dict[str, Any],
        live_lookup: dict[str, Sub2APIUsageSnapshot],
        summaries: list[Sub2APIRemoteAccountSummary],
    ) -> bool:
        """在临时切到 ChatGPT 并 refresh 后，判断是否满足最终放行条件。"""

        email_address = normalize_email(user.get("email"))
        if not email_address or not self.is_remote_team_user(email_address, summaries):
            return False
        snapshot = self.get_snapshot_for_email(email_address, live_lookup)
        if snapshot is None:
            return False
        return self.has_remaining_quota(snapshot, window="5h") and self.has_remaining_quota(
            snapshot,
            window="7d",
        )

    def should_revert_promoted_user_after_probe(
        self,
        user: dict[str, Any],
        live_lookup: dict[str, Sub2APIUsageSnapshot],
        summaries: list[Sub2APIRemoteAccountSummary],
    ) -> bool:
        """判断临时补位后的账号是否需要回退为 Codex。"""

        email_address = normalize_email(user.get("email"))
        if not email_address:
            return True
        if not self.is_remote_team_user(email_address, summaries):
            return True
        snapshot = self.get_snapshot_for_email(email_address, live_lookup)
        if snapshot is None:
            return True
        if self.has_remaining_quota(snapshot, window="5h") and self.has_remaining_quota(
            snapshot,
            window="7d",
        ):
            return False
        return True

    def refresh_remote_candidates_for_promotion(
        self,
        users: list[dict[str, Any]],
    ) -> Sub2APIUsageLoadResult | None:
        """对待补位账号先做一次 Sub2API refresh，再重拉最新快照。"""

        candidate_ids = self.collect_remote_account_ids_for_users(users)
        if not candidate_ids:
            return None
        remote_transition = self.refresh_remote_tokens_after_seat_change(
            candidate_ids,
            log_prefix="[AUTO][PROMOTE][PRECHECK]",
        )
        if not remote_transition.get("refreshed_remote_ids"):
            return None
        return load_sub2api_usage_lookup()

    def normalize_remote_account_ids(
        self,
        account_ids: list[int] | tuple[int, ...],
    ) -> list[int]:
        """把远程账号 ID 规整成去重后的正整数列表。"""

        normalized_ids: list[int] = []
        seen_ids: set[int] = set()
        for account_id in (account_ids or []):
            try:
                normalized_id = int(account_id)
            except (TypeError, ValueError):
                continue
            if normalized_id <= 0 or normalized_id in seen_ids:
                continue
            seen_ids.add(normalized_id)
            normalized_ids.append(normalized_id)
        normalized_ids.sort()
        return normalized_ids

    def extract_remote_success_ids(
        self,
        remote_result: dict[str, Any] | None,
        *,
        fallback_ids: list[int] | tuple[int, ...] = (),
    ) -> list[int]:
        """从远程操作结果里提取可信成功 ID。"""

        normalized_fallback_ids = self.normalize_remote_account_ids(fallback_ids)
        if not isinstance(remote_result, dict):
            return []
        success_ids = self.normalize_remote_account_ids(
            remote_result.get("success_ids") or []
        )
        if success_ids:
            return success_ids
        success_count = int(remote_result.get("success", 0) or 0)
        failed_count = int(remote_result.get("failed", 0) or 0)
        if normalized_fallback_ids and success_count == len(normalized_fallback_ids) and failed_count == 0:
            return normalized_fallback_ids
        return []

    def stringify_remote_result_detail(
        self,
        detail: Any,
    ) -> str:
        """把远程返回的 detail 压成一行易读文本。"""

        if isinstance(detail, (dict, list)):
            text = json.dumps(detail, ensure_ascii=False, sort_keys=True)
        else:
            text = str(detail or "").strip()
        text = text.replace("\r", " ").replace("\n", " ").strip()
        if len(text) > 320:
            return f"{text[:320]}..."
        return text

    def collect_remote_result_detail_messages(
        self,
        remote_result: dict[str, Any] | None,
    ) -> list[str]:
        """收集远程操作里的 errors / warnings / results 明细。"""

        if not isinstance(remote_result, dict):
            return []
        detail_messages: list[str] = []
        seen_messages: set[str] = set()
        for field_name in ("errors", "warnings", "results"):
            items = remote_result.get(field_name) or []
            if not isinstance(items, list):
                items = [items]
            for item in items:
                detail_text = self.stringify_remote_result_detail(item)
                if not detail_text or detail_text in seen_messages:
                    continue
                seen_messages.add(detail_text)
                detail_messages.append(detail_text)
        return detail_messages

    def find_remote_refresh_block_reasons(
        self,
        refresh_result: dict[str, Any] | None,
    ) -> list[str]:
        """识别 refresh 结果里是否出现限流或 usage_limit_reached。"""

        block_reasons: list[str] = []
        for detail_text in self.collect_remote_result_detail_messages(refresh_result):
            normalized_text = detail_text.lower()
            if any(
                marker in normalized_text
                for marker in (
                    "usage_limit_reached",
                    "http 429",
                    "status\": 429",
                    "status: 429",
                    "rate limit",
                    "rate_limit",
                    "too many requests",
                    "429 ",
                )
            ):
                block_reasons.append(detail_text)
        return block_reasons

    def log_remote_batch_result(
        self,
        log_prefix: str,
        step_label: str,
        remote_result: dict[str, Any] | None,
        *,
        fallback_ids: list[int] | tuple[int, ...] = (),
    ) -> None:
        """统一打印 recover / refresh / active / inactive 的远程返回。"""

        if not isinstance(remote_result, dict):
            self.write_log(f"{log_prefix}{step_label}[FAIL] 远程返回为空")
            return
        if remote_result.get("skipped"):
            self.write_log(f"{log_prefix}{step_label}[SKIP] 无可处理账号")
            return
        success_ids = self.extract_remote_success_ids(
            remote_result,
            fallback_ids=fallback_ids,
        )
        failed_ids = self.normalize_remote_account_ids(remote_result.get("failed_ids") or [])
        success_count = int(remote_result.get("success", len(success_ids)) or 0)
        failed_count = int(remote_result.get("failed", len(failed_ids)) or 0)
        if failed_count <= 0:
            status_label = "OK"
        elif success_count > 0:
            status_label = "PARTIAL"
        else:
            status_label = "FAIL"
        self.write_log(
            f"{log_prefix}{step_label}[{status_label}] "
            f"success={success_count} failed={failed_count} "
            f"success_ids={success_ids} failed_ids={failed_ids}"
        )
        for detail_text in self.collect_remote_result_detail_messages(remote_result):
            self.write_log(f"{log_prefix}{step_label}[DETAIL] {detail_text}")

    def refresh_remote_tokens_after_seat_change(
        self,
        account_ids: list[int] | tuple[int, ...],
        *,
        log_prefix: str,
        keep_local_cache_message: str | None = None,
    ) -> dict[str, Any]:
        """在席位切换成功后，先 recover-state，再 refresh token。"""

        normalized_ids = self.normalize_remote_account_ids(account_ids)
        if not normalized_ids:
            self.write_log(f"{log_prefix}[REFRESH_TOKEN][SKIP] 未匹配到远程账号 ID")
            return {
                "requested_remote_ids": [],
                "recovered_remote_ids": [],
                "refreshed_remote_ids": [],
                "recover_result": {"skipped": True},
                "refresh_result": {"skipped": True},
                "blocked": False,
                "blocked_reasons": [],
            }
        self.write_log(f"{log_prefix}[RECOVER] account_ids={normalized_ids}")
        recover_result = recover_remote_accounts_state(normalized_ids)
        self.log_remote_batch_result(
            log_prefix,
            "[RECOVER]",
            recover_result,
            fallback_ids=normalized_ids,
        )
        recovered_remote_ids = self.extract_remote_success_ids(
            recover_result,
            fallback_ids=normalized_ids,
        )
        if not recovered_remote_ids:
            return {
                "requested_remote_ids": normalized_ids,
                "recovered_remote_ids": [],
                "refreshed_remote_ids": [],
                "recover_result": recover_result,
                "refresh_result": {"skipped": True},
                "blocked": False,
                "blocked_reasons": [],
            }
        self.write_log(f"{log_prefix}[REFRESH_TOKEN] account_ids={recovered_remote_ids}")
        refresh_result = refresh_remote_accounts_serial(recovered_remote_ids)
        self.log_remote_batch_result(
            log_prefix,
            "[REFRESH_TOKEN]",
            refresh_result,
            fallback_ids=recovered_remote_ids,
        )
        refreshed_remote_ids = self.extract_remote_success_ids(
            refresh_result,
            fallback_ids=recovered_remote_ids,
        )
        blocked_reasons = self.find_remote_refresh_block_reasons(refresh_result)
        for blocked_reason in blocked_reasons:
            self.write_log(f"{log_prefix}[REFRESH_TOKEN][BLOCK] {blocked_reason}")
        if keep_local_cache_message:
            self.write_log(f"{log_prefix}[KEEP_LOCAL_CACHE] {keep_local_cache_message}")
        return {
            "requested_remote_ids": normalized_ids,
            "recovered_remote_ids": recovered_remote_ids,
            "refreshed_remote_ids": refreshed_remote_ids,
            "recover_result": recover_result,
            "refresh_result": refresh_result,
            "blocked": bool(blocked_reasons),
            "blocked_reasons": blocked_reasons,
        }

    def evaluate_remote_call_policy_for_chatgpt_user(
        self,
        user: dict[str, Any],
        live_lookup: dict[str, Sub2APIUsageSnapshot],
        summaries: list[Sub2APIRemoteAccountSummary],
    ) -> bool:
        """判断手动切到 ChatGPT 后，是否允许开启远程调用。"""

        email_address = normalize_email(user.get("email"))
        if not email_address or not self.is_remote_team_user(email_address, summaries):
            return False
        snapshot = self.get_snapshot_for_email(email_address, live_lookup)
        if snapshot is None:
            return False
        return self.has_remaining_quota(snapshot, window="5h") and self.has_remaining_quota(
            snapshot,
            window="7d",
        )

    def postprocess_manual_seat_change_remote_state(
        self,
        user: dict[str, Any],
        ensure_result: dict[str, Any],
        target_seat_type: str,
    ) -> dict[str, Any]:
        """在手动切席位成功后，立即校验并同步远程调用状态。"""

        remote_ids = self.collect_remote_account_ids_for_users(
            [ensure_result.get("user") or user]
        )
        response: dict[str, Any] = {
            "refreshed_remote_ids": [],
            "enabled_remote_ids": [],
            "disabled_remote_ids": [],
            "latest_usage_result": None,
        }
        if not ensure_result.get("changed") or not remote_ids:
            return response
        remote_transition = self.refresh_remote_tokens_after_seat_change(
            remote_ids,
            log_prefix="[MANUAL][SEAT]",
            keep_local_cache_message=(
                "手动转 Codex 后仅 refresh token，本地额度仍以可信缓存为主"
                if target_seat_type == SEAT_ACTIONS["Codex"]
                else None
            ),
        )
        refreshed_remote_ids = self.normalize_remote_account_ids(
            remote_transition.get("refreshed_remote_ids") or []
        )
        response["refreshed_remote_ids"] = refreshed_remote_ids
        if target_seat_type == SEAT_ACTIONS["Codex"]:
            self.write_log(f"[MANUAL][SEAT][DISABLE] remote_ids={remote_ids}")
            disable_result = set_remote_accounts_inactive(remote_ids)
            self.log_remote_batch_result(
                "[MANUAL][SEAT]",
                "[DISABLE]",
                disable_result,
                fallback_ids=remote_ids,
            )
            response["disabled_remote_ids"] = self.extract_remote_success_ids(
                disable_result,
                fallback_ids=remote_ids,
            )
            return response
        if remote_transition.get("blocked"):
            self.write_log(
                "[MANUAL][SEAT][DISABLE][REASON] refresh 命中限流或 usage_limit_reached，禁止放行"
            )
        if not refreshed_remote_ids or remote_transition.get("blocked"):
            self.write_log(f"[MANUAL][SEAT][DISABLE] remote_ids={remote_ids}")
            disable_result = set_remote_accounts_inactive(remote_ids)
            self.log_remote_batch_result(
                "[MANUAL][SEAT]",
                "[DISABLE]",
                disable_result,
                fallback_ids=remote_ids,
            )
            response["disabled_remote_ids"] = self.extract_remote_success_ids(
                disable_result,
                fallback_ids=remote_ids,
            )
            return response

        latest_usage_result = load_sub2api_usage_lookup()
        response["latest_usage_result"] = latest_usage_result
        latest_lookup = dict(latest_usage_result.lookup)
        latest_summaries = list(latest_usage_result.summaries)
        email_address = normalize_email(user.get("email"))
        snapshot = self.get_snapshot_for_email(email_address, latest_lookup)
        if snapshot is not None:
            self.write_log(
                "[MANUAL][SEAT][REFRESHED] "
                f"{email_address} 5h={snapshot.quota_5h_text} "
                f"7d={snapshot.quota_7d_text} status={snapshot.account_status or '--'} "
                f"updated={snapshot.usage_updated_at or '--'}"
            )
        if self.evaluate_remote_call_policy_for_chatgpt_user(
            ensure_result.get("user") or user,
            latest_lookup,
            latest_summaries,
        ):
            self.write_log(f"[MANUAL][SEAT][ENABLE] remote_ids={refreshed_remote_ids}")
            enable_result = set_remote_accounts_status(refreshed_remote_ids, "active")
            self.log_remote_batch_result(
                "[MANUAL][SEAT]",
                "[ENABLE]",
                enable_result,
                fallback_ids=refreshed_remote_ids,
            )
            response["enabled_remote_ids"] = self.extract_remote_success_ids(
                enable_result,
                fallback_ids=refreshed_remote_ids,
            )
            return response
        self.write_log(f"[MANUAL][SEAT][DISABLE] remote_ids={remote_ids}")
        disable_result = set_remote_accounts_inactive(remote_ids)
        self.log_remote_batch_result(
            "[MANUAL][SEAT]",
            "[DISABLE]",
            disable_result,
            fallback_ids=remote_ids,
        )
        response["disabled_remote_ids"] = self.extract_remote_success_ids(
            disable_result,
            fallback_ids=remote_ids,
        )
        return response

    def filter_promotable_users_after_refresh(
        self,
        users: list[dict[str, Any]],
        live_lookup: dict[str, Sub2APIUsageSnapshot],
        summaries: list[Sub2APIRemoteAccountSummary],
    ) -> list[dict[str, Any]]:
        """只保留 refresh 后确认仍满足补位条件的账号。"""

        promotable_users: list[dict[str, Any]] = []
        for user in users:
            email_address = normalize_email(user.get("email"))
            if not email_address or not self.is_remote_team_user(email_address, summaries):
                continue
            snapshot = live_lookup.get(email_address)
            if snapshot is None:
                continue
            if not self.has_remaining_quota(snapshot, window="5h"):
                continue
            if not self.has_remaining_quota(snapshot, window="7d"):
                continue
            promotable_users.append(user)
        return promotable_users

    def build_snapshot_refresh_text(
        self,
        snapshot: Sub2APIUsageSnapshot | None,
        *,
        window: str,
    ) -> str:
        """把额度刷新时间转换成表格文案。"""

        if snapshot is None:
            return "--"
        if window == "5h":
            return format_reset_eta_text(
                snapshot.quota_5h_reset_at,
                snapshot.quota_5h_reset_after_seconds,
            )
        return format_reset_eta_text(
            snapshot.quota_7d_reset_at,
            snapshot.quota_7d_reset_after_seconds,
        )

    def build_codex_cache_missing_row(self) -> tuple[str, str, str, str]:
        """为缺少可信缓存的 Codex 成员生成提示文案。"""

        return ("缓存缺失", "缓存缺失", "缓存缺失", "缓存缺失")

    def build_user_table_values(
        self,
        user: dict[str, Any],
    ) -> tuple[str, str, str, str, str, str, str]:
        """构造成员表格的一整行显示值。"""

        quota_5h_text = "--"
        quota_7d_text = "--"
        quota_5h_refresh_text = "--"
        quota_7d_refresh_text = "--"
        if self.remote_usage_loaded:
            live_snapshot = self.get_user_live_remote_usage_snapshot(user)
            display_snapshot = self.get_user_remote_usage_snapshot(user)
            if display_snapshot is None:
                if self.is_codex_seat_type(user.get("seat_type")) and live_snapshot is not None:
                    (
                        quota_5h_text,
                        quota_7d_text,
                        quota_5h_refresh_text,
                        quota_7d_refresh_text,
                    ) = self.build_codex_cache_missing_row()
                else:
                    quota_5h_text = "未导入"
                    quota_7d_text = "未导入"
                    quota_5h_refresh_text = "未导入"
                    quota_7d_refresh_text = "未导入"
            else:
                quota_5h_text = display_snapshot.quota_5h_text
                quota_7d_text = display_snapshot.quota_7d_text
                quota_5h_refresh_text = self.build_snapshot_refresh_text(
                    display_snapshot,
                    window="5h",
                )
                quota_7d_refresh_text = self.build_snapshot_refresh_text(
                    display_snapshot,
                    window="7d",
                )
        return (
            str(user.get("id", "")),
            str(user.get("email", "")),
            core.seat_label(user.get("seat_type")),
            quota_5h_text,
            quota_7d_text,
            quota_5h_refresh_text,
            quota_7d_refresh_text,
        )

    def merge_trusted_usage_lookup(
        self,
        live_lookup: dict[str, Sub2APIUsageSnapshot],
        summaries: list[Sub2APIRemoteAccountSummary] | None = None,
    ) -> dict[str, Sub2APIUsageSnapshot]:
        """按席位策略合并可信缓存，避免 Codex 被远程 100% 覆盖。"""

        merged_lookup = dict(self.trusted_usage_lookup)
        target_summaries = self.remote_account_summaries if summaries is None else summaries
        user_lookup = {
            normalize_email(user.get("email")): user
            for user in self.current_users
            if normalize_email(user.get("email"))
        }
        for email_address, live_snapshot in (live_lookup or {}).items():
            if not self.is_remote_team_user(email_address, target_summaries):
                continue
            current_user = user_lookup.get(email_address)
            if current_user and self.is_codex_seat_type(current_user.get("seat_type")):
                cached_snapshot = merged_lookup.get(email_address)
                if cached_snapshot is None:
                    continue
                has_cached_5h = cached_snapshot.quota_5h_remaining_percent is not None
                has_cached_7d = cached_snapshot.quota_7d_remaining_percent is not None
                has_any_cached_quota = has_cached_5h or has_cached_7d
                merged_lookup[email_address] = replace(
                    cached_snapshot,
                    account_id=live_snapshot.account_id or cached_snapshot.account_id,
                    name=live_snapshot.name or cached_snapshot.name,
                    email=live_snapshot.email or cached_snapshot.email,
                    quota_5h_text=(
                        live_snapshot.quota_5h_text
                        if not has_cached_5h
                        else cached_snapshot.quota_5h_text
                    ),
                    quota_7d_text=(
                        live_snapshot.quota_7d_text
                        if not has_cached_7d
                        else cached_snapshot.quota_7d_text
                    ),
                    usage_updated_at=(
                        cached_snapshot.usage_updated_at
                        if has_any_cached_quota and cached_snapshot.usage_updated_at
                        else (live_snapshot.usage_updated_at or cached_snapshot.usage_updated_at)
                    ),
                    quota_5h_remaining_percent=(
                        live_snapshot.quota_5h_remaining_percent
                        if not has_cached_5h
                        else cached_snapshot.quota_5h_remaining_percent
                    ),
                    quota_7d_remaining_percent=(
                        live_snapshot.quota_7d_remaining_percent
                        if not has_cached_7d
                        else cached_snapshot.quota_7d_remaining_percent
                    ),
                    account_status=live_snapshot.account_status or cached_snapshot.account_status,
                    quota_5h_reset_at=(
                        cached_snapshot.quota_5h_reset_at
                        if has_cached_5h and cached_snapshot.quota_5h_reset_at
                        else (live_snapshot.quota_5h_reset_at or cached_snapshot.quota_5h_reset_at)
                    ),
                    quota_7d_reset_at=(
                        cached_snapshot.quota_7d_reset_at
                        if has_cached_7d and cached_snapshot.quota_7d_reset_at
                        else (live_snapshot.quota_7d_reset_at or cached_snapshot.quota_7d_reset_at)
                    ),
                    quota_5h_reset_after_seconds=(
                        live_snapshot.quota_5h_reset_after_seconds
                        if (not has_cached_5h and cached_snapshot.quota_5h_reset_after_seconds is None)
                        else cached_snapshot.quota_5h_reset_after_seconds
                    ),
                    quota_7d_reset_after_seconds=(
                        live_snapshot.quota_7d_reset_after_seconds
                        if (not has_cached_7d and cached_snapshot.quota_7d_reset_after_seconds is None)
                        else cached_snapshot.quota_7d_reset_after_seconds
                    ),
                )
                continue
            merged_lookup[email_address] = live_snapshot
        return merged_lookup

    def get_user_by_email(
        self,
        email_address: str,
        *,
        include_cached: bool = False,
    ) -> dict[str, Any] | None:
        """按邮箱查找成员，必要时回退到成员缓存。"""

        normalized_email = normalize_email(email_address)
        if not normalized_email:
            return None
        for user in self.current_users:
            if normalize_email(user.get("email")) == normalized_email:
                return user
        if not include_cached:
            return None
        for user in read_member_list_cache(MEMBER_LIST_CACHE_PATH):
            if normalize_email(user.get("email")) == normalized_email:
                return user
        return None

    def get_codex_remote_account_ids_to_disable(
        self,
        live_lookup: dict[str, Sub2APIUsageSnapshot] | None = None,
    ) -> list[int]:
        """找出当前成员里需要在 Sub2API 停用调用的 Codex 账号。"""

        target_lookup = self.remote_usage_lookup if live_lookup is None else live_lookup
        account_ids: list[int] = []
        seen_ids: set[int] = set()
        for user in self.current_users:
            if not self.is_codex_seat_type(user.get("seat_type")):
                continue
            snapshot = target_lookup.get(normalize_email(user.get("email")))
            if snapshot is None or snapshot.account_id <= 0:
                continue
            if snapshot.account_status == "inactive" or snapshot.account_id in seen_ids:
                continue
            seen_ids.add(snapshot.account_id)
            account_ids.append(snapshot.account_id)
        return account_ids

    def get_chatgpt_remote_account_ids_to_enable(
        self,
        live_lookup: dict[str, Sub2APIUsageSnapshot] | None = None,
    ) -> list[int]:
        """找出当前成员里应该在 Sub2API 自动恢复调用的 ChatGPT 账号。"""

        target_lookup = self.remote_usage_lookup if live_lookup is None else live_lookup
        account_ids: list[int] = []
        seen_ids: set[int] = set()
        for user in self.current_users:
            if not self.is_chatgpt_seat_type(user.get("seat_type")):
                continue
            snapshot = target_lookup.get(normalize_email(user.get("email")))
            if snapshot is None or snapshot.account_id <= 0:
                continue
            if snapshot.account_status == "active" or snapshot.account_id in seen_ids:
                continue
            if self.should_demote_user_to_codex(user, snapshot):
                continue
            seen_ids.add(snapshot.account_id)
            account_ids.append(snapshot.account_id)
        return account_ids

    def build_usage_lookup_with_status(
        self,
        lookup: dict[str, Sub2APIUsageSnapshot],
        account_ids: list[int] | tuple[int, ...],
        status: str,
    ) -> dict[str, Sub2APIUsageSnapshot]:
        """把指定账号 ID 的本地额度快照状态同步到目标状态。"""

        normalized_ids: set[int] = set()
        for account_id in (account_ids or []):
            try:
                normalized_id = int(account_id)
            except (TypeError, ValueError):
                continue
            if normalized_id > 0:
                normalized_ids.add(normalized_id)
        if not normalized_ids:
            return dict(lookup)
        normalized_status = str(status or "").strip().lower()
        updated_lookup: dict[str, Sub2APIUsageSnapshot] = {}
        for email_address, snapshot in (lookup or {}).items():
            if snapshot.account_id in normalized_ids and snapshot.account_status != normalized_status:
                updated_lookup[email_address] = replace(
                    snapshot,
                    account_status=normalized_status,
                )
            else:
                updated_lookup[email_address] = snapshot
        return updated_lookup

    def build_remote_account_summaries_with_status(
        self,
        summaries: list[Sub2APIRemoteAccountSummary],
        account_ids: list[int] | tuple[int, ...],
        status: str,
    ) -> list[Sub2APIRemoteAccountSummary]:
        """把账号管理表摘要里的状态同步到目标状态。"""

        normalized_ids = {
            int(account_id)
            for account_id in (account_ids or [])
            if str(account_id or "").strip().isdigit() and int(account_id) > 0
        }
        if not normalized_ids:
            return list(summaries)
        normalized_status = str(status or "").strip().lower()
        updated_items: list[Sub2APIRemoteAccountSummary] = []
        for item in summaries or []:
            if item.account_id in normalized_ids:
                updated_items.append(
                    Sub2APIRemoteAccountSummary(
                        account_id=item.account_id,
                        email=item.email,
                        name=item.name,
                        plan_type=item.plan_type,
                        status=normalized_status,
                    )
                )
            else:
                updated_items.append(item)
        return updated_items

    def store_usage_load_result_locally(
        self,
        result: Sub2APIUsageLoadResult | None,
    ) -> None:
        """把一次远程额度结果写回本地状态和缓存文件。"""

        if result is None:
            return
        self.remote_usage_loaded = True
        self.remote_usage_lookup = dict(result.lookup)
        self.remote_account_summaries = list(result.summaries)
        self.trusted_usage_lookup = self.merge_trusted_usage_lookup(
            self.remote_usage_lookup,
            self.remote_account_summaries,
        )
        write_usage_cache(USAGE_CACHE_PATH, self.trusted_usage_lookup)

    def mark_remote_accounts_status_locally(
        self,
        account_ids: list[int] | tuple[int, ...],
        status: str,
    ) -> None:
        """同步更新本地额度快照和账号摘要里的调用状态。"""

        self.remote_usage_lookup = self.build_usage_lookup_with_status(
            self.remote_usage_lookup,
            account_ids,
            status,
        )
        self.trusted_usage_lookup = self.build_usage_lookup_with_status(
            self.trusted_usage_lookup,
            account_ids,
            status,
        )
        self.remote_account_summaries = self.build_remote_account_summaries_with_status(
            self.remote_account_summaries,
            account_ids,
            status,
        )
        write_usage_cache(USAGE_CACHE_PATH, self.trusted_usage_lookup)

    def mark_remote_accounts_inactive_locally(
        self,
        account_ids: list[int] | tuple[int, ...],
    ) -> None:
        """把内存里的远程账号状态同步标记为 inactive。"""

        self.mark_remote_accounts_status_locally(account_ids, "inactive")

    def update_remote_account_summary_status_locally(
        self,
        account_ids: list[int] | tuple[int, ...],
        status: str,
    ) -> None:
        """同步更新账号管理表里的状态。"""

        self.remote_account_summaries = self.build_remote_account_summaries_with_status(
            self.remote_account_summaries,
            account_ids,
            status,
        )

    def refresh_remote_account_table_rows(self) -> None:
        """按当前远程账号摘要重绘账号管理表。"""

        if not hasattr(self, "remote_account_tree"):
            return
        for item_id in self.remote_account_tree.get_children():
            self.remote_account_tree.delete(item_id)
        for item in self.remote_account_summaries:
            self.remote_account_tree.insert(
                "",
                tk.END,
                iid=str(item.account_id),
                values=(
                    item.plan_type,
                    item.email,
                    item.name,
                    item.status or "--",
                    item.account_id,
                ),
            )
        if hasattr(self, "remote_account_summary_var"):
            self.remote_account_summary_var.set(
                f"远程账号：{len(self.remote_account_summaries)} 个"
            )

    def get_selected_remote_account_summaries(self) -> list[Sub2APIRemoteAccountSummary]:
        """读取当前选中的远程账号。"""

        selection_ids = list(self.remote_account_tree.selection())
        if not selection_ids:
            raise core.SeatApiError("请先选中一个 Sub2API 账号。")
        selected_ids = {int(item_id) for item_id in selection_ids}
        selected_items = [
            item for item in self.remote_account_summaries if item.account_id in selected_ids
        ]
        if not selected_items:
            raise core.SeatApiError("当前选中的 Sub2API 账号已失效，请先刷新。")
        return selected_items

    def get_codex_blocked_remote_accounts(
        self,
        selected_items: list[Sub2APIRemoteAccountSummary],
    ) -> tuple[list[Sub2APIRemoteAccountSummary], list[str]]:
        """筛出因 Codex 席位保护而不能启用的远程账号。"""

        allowed_items: list[Sub2APIRemoteAccountSummary] = []
        blocked_emails: list[str] = []
        for item in selected_items:
            matched_user = self.get_user_by_email(item.email, include_cached=True)
            if matched_user and self.is_codex_seat_type(matched_user.get("seat_type")):
                blocked_emails.append(item.email)
                continue
            allowed_items.append(item)
        return allowed_items, blocked_emails

    def change_selected_remote_accounts_status(self, status: str) -> None:
        """批量修改选中远程账号的调用状态。"""

        selected_items = self.get_selected_remote_account_summaries()
        target_items = list(selected_items)
        blocked_emails: list[str] = []
        normalized_status = str(status or "").strip().lower()
        if normalized_status == "active":
            target_items, blocked_emails = self.get_codex_blocked_remote_accounts(selected_items)
            if blocked_emails and not target_items:
                raise core.SeatApiError(
                    "以下账号命中 Codex 成员，禁止开启调用：\n"
                    + "\n".join(blocked_emails)
                )
        account_ids = [item.account_id for item in target_items]
        if not account_ids:
            return
        self.busy = True
        action_label = "开启" if normalized_status == "active" else "关闭"
        self.status_var.set(f"正在批量{action_label} {len(account_ids)} 个 Sub2API 账号...")
        self.update_button_states()

        def run() -> None:
            try:
                result = set_remote_accounts_status(account_ids, normalized_status)
            except Exception as exc:  # noqa: BLE001
                self.root.after(
                    0,
                    lambda captured_error=exc: self.finish_remote_account_status_change(
                        normalized_status,
                        [],
                        blocked_emails,
                        error=captured_error,
                    ),
                )
                return
            self.root.after(
                0,
                lambda captured_result=result: self.finish_remote_account_status_change(
                    normalized_status,
                    account_ids,
                    blocked_emails,
                    result=captured_result,
                ),
            )

        threading.Thread(target=run, daemon=True).start()

    def finish_remote_account_status_change(
        self,
        status: str,
        account_ids: list[int],
        blocked_emails: list[str],
        *,
        result: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        """收尾远程账号调用状态切换。"""

        self.busy = False
        if error is not None:
            self.status_var.set(f"切换远程账号状态失败：{error}")
            self.update_button_states()
            self.show_error_dialog("切换远程账号状态失败", str(error))
            return
        success_ids = result.get("success_ids") if isinstance(result, dict) else account_ids
        success_ids = [int(item) for item in (success_ids or account_ids)]
        self.update_remote_account_summary_status_locally(success_ids, status)
        if status == "inactive":
            self.mark_remote_accounts_inactive_locally(success_ids)
        self.refresh_remote_account_table_rows()
        self.refresh_member_table_rows()
        action_label = "开启" if status == "active" else "关闭"
        status_text = f"已{action_label} {len(success_ids)} 个 Sub2API 账号"
        if blocked_emails:
            status_text += f"，已拦截 {len(blocked_emails)} 个 Codex 成员账号"
        self.status_var.set(status_text)
        self.update_button_states()

    def schedule_auto_seat_policy_evaluation(self) -> None:
        """在成员和额度都可用时触发自动席位策略。"""

        if getattr(self, "auto_seat_policy_running", False) or self.busy:
            return
        if not self.current_users or not self.remote_usage_loaded:
            return
        credentials = getattr(self, "credentials", {}) or {}
        if not (
            str(credentials.get("access_token") or "").strip()
            or str(credentials.get("session_token") or "").strip()
        ):
            return
        if not str(credentials.get("account_id") or "").strip():
            return
        self.auto_seat_policy_running = True
        self.busy = True
        self.status_var.set("正在按额度自动校正席位和 Sub2API 调用...")
        self.write_log(
            "[AUTO][START] "
            f"members={len(self.current_users)} chatgpt={self.count_chatgpt_users()}/{self.get_chatgpt_seat_limit()}"
        )
        self.update_button_states()

        def run() -> None:
            try:
                result = self.execute_auto_seat_policy()
            except Exception as exc:  # noqa: BLE001
                self.root.after(
                    0,
                    lambda captured_error=exc: self.finish_auto_seat_policy(error=captured_error),
                )
                return
            self.root.after(
                0,
                lambda captured_result=result: self.finish_auto_seat_policy(result=captured_result),
            )

        threading.Thread(target=run, daemon=True).start()

    def execute_auto_seat_policy(self) -> dict[str, Any]:
        """执行按额度自动切席位的主策略。"""

        demote_users: list[dict[str, Any]] = []
        current_chatgpt_count = self.count_chatgpt_users()

        for user in self.current_users:
            snapshot = self.get_user_policy_snapshot(user)
            if self.should_demote_user_to_codex(user, snapshot):
                demote_users.append(user)
                self.write_log(
                    "[AUTO][DEMOTE][CANDIDATE] "
                    f"{normalize_email(user.get('email'))} "
                    f"seat={user.get('seat_type')} "
                    f"5h={getattr(snapshot, 'quota_5h_text', '--')} "
                    f"7d={getattr(snapshot, 'quota_7d_text', '--')}"
                )

        available_chatgpt_slots = max(
            0,
            self.get_chatgpt_seat_limit() - (current_chatgpt_count - len(demote_users)),
        )
        self.write_log(
            "[AUTO][PLAN] "
            f"demote={len(demote_users)} promote_candidates=0 "
            f"available_slots={available_chatgpt_slots}"
        )
        refreshed_usage_result: Sub2APIUsageLoadResult | None = None

        if not demote_users:
            return {
                "changed": False,
                "users": [],
                "demoted_count": 0,
                "promoted_count": 0,
                "demote_remote_ids": [],
                "promote_remote_ids": [],
                "refreshed_candidates": 0,
                "skipped_promotions": 0,
            }

        client = self.build_client()
        remote_lookup_for_actions = dict(
            refreshed_usage_result.lookup
            if refreshed_usage_result is not None
            else self.remote_usage_lookup
        )
        remote_summaries_for_actions = list(
            refreshed_usage_result.summaries
            if refreshed_usage_result is not None
            else self.remote_account_summaries
        )

        demote_remote_ids = self.collect_remote_account_ids_for_users(
            demote_users,
            expected_status="active",
            lookup=remote_lookup_for_actions,
        )
        demoted_count = 0
        promoted_count = 0
        probe_remote_refresh_count = 0
        for user in demote_users:
            self.write_log(
                f"[AUTO][DEMOTE][APPLY] {normalize_email(user.get('email'))} -> Codex"
            )
            core.ensure_user_seat(
                client,
                user_id=str(user.get("id", "")),
                email=None,
                target_seat_type=SEAT_ACTIONS["Codex"],
            )
            demoted_count += 1

        if demote_remote_ids:
            self.refresh_remote_tokens_after_seat_change(
                demote_remote_ids,
                log_prefix="[AUTO][DEMOTE]",
                keep_local_cache_message=(
                    "降为 Codex 后只 refresh token，不回写远程假额度；"
                    "本地可信额度与刷新时间继续保留"
                ),
            )
            self.write_log(
                f"[AUTO][DEMOTE][DISABLE] remote_ids={demote_remote_ids}"
            )
            disable_result = set_remote_accounts_inactive(demote_remote_ids)
            self.log_remote_batch_result(
                "[AUTO][DEMOTE]",
                "[DISABLE]",
                disable_result,
                fallback_ids=demote_remote_ids,
            )
            demote_remote_ids = self.extract_remote_success_ids(
                disable_result,
                fallback_ids=demote_remote_ids,
            )
            self.write_log(
                "[AUTO][DEMOTE][SKIP_REMOTE_QUOTA_SYNC] "
                "降为 Codex 后跳过远程额度 refresh，避免把 Sub2API 的假 100% 写回本地"
            )
            remote_lookup_for_actions = self.build_usage_lookup_with_status(
                remote_lookup_for_actions,
                demote_remote_ids,
                "inactive",
            )
            remote_summaries_for_actions = self.build_remote_account_summaries_with_status(
                remote_summaries_for_actions,
                demote_remote_ids,
                "inactive",
            )
            self.remote_usage_lookup = dict(remote_lookup_for_actions)
            self.remote_account_summaries = list(remote_summaries_for_actions)
            self.trusted_usage_lookup = self.merge_trusted_usage_lookup(
                self.remote_usage_lookup,
                self.remote_account_summaries,
            )
            write_usage_cache(USAGE_CACHE_PATH, self.trusted_usage_lookup)
            self.write_log(
                "[AUTO][DEMOTE][KEEP_LOCAL_CACHE] "
                "已保留本地可信额度与刷新时间，仅同步远程调用状态为 inactive"
            )

        refreshed_users = list_all_users(client, query="")
        return {
            "changed": True,
            "users": refreshed_users,
            "demoted_count": demoted_count,
            "promoted_count": promoted_count,
            "demote_remote_ids": demote_remote_ids,
            "promote_remote_ids": [],
            "refreshed_candidates": probe_remote_refresh_count,
            "skipped_promotions": 0,
            "latest_usage_result": refreshed_usage_result,
        }

    def collect_remote_account_ids_for_users(
        self,
        users: list[dict[str, Any]],
        *,
        expected_status: str | None = None,
        lookup: dict[str, Sub2APIUsageSnapshot] | None = None,
    ) -> list[int]:
        """按成员列表收集对应远程账号 ID。"""

        account_ids: list[int] = []
        seen_ids: set[int] = set()
        normalized_expected_status = str(expected_status or "").strip().lower()
        target_lookup = self.remote_usage_lookup if lookup is None else lookup
        for user in users:
            snapshot = target_lookup.get(normalize_email(user.get("email")))
            if snapshot is None or snapshot.account_id <= 0 or snapshot.account_id in seen_ids:
                continue
            if normalized_expected_status and snapshot.account_status != normalized_expected_status:
                continue
            seen_ids.add(snapshot.account_id)
            account_ids.append(snapshot.account_id)
        return account_ids

    def finish_auto_seat_policy(
        self,
        *,
        result: dict[str, Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        """收尾自动席位策略执行结果。"""

        self.auto_seat_policy_running = False
        self.busy = False
        if error is not None:
            self.status_var.set(f"自动席位策略执行失败：{error}")
            self.write_log(f"[AUTO][ERROR] {error}")
            self.update_button_states()
            self.schedule_auto_refresh()
            return

        if result is None:
            self.status_var.set("自动席位策略未执行")
            self.update_button_states()
            self.schedule_auto_refresh()
            return

        if not bool(result.get("changed", True)):
            self.write_log(
                "[AUTO][DONE] 无需切席位 "
                f"refreshed={int(result.get('refreshed_candidates', 0) or 0)} "
                f"skipped={int(result.get('skipped_promotions', 0) or 0)}"
            )
            self.status_var.set(
                "自动额度策略完成：无需切席位"
                f" | 已刷新候选 {int(result.get('refreshed_candidates', 0) or 0)}"
                f" | 跳过补位 {int(result.get('skipped_promotions', 0) or 0)}"
            )
            self.update_button_states()
            return

        latest_usage_result = result.get("latest_usage_result")
        if isinstance(latest_usage_result, Sub2APIUsageLoadResult):
            self.store_usage_load_result_locally(latest_usage_result)
        demote_remote_ids = result.get("demote_remote_ids") or []
        promote_remote_ids = result.get("promote_remote_ids") or []
        if demote_remote_ids:
            self.mark_remote_accounts_inactive_locally(demote_remote_ids)
        if promote_remote_ids:
            self.mark_remote_accounts_status_locally(promote_remote_ids, "active")
        self.apply_loaded_users(result.get("users") or [])
        self.refresh_remote_account_table_rows()
        self.status_var.set(
            "自动额度策略完成："
            f"转 Codex {int(result.get('demoted_count', 0) or 0)}"
            f" | 转 ChatGPT {int(result.get('promoted_count', 0) or 0)}"
            f" | 已刷新候选 {int(result.get('refreshed_candidates', 0) or 0)}"
            f" | 跳过补位 {int(result.get('skipped_promotions', 0) or 0)}"
        )
        self.write_log(
            "[AUTO][DONE] "
            f"demoted={int(result.get('demoted_count', 0) or 0)} "
            f"promoted={int(result.get('promoted_count', 0) or 0)} "
            f"refreshed={int(result.get('refreshed_candidates', 0) or 0)} "
            f"skipped={int(result.get('skipped_promotions', 0) or 0)}"
        )
        self.update_button_states()

    def is_mother_user(self, user: dict[str, Any] | None) -> bool:
        """判断当前成员是否母号。"""

        if not isinstance(user, dict):
            return False
        if not MOTHER_ACCOUNT_EMAIL:
            return False
        user_email = normalize_email(user.get("email"))
        if not user_email:
            return False
        return user_email == MOTHER_ACCOUNT_EMAIL

    def get_mother_account_user(
        self,
        users: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        """在成员列表里查找母号。"""

        target_users = self.current_users if users is None else users
        for user in target_users:
            if self.is_mother_user(user):
                return user
        return None

    def refresh_member_table_rows(self) -> None:
        """按当前成员和额度缓存重绘表格。"""

        for item_id in self.tree.get_children():
            self.tree.delete(item_id)

        for user in self.current_users:
            self.tree.insert(
                "",
                tk.END,
                iid=str(user.get("id", "")),
                values=self.build_user_table_values(user),
                tags=(MOTHER_ACCOUNT_TREE_TAG,) if self.is_mother_user(user) else (),
            )

    def update_remote_usage_summary(self, result: Sub2APIUsageLoadResult | None = None) -> None:
        """刷新顶部 Sub2API 额度摘要。"""

        if not self.current_users:
            self.remote_usage_summary_var.set("Sub2API额度：请先加载成员")
            return
        if not self.remote_usage_loaded or result is None:
            self.remote_usage_summary_var.set("Sub2API额度：未刷新")
            return
        matched_count = sum(
            1
            for user in self.current_users
            if self.get_user_live_remote_usage_snapshot(user) is not None
        )
        latest_updated_at = max(
            (
                snapshot.usage_updated_at
                for snapshot in result.lookup.values()
                if snapshot.usage_updated_at
            ),
            default="-",
        )
        self.remote_usage_summary_var.set(
            "Sub2API额度："
            f"已匹配 {matched_count}/{len(self.current_users)}"
            f" | 远程 {result.remote_total}"
            f" | 更新 {latest_updated_at}"
        )

    def load_remote_usage_cache(self) -> None:
        """启动时恢复本地额度缓存。"""

        cached_lookup = read_usage_cache(USAGE_CACHE_PATH)
        if not cached_lookup:
            return
        self.trusted_usage_lookup = dict(cached_lookup)
        self.remote_usage_lookup = dict(cached_lookup)
        self.remote_usage_loaded = True
        self.remote_usage_summary_var.set(
            f"Sub2API额度：已加载本地缓存 {len(self.trusted_usage_lookup)}"
        )

    def restore_member_list_cache(self) -> None:
        """启动时恢复本地成员列表缓存。"""

        cached_users = read_member_list_cache(MEMBER_LIST_CACHE_PATH)
        if not cached_users:
            return
        self.current_users = list(cached_users)
        self.refresh_member_table_rows()
        self.update_member_stats()
        self.status_var.set(f"已加载成员缓存 {len(self.current_users)} 个")
        self.maybe_prompt_mother_account_codex()

    def start_sync_remote_call_policy_actions(
        self,
        *,
        disable_ids: list[int] | tuple[int, ...] = (),
        enable_ids: list[int] | tuple[int, ...] = (),
        success_message: str,
        error_title: str,
        announce_error: bool = False,
    ) -> bool:
        """异步同步远程账号调用状态，统一处理启用和停用。"""

        normalized_disable_ids = sorted(
            {
                int(account_id)
                for account_id in (disable_ids or [])
                if str(account_id or "").strip().isdigit() and int(account_id) > 0
            }
        )
        normalized_enable_ids = sorted(
            {
                int(account_id)
                for account_id in (enable_ids or [])
                if str(account_id or "").strip().isdigit() and int(account_id) > 0
            }
        )
        if getattr(self, "remote_policy_sync_running", False):
            return False
        if not normalized_disable_ids and not normalized_enable_ids:
            return False
        self.remote_policy_sync_running = True

        def run() -> None:
            try:
                result: dict[str, Any] = {}
                if normalized_disable_ids:
                    result["disabled"] = set_remote_accounts_inactive(normalized_disable_ids)
                if normalized_enable_ids:
                    result["enabled"] = set_remote_accounts_status(normalized_enable_ids, "active")
            except Exception as exc:  # noqa: BLE001
                self.root.after(
                    0,
                    lambda captured_error=exc: self.finish_sync_remote_call_policy_actions(
                        disable_ids=normalized_disable_ids,
                        enable_ids=normalized_enable_ids,
                        success_message=success_message,
                        error_title=error_title,
                        error=captured_error,
                        announce_error=announce_error,
                    ),
                )
                return
            self.root.after(
                0,
                lambda captured_result=result: self.finish_sync_remote_call_policy_actions(
                    disable_ids=normalized_disable_ids,
                    enable_ids=normalized_enable_ids,
                    success_message=success_message,
                    error_title=error_title,
                    result=captured_result,
                    announce_error=announce_error,
                ),
            )

        threading.Thread(target=run, daemon=True).start()
        return True

    def finish_sync_remote_call_policy_actions(
        self,
        disable_ids: list[int],
        *,
        enable_ids: list[int],
        success_message: str,
        error_title: str,
        result: dict[str, Any] | None = None,
        error: Exception | None = None,
        announce_error: bool,
    ) -> None:
        """收尾远程账号调用状态自动同步动作。"""

        self.remote_policy_sync_running = False
        if error is not None:
            self.status_var.set(f"{success_message}失败：{error}")
            if announce_error:
                self.show_error_dialog(error_title, str(error))
            return
        disabled_result = result.get("disabled") if isinstance(result, dict) else None
        enabled_result = result.get("enabled") if isinstance(result, dict) else None
        disabled_success_ids = (
            disabled_result.get("success_ids") if isinstance(disabled_result, dict) else []
        )
        enabled_success_ids = (
            enabled_result.get("success_ids") if isinstance(enabled_result, dict) else []
        )
        disabled_success_ids = [
            int(account_id) for account_id in (disabled_success_ids or disable_ids)
        ]
        enabled_success_ids = [
            int(account_id) for account_id in (enabled_success_ids or enable_ids)
        ]
        if disabled_success_ids:
            self.mark_remote_accounts_inactive_locally(disabled_success_ids)
            self.update_remote_account_summary_status_locally(disabled_success_ids, "inactive")
        if enabled_success_ids:
            self.mark_remote_accounts_status_locally(enabled_success_ids, "active")
            self.update_remote_account_summary_status_locally(enabled_success_ids, "active")
        write_usage_cache(
            USAGE_CACHE_PATH,
            getattr(self, "trusted_usage_lookup", {}),
        )
        self.refresh_remote_account_table_rows()
        self.refresh_member_table_rows()
        self.status_var.set(success_message)
        if getattr(self, "remote_policy_sync_pending", False):
            pending_lookup = dict(
                getattr(self, "pending_remote_policy_lookup", {})
                or getattr(self, "remote_usage_lookup", {})
            )
            self.remote_policy_sync_pending = False
            self.pending_remote_policy_lookup = {}
            self.sync_codex_remote_call_policy(pending_lookup)

    def sync_codex_remote_call_policy(self, live_lookup: dict[str, Sub2APIUsageSnapshot]) -> None:
        """按当前成员席位和额度自动同步远程调用状态。"""

        if getattr(self, "remote_policy_sync_running", False):
            self.remote_policy_sync_pending = True
            self.pending_remote_policy_lookup = dict(live_lookup or {})
            self.write_log("[AUTO][REMOTE][QUEUE] 远程调度同步进行中，已登记一次重跑")
            return
        disable_ids = self.get_codex_remote_account_ids_to_disable(live_lookup)
        enable_ids = self.get_chatgpt_remote_account_ids_to_enable(live_lookup)
        if not disable_ids and not enable_ids:
            return
        messages = []
        if disable_ids:
            messages.append(f"关闭 {len(disable_ids)} 个 Codex 账号")
        if enable_ids:
            messages.append(f"开启 {len(enable_ids)} 个 ChatGPT 账号")
        self.start_sync_remote_call_policy_actions(
            disable_ids=disable_ids,
            enable_ids=enable_ids,
            success_message="已自动同步 Sub2API 调用：" + "，".join(messages),
            error_title="同步远程调用状态失败",
            announce_error=False,
        )

    def handle_created_remote_oauth_account(self, creation_result: dict[str, Any]) -> dict[str, Any]:
        """处理 OAuth 建号成功后的 Codex 停用规则。"""

        email_address = normalize_email(creation_result.get("account_email"))
        created_account_id = int(creation_result.get("account_id") or 0)
        created_account_name = str(creation_result.get("account_name") or "").strip()
        matched_user = self.get_user_by_email(email_address, include_cached=True)
        response = {
            "matched_member": bool(matched_user),
            "disabled": False,
            "email": email_address,
            "seat_type": str(matched_user.get("seat_type") or "").strip() if matched_user else "",
        }
        if created_account_id <= 0:
            response["error"] = "新建账号未返回有效 account_id，无法自动停用"
            return response
        disable_result = set_remote_accounts_inactive([created_account_id])
        if matched_user:
            self.seed_created_remote_oauth_account_locally(
                email_address=email_address,
                account_id=created_account_id,
                account_name=created_account_name,
            )
        self.mark_remote_accounts_inactive_locally([created_account_id])
        response["disabled"] = True
        response["disable_result"] = disable_result
        return response

    def parse_acc_text(self) -> None:
        """解析当前输入的 ACC 原文并缓存。"""
        self.write_current_import_text_cache()
        self.mother_account_prompted = False
        self.import_payload_text(self.get_import_text(), show_error=True)

    def import_payload_text(
        self,
        raw_text: str,
        *,
        show_error: bool,
        from_clipboard: bool = False,
    ) -> bool:
        """统一处理 ACC 文本导入。"""

        try:
            payload = parse_import_payload(raw_text)
        except core.SeatApiError as exc:
            if show_error:
                self.show_error_dialog("ACC 解析失败", str(exc))
            return False

        if from_clipboard:
            self.set_import_text(raw_text)
        self.write_current_import_text_cache()
        write_import_cache(IMPORT_CACHE_PATH, payload)
        self.refresh_import_cache_state()
        self.apply_import_payload(payload)
        return True

    def start_quick_fetch_session(self) -> None:
        """打开 ChatGPT session 页面。"""

        try:
            webbrowser.open(CHATGPT_SESSION_URL)
        except Exception as exc:  # noqa: BLE001
            self.show_error_dialog("打开 session 页面失败", str(exc))
            return

        self.status_var.set("已打开 session 页面")

    def use_import_cache(self) -> None:
        """读取本地 ACC 缓存并恢复会话。"""
        self.refresh_import_cache_state()
        if not self.import_cache:
            messagebox.showwarning("提示", "还没有 ACC 缓存，请先粘贴原文并解析。")
            return
        self.apply_import_payload(self.import_cache)

    def maybe_restore_import_session_on_startup(self) -> None:
        """启动时自动恢复 ACC 缓存会话。"""

        if not self.import_cache:
            return
        self.auto_restore_session_pending = True
        self.apply_import_payload(
            self.import_cache,
            source_label="ACC 缓存已恢复",
            auto_load_members=True,
        )

    def apply_import_payload(
        self,
        payload: dict[str, str],
        *,
        source_label: str = "ACC 已解析",
        auto_load_members: bool = False,
    ) -> None:
        """把导入结果写入当前会话状态。"""
        self.credentials = default_credential_state()
        self.mother_account_prompted = False
        self.credentials["access_token"] = str(payload.get("accessToken") or "").strip()
        self.credentials["account_id"] = str(payload.get("accountId") or "").strip()
        self.credentials["device_id"] = str(payload.get("deviceId") or "").strip()
        self.credentials["session_token"] = str(payload.get("sessionToken") or "").strip()
        self.credentials["client_build_number"] = (
            str(payload.get("clientBuildNumber") or "").strip() or core.CLIENT_BUILD_NUMBER
        )
        self.credentials["client_version"] = (
            str(payload.get("clientVersion") or "").strip() or core.CLIENT_VERSION
        )
        self.update_session_summary()
        self.auto_restore_session_pending = bool(auto_load_members)

        if self.credentials["session_token"]:
            self.status_var.set(f"{source_label}，正在用 sessionToken 补齐当前会话...")
            self.resolve_session_from_token(self.credentials["session_token"])
            return

        self.save_config_silently()
        self.status_var.set(f"{source_label}并写入本地缓存")
        if auto_load_members:
            self.maybe_start_auto_member_refresh()

    def resolve_session_from_token(self, session_token: str) -> None:
        """通过 sessionToken 拉取当前会话。"""
        if self.busy:
            return

        self.busy = True
        self.status_var.set("正在刷新当前会话...")
        self.update_button_states()

        def run() -> None:
            try:
                session_data = core.fetch_session_info(
                    self.credentials["base_url"],
                    session_token,
                )
                result = core.extract_session_credentials(session_data)
            except Exception as exc:  # noqa: BLE001
                if is_forbidden_session_refresh_error(exc):
                    self.root.after(
                        0,
                        lambda captured_error=exc: self.handle_ignored_session_refresh_error(
                            captured_error
                        ),
                    )
                    return
                self.root.after(
                    0,
                    lambda captured_error=exc: self.finish_task(error=captured_error),
                )
                return
            self.root.after(
                0,
                lambda captured_result=result: self.finish_task(
                    result=captured_result,
                    on_success=self.apply_resolved_session,
                ),
            )

        threading.Thread(target=run, daemon=True).start()

    def handle_ignored_session_refresh_error(self, error: Exception) -> None:
        """静默跳过 403 会话刷新错误，并保留已解析结果。"""

        self.busy = False
        self.save_config_silently()
        self.status_var.set(f"ACC 已解析，已跳过会话刷新异常：{error}")
        self.update_button_states()
        if getattr(self, "auto_restore_session_pending", False):
            self.maybe_start_auto_member_refresh()

    def apply_resolved_session(self, result: tuple[str, str]) -> None:
        """应用通过 sessionToken 刷新的 access token 和 account_id。"""
        access_token, account_id = result
        self.credentials["access_token"] = access_token
        self.credentials["account_id"] = account_id
        self.update_session_summary()
        self.save_config_silently()
        self.status_var.set("ACC 已解析，并自动补齐当前会话")
        if getattr(self, "auto_restore_session_pending", False):
            self.maybe_start_auto_member_refresh()

    def maybe_start_auto_member_refresh(self) -> None:
        """在启动恢复 ACC 会话后自动拉取成员列表。"""

        self.auto_restore_session_pending = False
        if self.busy:
            return
        self.load_members(query_override="", source_label="正在自动恢复成员列表...")

    def save_config_silently(self) -> None:
        """静默保存当前会话到本目录 .env。"""
        values = build_env_values(
            access_token=self.credentials["access_token"],
            account_id=self.credentials["account_id"],
            device_id=self.credentials["device_id"],
            session_token=self.credentials["session_token"],
            client_build_number=self.credentials["client_build_number"],
            client_version=self.credentials["client_version"],
            base_url=self.credentials["base_url"],
        )
        write_env_file(ENV_FILE_PATH, values)

    def build_client(self) -> core.SeatClient:
        """根据当前会话状态创建请求客户端。"""
        config = core.Config(
            access_token=self.credentials["access_token"].strip(),
            account_id=self.credentials["account_id"].strip(),
            device_id=self.credentials["device_id"].strip(),
            session_token=self.credentials["session_token"].strip(),
            client_build_number=self.credentials["client_build_number"].strip() or core.CLIENT_BUILD_NUMBER,
            client_version=self.credentials["client_version"].strip() or core.CLIENT_VERSION,
            base_url=core.normalize_base_url(self.credentials["base_url"].strip() or core.DEFAULT_BASE_URL),
        )
        if not config.access_token and not config.session_token:
            raise core.SeatApiError("缺少 access token 或 session token。")
        if not config.account_id:
            raise core.SeatApiError("缺少 account_id。请重新导入 ACC 原文。")
        return core.SeatClient(config)

    def start_background_task(
        self,
        busy_text: str,
        worker: Callable[[], Any],
        on_success: Callable[[Any], None],
    ) -> None:
        """把网络任务放到后台线程执行。"""
        if self.busy:
            return

        self.busy = True
        self.status_var.set(busy_text)
        self.update_button_states()

        def run() -> None:
            try:
                result = worker()
            except Exception as exc:  # noqa: BLE001
                self.root.after(0, lambda captured_error=exc: self.finish_task(error=captured_error))
                return
            self.root.after(
                0,
                lambda captured_result=result: self.finish_task(
                    result=captured_result,
                    on_success=on_success,
                ),
            )

        threading.Thread(target=run, daemon=True).start()

    def finish_task(
        self,
        result: Any = None,
        on_success: Callable[[Any], None] | None = None,
        error: Exception | None = None,
    ) -> None:
        """在主线程里收尾后台任务。"""
        self.busy = False
        if error is not None:
            self.status_var.set(f"操作失败：{error}")
            self.update_button_states()
            self.show_error_dialog("操作失败", str(error))
            return

        if on_success is not None:
            on_success(result)
        self.update_button_states()

    def load_members(
        self,
        *,
        query_override: str | None = None,
        source_label: str | None = None,
    ) -> None:
        """加载当前账号下的全部成员。"""

        def worker() -> list[dict[str, Any]]:
            client = self.build_client()
            target_query = self.query_var.get() if query_override is None else query_override
            return list_all_users(client, query=target_query)

        query_text = (self.query_var.get() if query_override is None else query_override).strip()
        status_text = source_label or (
            "正在加载全部成员..." if not query_text else f"正在搜索成员：{query_text}"
        )
        self.start_background_task(
            busy_text=status_text,
            worker=worker,
            on_success=self.apply_loaded_users,
        )

    def apply_loaded_users(self, users: list[dict[str, Any]]) -> None:
        """把成员列表刷新到表格。"""
        self.current_users = list(users)
        write_member_list_cache(MEMBER_LIST_CACHE_PATH, self.current_users)
        self.refresh_member_table_rows()
        self.update_member_stats()
        self.status_var.set(f"已加载 {len(self.current_users)} 个成员")
        self.maybe_prompt_mother_account_codex()
        self.refresh_remote_usage(announce_error=False)

    def maybe_prompt_mother_account_codex(self) -> None:
        """首次加载到母号且仍是 ChatGPT 时，提醒改为 Codex。"""

        if getattr(self, "mother_account_prompted", False):
            return
        mother_user = self.get_mother_account_user()
        if mother_user is None:
            return
        self.mother_account_prompted = True
        if not self.is_chatgpt_seat_type(mother_user.get("seat_type")):
            return
        self.show_mother_account_seat_dialog(mother_user)

    def show_mother_account_seat_dialog(self, mother_user: dict[str, Any]) -> None:
        """弹出母号席位提醒，并支持一键改为 Codex。"""

        dialog = tk.Toplevel(self.root.winfo_toplevel())
        dialog.title("母号席位提醒")
        dialog.transient(self.root.winfo_toplevel())
        dialog.grab_set()
        dialog.geometry("520x200")
        dialog.minsize(420, 180)

        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(0, weight=1)

        ttk.Label(
            frame,
            text="当前母号为 ChatGPT 席位，请改为 Codex 席位。",
            font=("Microsoft YaHei UI", 11, "bold"),
            foreground="#c62828",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            frame,
            text=f"母号邮箱：{str(mother_user.get('email') or '').strip()}",
            justify=tk.LEFT,
            wraplength=470,
        ).grid(row=1, column=0, sticky="w", pady=(12, 0))

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=2, column=0, sticky="e", pady=(18, 0))
        ttk.Button(
            button_frame,
            text="改为Codex席位",
            command=lambda: self.convert_mother_account_to_codex(dialog, mother_user),
        ).pack(side=tk.LEFT)
        ttk.Button(
            button_frame,
            text="暂不处理",
            command=dialog.destroy,
        ).pack(side=tk.LEFT, padx=(8, 0))

    def convert_mother_account_to_codex(
        self,
        dialog: tk.Toplevel,
        mother_user: dict[str, Any],
    ) -> None:
        """从母号提醒弹窗里直接把母号切到 Codex。"""

        if dialog.winfo_exists():
            dialog.destroy()
        self.change_user_seat(mother_user, SEAT_ACTIONS["Codex"])

    def refresh_remote_usage(
        self,
        announce_error: bool = True,
        *,
        from_auto_refresh: bool = False,
    ) -> None:
        """从 Sub2API 拉取远程额度并按邮箱回填到成员列表。"""

        if self.busy:
            return

        self.busy = True
        if from_auto_refresh:
            self.status_var.set("自动刷新 Sub2API 额度中...")
        else:
            self.status_var.set("刷新 Sub2API 额度中...")
        self.update_button_states()

        def run() -> None:
            try:
                result = load_sub2api_usage_lookup()
            except Exception as exc:  # noqa: BLE001
                self.root.after(
                    0,
                    lambda captured_error=exc: self.finish_remote_usage_refresh(
                        error=captured_error,
                        announce_error=announce_error,
                        from_auto_refresh=from_auto_refresh,
                    ),
                )
                return
            self.root.after(
                0,
                lambda captured_result=result: self.finish_remote_usage_refresh(
                    result=captured_result,
                    announce_error=announce_error,
                    from_auto_refresh=from_auto_refresh,
                ),
            )

        threading.Thread(target=run, daemon=True).start()

    def finish_remote_usage_refresh(
        self,
        result: Sub2APIUsageLoadResult | None = None,
        error: Exception | None = None,
        *,
        announce_error: bool,
        from_auto_refresh: bool,
    ) -> None:
        """在主线程里收尾远程额度刷新。"""

        self.busy = False
        if error is not None:
            self.status_var.set(f"刷新 Sub2API 额度失败：{error}")
            if not self.remote_usage_loaded:
                self.remote_usage_summary_var.set("Sub2API额度：刷新失败")
                self.refresh_member_table_rows()
            self.update_button_states()
            if announce_error:
                self.show_error_dialog("刷新 Sub2API 额度失败", str(error))
            self.schedule_auto_refresh()
            return

        self.store_usage_load_result_locally(result)
        self.refresh_member_table_rows()
        self.refresh_remote_account_table_rows()
        self.update_remote_usage_summary(result)
        matched_count = sum(
            1
            for user in self.current_users
            if self.get_user_live_remote_usage_snapshot(user) is not None
        )
        refresh_prefix = "Sub2API 额度已自动刷新" if from_auto_refresh else "Sub2API 额度已刷新"
        self.status_var.set(f"{refresh_prefix}，已匹配 {matched_count}/{len(self.current_users)}")
        self.update_button_states()
        self.sync_codex_remote_call_policy(self.remote_usage_lookup)
        self.schedule_auto_seat_policy_evaluation()
        self.schedule_auto_refresh()

    def get_selected_user(self) -> dict[str, Any]:
        """读取当前选中的成员对象。"""
        selection = self.tree.selection()
        if not selection:
            raise core.SeatApiError("请先选中一个成员。")
        selected_id = selection[0]
        for user in self.current_users:
            if str(user.get("id", "")) == selected_id:
                return user
        raise core.SeatApiError("当前选中成员已失效，请重新加载成员列表。")

    def update_seat_action_buttons(self) -> None:
        """根据当前选中成员动态调整席位按钮文案。"""

        if not bool(self.tree.selection()):
            self.toggle_button.configure(text="切换席位")
            self.set_default_button.configure(text="禁改 ChatGPT")
            self.set_usage_based_button.configure(text="设为 Codex")
            return
        try:
            user = self.get_selected_user()
        except core.SeatApiError:
            self.toggle_button.configure(text="切换席位")
            self.set_default_button.configure(text="禁改 ChatGPT")
            self.set_usage_based_button.configure(text="设为 Codex")
            return
        if not self.is_mother_user(user):
            self.toggle_button.configure(text="切换席位")
            self.set_default_button.configure(text="禁改 ChatGPT")
            self.set_usage_based_button.configure(text="设为 Codex")
            return
        if self.is_chatgpt_seat_type(user.get("seat_type")):
            self.toggle_button.configure(text="改为 Codex")
        else:
            self.toggle_button.configure(text="母号保持 Codex")
        self.set_default_button.configure(text="母号禁改 ChatGPT")
        self.set_usage_based_button.configure(text="设为 Codex")

    def copy_selected_email(self) -> None:
        """复制当前选中成员邮箱。"""
        user = self.get_selected_user()
        email_address = str(user.get("email") or "").strip()
        if not email_address:
            raise core.SeatApiError("当前成员没有邮箱地址。")
        copy_text_to_clipboard(self.root, email_address)
        self.status_var.set(f"已复制邮箱：{email_address}")

    def toggle_selected_user(self) -> None:
        """按当前状态切换选中成员席位。"""
        user = self.get_selected_user()
        target_seat = core.next_seat_type(user.get("seat_type"))
        self.change_user_seat(user, target_seat)

    def set_selected_user_seat(self, seat_type: str) -> None:
        """把选中成员设置为指定席位。"""
        user = self.get_selected_user()
        self.change_user_seat(user, seat_type)

    def ensure_mother_account_chatgpt_blocked(
        self,
        user: dict[str, Any],
        target_seat_type: str,
    ) -> None:
        """禁止把母号改成 ChatGPT。"""

        if not self.is_mother_user(user):
            return
        if target_seat_type == SEAT_ACTIONS["ChatGPT"]:
            raise core.SeatApiError("母号已受保护，不能在本软件里改为 ChatGPT 席位。")

    def ensure_chatgpt_seat_available(
        self,
        user: dict[str, Any],
        target_seat_type: str,
        *,
        users: list[dict[str, Any]] | None = None,
    ) -> None:
        """在转成 ChatGPT 前检查当前席位上限。"""

        if target_seat_type != SEAT_ACTIONS["ChatGPT"]:
            return
        if self.is_chatgpt_seat_type(user.get("seat_type")):
            return
        limit = self.get_chatgpt_seat_limit()
        current_chatgpt_count = self.count_chatgpt_users(users)
        if current_chatgpt_count >= limit:
            raise core.SeatApiError(
                f"当前 ChatGPT 席位已达上限 {limit}，不能再转换为 ChatGPT。"
            )

    def ensure_chatgpt_seat_available_runtime(
        self,
        client: core.SeatClient,
        user: dict[str, Any],
        target_seat_type: str,
        *,
        log_prefix: str,
        raise_on_limit: bool = True,
    ) -> bool:
        """在真正切到 ChatGPT 前，按远端实时成员列表再做一次上限校验。"""

        if target_seat_type != SEAT_ACTIONS["ChatGPT"]:
            return True
        if self.is_chatgpt_seat_type(user.get("seat_type")):
            return True
        live_users = list_all_users(client, query="")
        current_chatgpt_count = self.count_chatgpt_users(live_users)
        limit = self.get_chatgpt_seat_limit()
        self.write_log(
            f"{log_prefix} 当前 ChatGPT={current_chatgpt_count}/{limit}"
        )
        if current_chatgpt_count >= limit:
            if raise_on_limit:
                raise core.SeatApiError(
                    f"当前 ChatGPT 席位已达上限 {limit}，不能再转换为 ChatGPT。"
                )
            return False
        return True

    def change_user_seat(self, user: dict[str, Any], seat_type: str) -> None:
        """执行席位切换并在完成后刷新成员列表。"""
        self.ensure_mother_account_chatgpt_blocked(user, seat_type)
        self.ensure_chatgpt_seat_available(user, seat_type)
        identifier = str(user.get("email") or user.get("id") or "")

        def progress_callback(attempt: int, callback_identifier: str, target_seat_type: str) -> None:
            self.root.after(
                0,
                lambda: self.update_attempt_status(
                    callback_identifier,
                    target_seat_type,
                    attempt,
                ),
            )

        def worker() -> dict[str, Any]:
            client = self.build_client()
            self.ensure_chatgpt_seat_available_runtime(
                client,
                user,
                seat_type,
                log_prefix=f"[MANUAL][CHECK] {identifier}",
            )
            ensure_result = core.ensure_user_seat(
                client,
                user_id=str(user.get("id", "")),
                email=None,
                target_seat_type=seat_type,
                progress_callback=progress_callback,
            )
            remote_postprocess = self.postprocess_manual_seat_change_remote_state(
                user,
                ensure_result,
                seat_type,
            )
            query_text = self.query_var.get() if hasattr(self, "query_var") else ""
            users = list_all_users(client, query=query_text)
            return {
                "ensure_result": ensure_result,
                "users": users,
                "refreshed_remote_ids": remote_postprocess.get("refreshed_remote_ids") or [],
                "enabled_remote_ids": remote_postprocess.get("enabled_remote_ids") or [],
                "disabled_remote_ids": remote_postprocess.get("disabled_remote_ids") or [],
                "latest_usage_result": remote_postprocess.get("latest_usage_result"),
            }

        self.start_background_task(
            busy_text=f"正在更新 {identifier} 的席位...",
            worker=worker,
            on_success=self.apply_seat_change_result,
        )

    def update_attempt_status(self, identifier: str, target_seat_type: str, attempt: int) -> None:
        """实时展示当前席位切换尝试次数。"""
        self.status_var.set(
            f"正在把 {identifier} 设为 {core.seat_label(target_seat_type)}，"
            f"第 {attempt} 次尝试..."
        )

    def apply_seat_change_result(self, result: Any) -> None:
        """处理席位切换后的结果并刷新表格。"""
        if isinstance(result, tuple):
            ensure_result, users = result
            refreshed_remote_ids: list[int] = []
        else:
            ensure_result = dict(result.get("ensure_result") or {})
            users = list(result.get("users") or [])
            refreshed_remote_ids = self.normalize_remote_account_ids(
                result.get("refreshed_remote_ids") or []
            )
            enabled_remote_ids = self.normalize_remote_account_ids(
                result.get("enabled_remote_ids") or []
            )
            disabled_remote_ids = self.normalize_remote_account_ids(
                result.get("disabled_remote_ids") or []
            )
            latest_usage_result = result.get("latest_usage_result")
        if isinstance(result, tuple):
            enabled_remote_ids = []
            disabled_remote_ids = []
            latest_usage_result = None
        if latest_usage_result is not None:
            self.store_usage_load_result_locally(latest_usage_result)
        if disabled_remote_ids:
            self.mark_remote_accounts_inactive_locally(disabled_remote_ids)
            self.update_remote_account_summary_status_locally(disabled_remote_ids, "inactive")
        if enabled_remote_ids:
            self.mark_remote_accounts_status_locally(enabled_remote_ids, "active")
            self.update_remote_account_summary_status_locally(enabled_remote_ids, "active")
        self.apply_loaded_users(users)
        identifier = ensure_result["identifier"]
        target_seat_type = ensure_result["targetSeatType"]
        if ensure_result["changed"]:
            status_text = (
                f"{identifier} 已设置为 {core.seat_label(target_seat_type)}，"
                f"共尝试 {ensure_result['attempts']} 次"
            )
            if refreshed_remote_ids:
                status_text += f" | 已刷新 {len(refreshed_remote_ids)} 个远程令牌"
            if enabled_remote_ids:
                status_text += f" | 已开启 {len(enabled_remote_ids)} 个远程调用"
            elif disabled_remote_ids:
                status_text += f" | 已关闭 {len(disabled_remote_ids)} 个远程调用"
            self.status_var.set(status_text)
            return
        self.status_var.set(f"{identifier} 已是 {core.seat_label(target_seat_type)}")

    def update_button_states(self) -> None:
        """根据当前状态启停按钮。"""
        has_selection = bool(self.tree.selection())
        has_remote_selection = bool(
            getattr(self, "remote_account_tree", None)
            and self.remote_account_tree.selection()
        )
        can_modify = has_selection and not self.busy
        can_modify_remote = has_remote_selection and not self.busy
        normal_or_disabled = tk.DISABLED if self.busy else tk.NORMAL
        selected_user: dict[str, Any] | None = None
        if has_selection:
            try:
                selected_user = self.get_selected_user()
            except core.SeatApiError:
                selected_user = None
        mother_selected = self.is_mother_user(selected_user)
        selected_is_codex = bool(
            selected_user and self.is_codex_seat_type(selected_user.get("seat_type"))
        )
        mother_is_codex = mother_selected and not self.is_chatgpt_seat_type(
            selected_user.get("seat_type") if selected_user else None
        )

        self.parse_button.configure(state=normal_or_disabled)
        self.quick_fetch_button.configure(state=normal_or_disabled)
        self.cache_button.configure(state=normal_or_disabled)
        self.clear_button.configure(state=normal_or_disabled)
        self.load_button.configure(state=normal_or_disabled)
        self.refresh_remote_usage_button.configure(state=normal_or_disabled)
        self.refresh_remote_accounts_button.configure(state=normal_or_disabled)
        self.auto_refresh_combo.configure(state="readonly")
        self.copy_email_button.configure(state=tk.NORMAL if can_modify else tk.DISABLED)
        self.enable_remote_account_button.configure(
            state=tk.NORMAL if can_modify_remote else tk.DISABLED
        )
        self.disable_remote_account_button.configure(
            state=tk.NORMAL if can_modify_remote else tk.DISABLED
        )
        self.toggle_button.configure(
            state=(
                tk.DISABLED
                if (not can_modify or mother_is_codex or selected_is_codex)
                else tk.NORMAL
            )
        )
        self.set_default_button.configure(state=tk.DISABLED)
        self.set_usage_based_button.configure(state=tk.NORMAL if can_modify else tk.DISABLED)
        self.update_seat_action_buttons()


class StandaloneAccSeatManagerWindow:
    """挂在 Sub2API 独立工具里的 ACC 席位窗口封装。"""

    def __init__(self, parent, on_close=None):
        self.parent = parent
        self.on_close = on_close
        self.window = tk.Toplevel(parent)
        self.window.title("ACC 席位工具")
        self.window.geometry(DEFAULT_WINDOW_SIZE)
        self.window.minsize(980, 620)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.app = StandaloneAccSeatConverterApp(self.window)

    def focus(self) -> None:
        """聚焦已有窗口。"""

        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def close(self) -> None:
        """关闭窗口并回收外部引用。"""

        if self.window.winfo_exists():
            self.window.destroy()
        if callable(self.on_close):
            self.on_close()


def main() -> None:
    """GUI 入口。"""
    parser = argparse.ArgumentParser(description="ACC 席位转换器")
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="创建并销毁窗口后退出，用于启动链路自检",
    )
    args = parser.parse_args()

    root = tk.Tk()
    if args.self_check:
        root.withdraw()
        StandaloneAccSeatConverterApp(root)
        root.update_idletasks()
        root.destroy()
        return

    StandaloneAccSeatConverterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
