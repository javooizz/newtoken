# -*- coding: utf-8 -*-
"""只保留 Sub2API 相关功能的独立桌面入口。"""

import os
import sys
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
if os.environ.get("SUB2API_SKIP_FIRST_RUN_SETUP", "").strip() != "1":
    prepare_first_run_environment(__file__)

from sub2api_converter import ConverterApp  # noqa: E402
from sub2api_converter_openai_oauth_ui import OpenAIOAuthAccountPageWindow  # noqa: E402
from standalone_acc_seat_converter_ui import StandaloneAccSeatConverterApp  # noqa: E402


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


if __name__ == "__main__":
    Sub2APIStandaloneApp().run()
