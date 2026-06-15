"""独立工具首次启动配置向导。"""

from __future__ import annotations

import json
import os
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from sub2api_runtime import get_app_dir

ENV_FIELD_ORDER = [
    "SUB2API_BASE_URL",
    "SUB2API_ADMIN_API_KEY",
    "SUB2API_GROUP_IDS",
    "SUB2API_PROXY_ID",
    "SUB2API_IMPORT_CONCURRENCY",
    "SUB2API_IMPORT_PRIORITY",
    "SUB2API_UPDATE_EXISTING",
    "SUB2API_SKIP_DEFAULT_GROUP_BIND",
    "SUB2API_CONFIRM_MIXED_CHANNEL_RISK",
    "SUB2API_OAUTH_REDIRECT_URI",
    "SUB2API_OAUTH_PROXY_ID",
    "SUB2API_OAUTH_PROXY_URL",
    "SUB2API_OAUTH_PROXY_NAME",
    "SUB2API_OAUTH_GROUP_IDS",
    "SUB2API_OAUTH_GROUP_NAME",
    "SUB2API_OAUTH_ACCOUNT_CONCURRENCY",
    "ACC_MOTHER_ACCOUNT_EMAIL",
    "CHATGPT_RANDOM_EMAIL_DOMAIN",
]

DEFAULT_ENV_VALUES: dict[str, str] = {
    "SUB2API_BASE_URL": "",
    "SUB2API_ADMIN_API_KEY": "",
    "SUB2API_GROUP_IDS": "",
    "SUB2API_PROXY_ID": "",
    "SUB2API_IMPORT_CONCURRENCY": "50",
    "SUB2API_IMPORT_PRIORITY": "",
    "SUB2API_UPDATE_EXISTING": "true",
    "SUB2API_SKIP_DEFAULT_GROUP_BIND": "false",
    "SUB2API_CONFIRM_MIXED_CHANNEL_RISK": "false",
    "SUB2API_OAUTH_REDIRECT_URI": "http://localhost:1455/auth/callback",
    "SUB2API_OAUTH_PROXY_ID": "",
    "SUB2API_OAUTH_PROXY_URL": "",
    "SUB2API_OAUTH_PROXY_NAME": "default",
    "SUB2API_OAUTH_GROUP_IDS": "",
    "SUB2API_OAUTH_GROUP_NAME": "cc",
    "SUB2API_OAUTH_ACCOUNT_CONCURRENCY": "10",
    "ACC_MOTHER_ACCOUNT_EMAIL": "",
    "CHATGPT_RANDOM_EMAIL_DOMAIN": "example.com",
}

REQUIRED_ENV_KEYS = (
    "SUB2API_BASE_URL",
    "SUB2API_ADMIN_API_KEY",
)


