# -*- coding: utf-8 -*-
"""只保留 Sub2API 相关功能的独立桌面入口。"""

import ctypes
import os
import sys
import traceback
from pathlib import Path
from tkinter import ttk

LOCAL_PROJECT_DIR = Path(__file__).resolve().parent
if str(LOCAL_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(LOCAL_PROJECT_DIR))

from sub2api_first_run_setup import prepare_first_run_environment  # noqa: E402
from sub2api_runtime import chdir_to_app_dir, ensure_on_sys_path, get_app_dir  # noqa: E402

PROJECT_DIR = get_app_dir(__file__)
STANDALONE_DIR = chdir_to_app_dir(__file__)
ensure_on_sys_path(PROJECT_DIR)
ensure_on_sys_path(STANDALONE_DIR)

from sub2api_converter import ConverterApp  # noqa: E402
from sub2api_converter_openai_oauth_ui import OpenAIOAuthAccountPageWindow  # noqa: E402
from standalone_acc_seat_converter_ui import StandaloneAccSeatConverterApp  # noqa: E402

APP_MUTEX_NAME = "Global\\Sub2APIStandaloneToolSingleton"
_APP_MUTEX_HANDLE = None


class Sub2APIStandaloneApp(ConverterApp):
    """独立的 Sub2API 工具，只保留远程管理和授权建号。"""

    def __init__(self):
        super().__init__(
            window_title="Sub2API 独立工具",
            show_mail_viewer=False,
            show_seat_tools=False,
            show_local_tools=False,
            show_remote_import_tools=False,
            window_geometry="1280x900",
            window_minsize=(1080, 760),
            log_height=8,
            log_expand=False,
        )
        self.update_context_file = __file__
        self.acc_panel_frame = ttk.LabelFrame(
            self.main_frame,
            text="ACC席位工具",
            padding=4,
        )
        self.acc_panel_frame.pack(
            before=self.log_drawer.frame,
            fill="both",
            expand=True,
            pady=(0, 8),
        )
        self.acc_panel = StandaloneAccSeatConverterApp(
            self.acc_panel_frame,
            embedded=True,
            status_var=self.status_var,
            log_handler=self.log,
        )
        self.log.write("Sub2API 与 ACC 已合并为单页模式\n")

    def open_openai_oauth_page(self):
        """打开带 Codex 停用后处理的一键授权建号页。"""

        if self.openai_oauth_window and self.openai_oauth_window.window.winfo_exists():
            self.openai_oauth_window.focus()
            return
        self.openai_oauth_window = OpenAIOAuthAccountPageWindow(
            self.root,
            on_close=self._handle_openai_oauth_page_closed,
            on_account_created=self.acc_panel.handle_created_remote_oauth_account,
        )
        self.log.write("已打开一键授权建号页\n")


def write_startup_error_log(base_dir: str | Path, exc: BaseException) -> Path:
    """把启动异常写到 exe 同目录，便于排查双击无反应。"""

    target_dir = Path(base_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    log_path = target_dir / "startup_error.log"
    error_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    lines = [
        "Sub2API 独立工具启动失败",
        "",
        error_text.strip(),
        "",
    ]
    log_path.write_text("\n".join(lines), encoding="utf-8")
    return log_path


def show_startup_error_message(log_path: Path) -> None:
    """用系统弹窗提示用户去看启动日志。"""

    try:
        ctypes.windll.user32.MessageBoxW(
            0,
            f"Sub2API 启动失败，错误日志已写入：\n{log_path}",
            "Sub2API 启动失败",
            0x10,
        )
    except Exception:
        return


def acquire_single_instance_mutex() -> bool:
    """限制同一台机器同时只开一个独立工具实例。"""

    global _APP_MUTEX_HANDLE
    create_mutex = ctypes.windll.kernel32.CreateMutexW
    get_last_error = ctypes.windll.kernel32.GetLastError
    create_mutex.restype = ctypes.c_void_p
    handle = create_mutex(None, False, APP_MUTEX_NAME)
    if not handle:
        return True
    _APP_MUTEX_HANDLE = handle
    return int(get_last_error()) != 183


def show_already_running_message() -> None:
    """提示用户程序已经在运行。"""

    try:
        ctypes.windll.user32.MessageBoxW(
            0,
            "Sub2API 已经在运行了。\n请先查看任务栏、Alt+Tab，或结束旧进程后再重开。",
            "Sub2API 已在运行",
            0x30,
        )
    except Exception:
        return


def main() -> int:
    """独立工具入口。"""

    try:
        if not acquire_single_instance_mutex():
            show_already_running_message()
            return 0
        if os.environ.get("SUB2API_SKIP_FIRST_RUN_SETUP", "").strip() != "1":
            prepare_first_run_environment(__file__)
        Sub2APIStandaloneApp().run()
        return 0
    except Exception as exc:  # noqa: BLE001
        log_path = write_startup_error_log(get_app_dir(__file__), exc)
        show_startup_error_message(log_path)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