def center_window(window: tk.Misc, *, preferred_width: int, preferred_height: int) -> None:
    """把窗口放到屏幕中央，避免首启窗口跑到屏幕外。"""

    window.update_idletasks()
    current_width = max(
        int(getattr(window, "winfo_width", lambda: 0)() or 0),
        int(getattr(window, "winfo_reqwidth", lambda: 0)() or 0),
        int(preferred_width),
    )
    current_height = max(
        int(getattr(window, "winfo_height", lambda: 0)() or 0),
        int(getattr(window, "winfo_reqheight", lambda: 0)() or 0),
        int(preferred_height),
    )
    screen_width = max(int(window.winfo_screenwidth() or 0), current_width)
    screen_height = max(int(window.winfo_screenheight() or 0), current_height)
    offset_x = max((screen_width - current_width) // 2, 0)
    offset_y = max((screen_height - current_height) // 2, 0)
    window.geometry(f"{current_width}x{current_height}+{offset_x}+{offset_y}")


def bring_window_to_front(window: tk.Misc) -> None:
    """尽量把窗口提到前台，避免用户误以为程序没打开。"""

    try:
        window.deiconify()
    except tk.TclError:
        return
    try:
        window.lift()
        window.focus_force()
        window.attributes("-topmost", True)
        window.after(1200, lambda: _clear_topmost(window))
    except tk.TclError:
        return


def _clear_topmost(window: tk.Misc) -> None:
    """取消临时 topmost，避免窗口一直压最前。"""

    try:
        window.attributes("-topmost", False)
    except tk.TclError:
        return


def parse_env_value(raw_value: str) -> str:
    """解析 .env 单行值。"""

    value = raw_value.strip()
    if not value:
        return ""
    if value.startswith('"') and value.endswith('"'):
        try:
            return str(json.loads(value))
        except json.JSONDecodeError:
            return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    return value


def read_env_file(path: Path) -> dict[str, str]:
    """读取简单 .env 文件。"""

    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = parse_env_value(value)
    return values


def write_env_file(path: Path, values: dict[str, str]) -> None:
    """按固定顺序写入公开版 .env。"""

    merged = dict(DEFAULT_ENV_VALUES)
    merged.update({key: str(value or "") for key, value in values.items()})

    lines = [
        "# Sub2API 独立工具首次启动生成的本地配置",
        "# 这个文件只保存在当前 exe 所在目录，不需要 Python 环境。",
        "",
        "# 远程 Sub2API 管理配置",
    ]
    for key in ENV_FIELD_ORDER[:9]:
        lines.append(f"{key}={json.dumps(merged[key], ensure_ascii=False)}")

    lines.extend(
        [
            "",
            "# OAuth 建号默认配置",
        ]
    )
    for key in ENV_FIELD_ORDER[9:16]:
        lines.append(f"{key}={json.dumps(merged[key], ensure_ascii=False)}")

    lines.extend(
        [
            "",
            "# 其他本地配置",
        ]
    )
    for key in ENV_FIELD_ORDER[16:]:
        lines.append(f"{key}={json.dumps(merged[key], ensure_ascii=False)}")

    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def get_standalone_env_path(module_file: str | Path) -> Path:
    """返回独立工具运行目录下的 .env 路径。"""

    return get_app_dir(module_file) / ".env"


def get_project_env_path(module_file: str | Path) -> Path:
    """返回项目目录下的 .env 路径。"""

    return get_app_dir(module_file) / ".env"


def load_effective_env_values(module_file: str | Path) -> tuple[dict[str, str], Path]:
    """按独立工具优先、项目目录兜底的顺序加载配置。"""

    local_env_path = get_standalone_env_path(module_file)
    project_env_path = get_project_env_path(module_file)

    local_values = read_env_file(local_env_path)
    if local_values:
        return local_values, local_env_path

    project_values = read_env_file(project_env_path)
    if project_values:
        return project_values, project_env_path

    return {}, local_env_path


def has_required_remote_config(values: dict[str, str]) -> bool:
    """判断是否已经具备远程功能所需最小配置。"""

    for key in REQUIRED_ENV_KEYS:
        if not str(values.get(key, "")).strip():
            return False
    return True


def ensure_env_file_exists(module_file: str | Path) -> Path:
    """首次启动时自动生成 .env 模板文件。"""

    values, env_path = load_effective_env_values(module_file)
    if env_path.exists():
        return env_path
    seed_values = dict(DEFAULT_ENV_VALUES)
    seed_values.update(values)
    write_env_file(env_path, seed_values)
    return env_path


def apply_env_values_to_process(values: dict[str, str]) -> None:
    """把已保存配置同步到当前进程环境变量。"""

    for key, value in (values or {}).items():
        os.environ[key] = str(value or "")


class FirstRunSetupDialog:
    """首次启动配置向导。"""

    def __init__(self, root: tk.Tk, env_path: Path, initial_values: dict[str, str]) -> None:
        self.root = root
        self.env_path = env_path
        self.result: dict[str, str] | None = None
        merged_values = dict(DEFAULT_ENV_VALUES)
        merged_values.update(initial_values or {})

        self.window = tk.Toplevel(root)
        self.window.title("首次启动配置")
        self.window.geometry("760x520")
        self.window.minsize(680, 460)
        self.window.transient(root)
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self.handle_skip)
        center_window(self.window, preferred_width=760, preferred_height=520)
        bring_window_to_front(self.window)

        container = ttk.Frame(self.window, padding=14)
        container.pack(fill="both", expand=True)
        container.columnconfigure(1, weight=1)

        ttk.Label(
            container,
            text="首次启动已自动生成 .env，本页填一次后以后直接打开就能用。",
            font=("Microsoft YaHei UI", 11, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w")

        ttk.Label(
            container,
            text="至少填好服务器地址和管理员 API Key；其余默认值已经预填。",
            justify="left",
            wraplength=700,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 12))

        self.base_url_var = tk.StringVar(value=merged_values["SUB2API_BASE_URL"])
        self.admin_api_key_var = tk.StringVar(value=merged_values["SUB2API_ADMIN_API_KEY"])
        self.group_name_var = tk.StringVar(value=merged_values["SUB2API_OAUTH_GROUP_NAME"])
        self.group_ids_var = tk.StringVar(value=merged_values["SUB2API_GROUP_IDS"])
        self.import_concurrency_var = tk.StringVar(
            value=merged_values["SUB2API_IMPORT_CONCURRENCY"]
        )
        self.oauth_concurrency_var = tk.StringVar(
            value=merged_values["SUB2API_OAUTH_ACCOUNT_CONCURRENCY"]
        )
        self.redirect_uri_var = tk.StringVar(
            value=merged_values["SUB2API_OAUTH_REDIRECT_URI"]
        )
        self.random_domain_var = tk.StringVar(
            value=merged_values["CHATGPT_RANDOM_EMAIL_DOMAIN"]
        )
        self.mother_email_var = tk.StringVar(
            value=merged_values["ACC_MOTHER_ACCOUNT_EMAIL"]
        )
        self.proxy_name_var = tk.StringVar(value=merged_values["SUB2API_OAUTH_PROXY_NAME"])

        self._create_entry(container, 2, "服务器地址", self.base_url_var)
        self._create_entry(container, 3, "管理员 API Key", self.admin_api_key_var, show="*")
        self._create_entry(container, 4, "默认分组名", self.group_name_var)
        self._create_entry(container, 5, "默认分组 ID", self.group_ids_var)
        self._create_entry(container, 6, "转换并发", self.import_concurrency_var)
        self._create_entry(container, 7, "建号并发", self.oauth_concurrency_var)
        self._create_entry(container, 8, "OAuth 回调地址", self.redirect_uri_var)
        self._create_entry(container, 9, "随机邮箱域名", self.random_domain_var)
        self._create_entry(container, 10, "母号邮箱", self.mother_email_var)
        self._create_entry(container, 11, "默认代理名", self.proxy_name_var)

        self.status_var = tk.StringVar(
            value=f"配置文件位置：{self.env_path}"
        )
        ttk.Label(
            container,
            textvariable=self.status_var,
            foreground="#1d4ed8",
            justify="left",
            wraplength=700,
        ).grid(row=12, column=0, columnspan=2, sticky="w", pady=(10, 0))

        button_row = ttk.Frame(container)
        button_row.grid(row=13, column=0, columnspan=2, sticky="e", pady=(16, 0))
        ttk.Button(button_row, text="先跳过", command=self.handle_skip).pack(
            side="left", padx=(0, 8)
        )
        ttk.Button(button_row, text="保存并启动", command=self.handle_save).pack(side="left")

    def _create_entry(
        self,
        parent: ttk.Frame,
        row: int,
        label_text: str,
        variable: tk.StringVar,
        *,
        show: str = "",
    ) -> None:
        ttk.Label(parent, text=label_text).grid(
            row=row,
            column=0,
            sticky="w",
            padx=(0, 12),
            pady=(0, 8),
        )
        ttk.Entry(parent, textvariable=variable, show=show).grid(
            row=row,
            column=1,
            sticky="ew",
            pady=(0, 8),
        )

    def build_values(self) -> dict[str, str]:
        """收集当前表单配置。"""

        return {
            "SUB2API_BASE_URL": self.base_url_var.get().strip(),
            "SUB2API_ADMIN_API_KEY": self.admin_api_key_var.get().strip(),
            "SUB2API_GROUP_IDS": self.group_ids_var.get().strip(),
            "SUB2API_PROXY_ID": "",
            "SUB2API_IMPORT_CONCURRENCY": self.import_concurrency_var.get().strip() or "50",
            "SUB2API_IMPORT_PRIORITY": "",
            "SUB2API_UPDATE_EXISTING": "true",
            "SUB2API_SKIP_DEFAULT_GROUP_BIND": "false",
            "SUB2API_CONFIRM_MIXED_CHANNEL_RISK": "false",
            "SUB2API_OAUTH_REDIRECT_URI": self.redirect_uri_var.get().strip()
            or DEFAULT_ENV_VALUES["SUB2API_OAUTH_REDIRECT_URI"],
            "SUB2API_OAUTH_PROXY_ID": "",
            "SUB2API_OAUTH_PROXY_URL": "",
            "SUB2API_OAUTH_PROXY_NAME": self.proxy_name_var.get().strip() or "default",
            "SUB2API_OAUTH_GROUP_IDS": self.group_ids_var.get().strip(),
            "SUB2API_OAUTH_GROUP_NAME": self.group_name_var.get().strip() or "cc",
            "SUB2API_OAUTH_ACCOUNT_CONCURRENCY": self.oauth_concurrency_var.get().strip()
            or "10",
            "ACC_MOTHER_ACCOUNT_EMAIL": self.mother_email_var.get().strip(),
            "CHATGPT_RANDOM_EMAIL_DOMAIN": self.random_domain_var.get().strip()
            or "example.com",
        }

    def handle_save(self) -> None:
        """保存配置并关闭向导。"""

        values = self.build_values()
        write_env_file(self.env_path, values)
        apply_env_values_to_process(values)
        self.result = values
        self.window.destroy()

    def handle_skip(self) -> None:
        """跳过首次配置，但保留自动生成的模板文件。"""

        values = read_env_file(self.env_path)
        if not values:
            values = dict(DEFAULT_ENV_VALUES)
            write_env_file(self.env_path, values)
        apply_env_values_to_process(values)
        self.result = values
        self.window.destroy()

    def show(self) -> dict[str, str]:
        """阻塞展示向导直到关闭。"""

        self.window.wait_window()
        return dict(self.result or {})


def prepare_first_run_environment(module_file: str | Path) -> dict[str, str]:
    """处理首次启动 .env 自动生成和首次配置。"""

    env_path = ensure_env_file_exists(module_file)
    values = read_env_file(env_path)
    if has_required_remote_config(values):
        apply_env_values_to_process(values)
        return values

    root = tk.Tk()
    root.withdraw()
    dialog = FirstRunSetupDialog(root, env_path, values)
    result = dialog.show()
    root.destroy()
    return result
