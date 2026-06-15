import concurrent.futures
import importlib
import json
import os
import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, messagebox, ttk

from sub2api_converter_archive import (
    extract_archives_in_directory,
    get_archive_extract_folder_name,
)
from sub2api_converter_core import (
    CAP_OUTPUT_MODE,
    CAP_OUTPUT_MODE_LABEL,
    DEFAULT_OUTPUT_MODE,
    MAX_CONCURRENT_CHECKS,
    OUTPUT_MODE_LABEL,
    OUTPUT_MODE_LABELS,
    build_export_account,
    build_cap_result,
    build_export_result,
    build_output_file_name,
    calculate_average_remaining_quota,
    classify_failure,
    collect_account_candidates,
    extract_chatgpt_account_id,
    parse_usage_quota,
    resolve_input_sources,
    resolve_remaining_quota,
    validate_account_candidate,
)
from sub2api_converter_remote import load_remote_import_defaults
from sub2api_converter_remote_ui import RemoteUIActionsMixin
from sub2api_first_run_setup import bring_window_to_front, center_window

__all__ = [
    "CAP_OUTPUT_MODE",
    "CAP_OUTPUT_MODE_LABEL",
    "DEFAULT_OUTPUT_MODE",
    "MAX_CONCURRENT_CHECKS",
    "OUTPUT_MODE_LABELS",
    "OUTPUT_MODE_LABEL",
    "build_export_account",
    "build_cap_result",
    "calculate_average_remaining_quota",
    "collect_account_candidates",
    "extract_chatgpt_account_id",
    "parse_usage_quota",
    "resolve_remaining_quota",
    "classify_failure",
    "build_export_result",
    "resolve_input_sources",
    "extract_archives_in_directory",
    "get_archive_extract_folder_name",
    "ConverterApp",
    "DrawerState",
    "load_remote_import_defaults",
]


@dataclass
class DrawerState:
    """保存抽屉模块的标题和展开状态。"""

    title: str
    expanded: bool = True

    def build_toggle_text(self):
        """生成当前状态对应的抽屉标题文本。"""

        marker = "▼" if self.expanded else "▶"
        return f"{marker} {self.title}"

    def toggle(self):
        """切换抽屉状态。"""

        self.expanded = not self.expanded


class DrawerSection:
    """提供可点击展开和收起的抽屉式容器。"""

    def __init__(
        self,
        parent,
        title,
        *,
        expanded=True,
        frame_pack_options=None,
        content_pack_options=None,
    ):
        self.state = DrawerState(title=title, expanded=expanded)
        self.frame = ttk.Frame(parent)
        self.frame.pack(**(frame_pack_options or {"fill": "x", "pady": (0, 8)}))
        self.toggle_button = ttk.Button(
            self.frame,
            text=self.state.build_toggle_text(),
            command=self.toggle,
        )
        self.toggle_button.pack(fill="x")
        self.content_frame = ttk.Frame(self.frame)
        self.content_pack_options = dict(content_pack_options or {"fill": "x"})
        self.sync()

    def sync(self):
        """同步按钮文案和内容显隐状态。"""

        self.toggle_button.configure(text=self.state.build_toggle_text())
        if self.state.expanded:
            if self.content_frame.winfo_manager() != "pack":
                self.content_frame.pack(**self.content_pack_options)
        elif self.content_frame.winfo_manager():
            self.content_frame.pack_forget()

    def toggle(self):
        """切换抽屉展开状态。"""

        self.state.toggle()
        self.sync()


class LogHandler:
    """把后台日志安全写回到 Tk 文本框。"""

    def __init__(self, text_widget):
        self.text = text_widget

    def write(self, msg):
        self.text.after(0, lambda: self._append(msg))

    def _append(self, msg):
        self.text.configure(state="normal")
        self.text.insert("end", msg)
        self.text.see("end")
        self.text.configure(state="disabled")


def build_mail_viewer_panel(parent, **kwargs):
    """懒加载邮件预览面板，避免独立工具打包时带上无关依赖。"""

    panel_class = importlib.import_module(
        "sub2api_converter_mail_viewer"
    ).MailViewerPanel
    return panel_class(parent, **kwargs)


def build_har_member_panel(parent):
    """懒加载 HAR 成员面板。"""

    panel_class = importlib.import_module("sub2api_converter_har_ui").HarMemberPanel
    return panel_class(parent)


def build_openai_oauth_window(parent, **kwargs):
    """懒加载 OpenAI OAuth 建号窗口。"""

    window_class = importlib.import_module(
        "sub2api_converter_openai_oauth_ui"
    ).OpenAIOAuthAccountPageWindow
    return window_class(parent, **kwargs)


class ConverterApp(RemoteUIActionsMixin):
    """主界面应用。"""

    def __init__(
        self,
        *,
        window_title="Sub2API 账号过滤转换工具",
        show_mail_viewer=True,
        show_seat_tools=True,
        show_local_tools=True,
        show_remote_import_tools=True,
        window_geometry="920x760",
        window_minsize=(720, 480),
        log_height=18,
        log_expand=True,
    ):
        remote_defaults = load_remote_import_defaults()
        self.tk = tk
        self.root = tk.Tk()
        self.root.title(window_title)
        self.root.geometry(window_geometry)
        self.root.minsize(*window_minsize)
        center_window(
            self.root,
            preferred_width=int(str(window_geometry).split("x", 1)[0]),
            preferred_height=int(str(window_geometry).split("x", 1)[1]),
        )
        self.root.after(120, self.ensure_window_visible)
        self.update_context_file = __file__
        self.openai_oauth_window = None
        self.show_local_tools = show_local_tools
        self.show_remote_import_tools = show_remote_import_tools

        try:
            self.root.iconbitmap(default="")
        except tk.TclError:
            pass

        style = ttk.Style()
        style.theme_use("vista" if "vista" in style.theme_names() else "clam")

        main = ttk.Frame(self.root, padding=16)
        main.pack(fill="both", expand=True)
        self.main_frame = main

        self.output_mode = tk.StringVar(value=DEFAULT_OUTPUT_MODE)
        self.output_mode.trace_add("write", self.handle_output_mode_changed)
        self.in_path = tk.StringVar()
        self.in_path.trace_add("write", self.handle_input_path_changed)
        self.out_path = tk.StringVar()

        self.convert_btn = None
        self.extract_btn = None
        self.copy_btn = None
        self.save_btn = None
        self.remote_import_btn = None
        self.remote_import_file_btn = None
        self.test_remote_btn = None
        self.refresh_remote_btn = None
        self.delete_dead_btn = None
        self.delete_auth_error_btn = None
        self.delete_no_quota_btn = None
        self.open_oauth_page_btn = None

        self.init_remote_stats_summary_ui(main)

        if show_local_tools:
            mode_drawer = DrawerSection(main, "目标格式", expanded=False)
            mode_frame = ttk.LabelFrame(
                mode_drawer.content_frame,
                text="目标格式",
                padding=8,
            )
            mode_frame.pack(fill="x")
            ttk.Radiobutton(
                mode_frame,
                text="转为 Sub",
                value=DEFAULT_OUTPUT_MODE,
                variable=self.output_mode,
            ).pack(side="left", padx=(0, 16))
            ttk.Radiobutton(
                mode_frame,
                text="转为 CAP",
                value=CAP_OUTPUT_MODE,
                variable=self.output_mode,
            ).pack(side="left")

            input_drawer = DrawerSection(main, "输入来源", expanded=True)
            in_frame = ttk.LabelFrame(
                input_drawer.content_frame,
                text="输入文件或目录",
                padding=8,
            )
            in_frame.pack(fill="x")
            ttk.Entry(in_frame, textvariable=self.in_path).pack(
                side="left", fill="x", expand=True, padx=(0, 8)
            )
            ttk.Button(in_frame, text="选目录", command=self.browse_input_dir).pack(
                side="right"
            )
            ttk.Button(in_frame, text="选文件", command=self.browse_input_file).pack(
                side="right", padx=(0, 8)
            )

            output_drawer = DrawerSection(main, "输出目录", expanded=False)
            out_frame = ttk.LabelFrame(
                output_drawer.content_frame,
                text="输出目录（下载结果 JSON 时使用）",
                padding=8,
            )
            out_frame.pack(fill="x")
            ttk.Entry(out_frame, textvariable=self.out_path).pack(
                side="left", fill="x", expand=True, padx=(0, 8)
            )
            ttk.Button(out_frame, text="浏览...", command=self.browse_output).pack(
                side="right"
            )

        remote_drawer = DrawerSection(main, "远程配置", expanded=False)
        self.init_remote_ui(
            remote_drawer.content_frame,
            remote_defaults,
            show_remote_import_tools=show_remote_import_tools,
        )

        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill="x", pady=(4, 8))
        action_grid = ttk.Frame(btn_frame)
        action_grid.pack(fill="x", pady=(0, 8))
        self.action_grid = action_grid
        self.action_grid_columns = 4
        self._action_buttons = []
        for column_index in range(self.action_grid_columns):
            action_grid.columnconfigure(column_index, weight=1)

        if show_local_tools:
            self.convert_btn = ttk.Button(
                action_grid,
                text="开始转换",
                command=self.start_convert,
            )
            self.extract_btn = ttk.Button(
                action_grid,
                text="一键解压压缩包",
                command=self.start_extract_archives,
            )
            self.copy_btn = ttk.Button(
                action_grid,
                text="复制结果",
                command=self.copy_cached_result,
            )
            self.save_btn = ttk.Button(
                action_grid,
                text="下载结果 JSON",
                command=self.save_cached_result,
            )
        if show_remote_import_tools:
            self.remote_import_btn = ttk.Button(
                action_grid,
                text="上传转换结果到 Sub2API",
                command=self.start_remote_import,
            )
            self.remote_import_file_btn = ttk.Button(
                action_grid,
                text="上传本地 JSON 到 Sub2API",
                command=self.start_remote_import_from_file,
            )
            self.test_remote_btn = ttk.Button(
                action_grid,
                text="测试导入连接",
                command=self.start_test_remote_connection,
            )
        self.refresh_remote_btn = ttk.Button(
            action_grid,
            text="刷新远程账号状态",
            command=self.start_remote_scan,
        )
        self.delete_dead_btn = ttk.Button(
            action_grid,
            text="一键删除死号",
            command=self.start_delete_dead_remote_accounts,
        )
        self.delete_auth_error_btn = ttk.Button(
            action_grid,
            text="删除所有401错误",
            command=self.start_delete_auth_error_remote_accounts,
        )
        self.delete_no_quota_btn = ttk.Button(
            action_grid,
            text="删除所有无额度",
            command=self.start_delete_no_quota_remote_accounts,
        )
        self.open_oauth_page_btn = ttk.Button(
            action_grid,
            text="打开一键授权建号页",
            command=self.open_openai_oauth_page,
        )
        action_buttons = []
        if show_local_tools:
            action_buttons.extend(
                [
                    self.convert_btn,
                    self.extract_btn,
                    self.copy_btn,
                    self.save_btn,
                ]
            )
        if show_remote_import_tools:
            action_buttons.extend(
                [
                    self.remote_import_btn,
                    self.remote_import_file_btn,
                    self.test_remote_btn,
                ]
            )
        action_buttons.extend(
            [
            self.refresh_remote_btn,
            self.delete_dead_btn,
            self.delete_auth_error_btn,
            self.delete_no_quota_btn,
            self.open_oauth_page_btn,
            ]
        )
        for button in action_buttons:
            self.add_action_button_widget(button)

        status_frame = ttk.Frame(btn_frame)
        status_frame.pack(fill="x")
        self.progress = ttk.Progressbar(status_frame, mode="determinate", value=0)
        self.progress.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(status_frame, textvariable=self.status_var, font=("Segoe UI", 9)).pack(
            side="right"
        )

        log_drawer = DrawerSection(
            main,
            "运行日志",
            expanded=True,
            frame_pack_options={"fill": "both", "expand": log_expand, "pady": (0, 0)},
            content_pack_options={"fill": "both", "expand": log_expand},
        )
        self.log_drawer = log_drawer
        log_frame = ttk.LabelFrame(log_drawer.content_frame, text="运行日志", padding=4)
        log_frame.pack(fill="both", expand=True)
        self.log_text = tk.Text(
            log_frame,
            height=log_height,
            wrap="word",
            state="disabled",
            font=("Consolas", 10),
            bg="#1e1e1e",
            fg="#d4d4d4",
            insertbackground="white",
        )
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)

        self.log = LogHandler(self.log_text)
        if show_local_tools:
            self.log.write("工具就绪，请选择单个 JSON 或目录输入\n")
            self.log.write("先选目标格式，再点一次开始转换，成功后可反复复制或下载结果\n")
        else:
            self.log.write("Sub2API 独立工具就绪，可直接刷新远程账号状态或打开授权建号页\n")


        self.mail_viewer = None
        if show_mail_viewer:
            mail_drawer = DrawerSection(
                main,
                "邮件 Html 预览",
                expanded=False,
                frame_pack_options={"fill": "both", "expand": False, "pady": (0, 8)},
                content_pack_options={"fill": "both", "expand": False},
            )
            mail_frame = ttk.LabelFrame(
                mail_drawer.content_frame,
                text="邮件 Html 预览",
                padding=4,
            )
            mail_frame.pack(fill="both", expand=True)
            self.mail_viewer = build_mail_viewer_panel(
                mail_frame,
                show_member_manager=False,
            )

        self.har_panel = None
        if show_seat_tools:
            seat_drawer = DrawerSection(
                main,
                "席位管理工具",
                expanded=False,
                frame_pack_options={"fill": "both", "expand": False, "pady": (0, 8)},
                content_pack_options={"fill": "both", "expand": False},
            )
            seat_frame = ttk.LabelFrame(
                seat_drawer.content_frame,
                text="席位管理工具",
                padding=4,
            )
            seat_frame.pack(fill="both", expand=True)
            self.har_panel = build_har_member_panel(seat_frame)

        self.convert_queue = queue.Queue()
        self.cached_payload_text = ""
        self.cached_summary = None
        self.cached_remote_scan_summary = None
        self.current_input_signature = ""
        self.cached_output_mode = DEFAULT_OUTPUT_MODE
        self.is_running = False
        self.set_export_buttons_enabled(False)
        self.update_remote_buttons_state()
        self.root.after(100, self.poll_queue)
        self.root.after(300, self.maybe_auto_refresh_remote_stats)

    def ensure_window_visible(self):
        """启动后把主窗口提到前台，避免看起来像没打开。"""

        bring_window_to_front(self.root)

    def handle_input_path_changed(self, *_args):
        self.reset_cached_result()

    def handle_output_mode_changed(self, *_args):
        self.reset_cached_result()

    def maybe_auto_refresh_remote_stats(self):
        """启动时在远程配置完整时静默刷新一次远程统计。"""

        if self.remote_base_url.get().strip() and self.remote_api_key.get().strip():
            self.start_remote_scan(announce=False)

    def browse_input_file(self):
        path = filedialog.askopenfilename(
            title="选择单个 JSON 文件",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
        )
        if path:
            self.in_path.set(path)
            self.log.write(f"输入文件: {path}\n")

    def browse_input_dir(self):
        path = filedialog.askdirectory(title="选择目录")
        if path:
            self.in_path.set(path)
            self.log.write(f"输入目录: {path}\n")

    def browse_output(self):
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.out_path.set(path)
            self.log.write(f"输出目录: {path}\n")

    def open_openai_oauth_page(self):
        """打开独立的一键授权建号页。"""

        if self.openai_oauth_window and self.openai_oauth_window.window.winfo_exists():
            self.openai_oauth_window.focus()
            return
        self.openai_oauth_window = build_openai_oauth_window(
            self.root,
            on_close=self._handle_openai_oauth_page_closed,
        )
        self.log.write("已打开一键授权建号页\n")

    def _handle_openai_oauth_page_closed(self):
        """在授权建号页关闭后清理窗口引用。"""

        self.openai_oauth_window = None

    def add_action_button_widget(self, button):
        """把按钮挂到共享按钮区，并自动计算网格位置。"""

        index = len(self._action_buttons)
        row_index = index // self.action_grid_columns
        column_index = index % self.action_grid_columns
        button.grid(
            row=row_index,
            column=column_index,
            sticky="ew",
            padx=4,
            pady=4,
        )
        self._action_buttons.append(button)

    def add_action_button(self, text, command):
        """在主按钮区追加一个新按钮。"""

        button = ttk.Button(
            self.action_grid,
            text=text,
            command=command,
        )
        self.add_action_button_widget(button)
        return button

    def set_export_buttons_enabled(self, enabled):
        state = "normal" if enabled else "disabled"
        if self.copy_btn is not None:
            self.copy_btn.configure(state=state)
        if self.save_btn is not None:
            self.save_btn.configure(state=state)

    def set_running(self, running):
        self.is_running = running
        if self.convert_btn is not None:
            self.convert_btn.configure(state="disabled" if running else "normal")
        if self.extract_btn is not None:
            self.extract_btn.configure(state="disabled" if running else "normal")
        if running:
            self.set_export_buttons_enabled(False)
        else:
            self.set_export_buttons_enabled(bool(self.cached_payload_text))
        self.update_remote_buttons_state()

    def copy_text_to_clipboard(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.root.update()

    def reset_cached_result(self):
        self.cached_payload_text = ""
        self.cached_summary = None
        self.current_input_signature = ""
        self.cached_output_mode = DEFAULT_OUTPUT_MODE
        self.set_export_buttons_enabled(False)
        self.update_remote_buttons_state()

    def build_input_signature(self, input_path):
        return f"{self.output_mode.get()}::{os.path.abspath(input_path)}"

    def start_convert(self):
        input_path = self.in_path.get().strip()
        output_mode = self.output_mode.get()
        if not input_path or not os.path.exists(input_path):
            messagebox.showerror("错误", "请选择有效的输入文件或目录")
            return

        try:
            input_sources = resolve_input_sources(input_path)
        except ValueError as exc:
            messagebox.showerror("错误", str(exc))
            return
        if not input_sources:
            messagebox.showinfo("提示", "没有找到可转换的 JSON 文件")
            return

        self.reset_cached_result()
        self.set_running(True)
        self.progress["value"] = 0
        self.progress["maximum"] = 1
        self.status_var.set("扫描账号中...")
        self.log.write(
            f"\n开始执行：任意 JSON -> {OUTPUT_MODE_LABELS.get(output_mode, OUTPUT_MODE_LABEL)}\n"
        )
        self.log.write(
            f"共发现 {len(input_sources)} 个输入来源，准备并发刷新 Codex 账号状态\n"
        )

        worker = threading.Thread(
            target=self._run_convert,
            args=(input_sources, self.build_input_signature(input_path), output_mode),
            daemon=True,
        )
        worker.start()

    def start_extract_archives(self):
        input_path = self.in_path.get().strip()
        if not input_path or not os.path.isdir(input_path):
            messagebox.showerror("错误", "请先选择一个要解压压缩包的目录")
            return
        self.set_running(True)
        self.status_var.set("批量解压压缩包中...")
        self.log.write(f"\n开始批量解压目录内压缩包: {input_path}\n")
        worker = threading.Thread(
            target=self._run_extract_archives,
            args=(input_path,),
            daemon=True,
        )
        worker.start()

    def _run_extract_archives(self, input_path):
        try:
            summary = extract_archives_in_directory(input_path)
            self.convert_queue.put(("extract_done", summary))
        except Exception as exc:  # noqa: BLE001
            self.convert_queue.put(("extract_error", str(exc)))

    def _run_convert(self, input_sources, input_signature, output_mode):
        candidates, skipped_duplicates = collect_account_candidates(input_sources)
        self.convert_queue.put(
            ("scan", len(candidates), skipped_duplicates, len(input_sources))
        )
        if not candidates:
            self.finish_with_summary(
                len(input_sources),
                [],
                {"auth_error": 0, "quota_error": 0, "other_error": 0},
                input_signature,
                output_mode,
            )
            return

        usable_results = []
        counts = {"auth_error": 0, "quota_error": 0, "other_error": 0}
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=MAX_CONCURRENT_CHECKS
        ) as executor:
            futures = [
                executor.submit(validate_account_candidate, candidate)
                for candidate in candidates
            ]
            finished = 0
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                finished += 1
                self.handle_single_result(result, usable_results, counts, finished)

        self.finish_with_summary(
            len(input_sources),
            usable_results,
            counts,
            input_signature,
            output_mode,
        )

    def handle_single_result(self, result, usable_results, counts, finished):
        if result.status == "ok":
            usable_results.append(result)
            message = (
                f"[KEEP] {result.folder_name}/{result.file_name} | "
                f"{result.email} | {result.reason}\n"
            )
        elif result.status == "auth_error":
            counts["auth_error"] += 1
            message = (
                f"[DROP][401/授权] {result.folder_name}/{result.file_name} | "
                f"{result.email} | {result.reason}\n"
            )
        elif result.status == "quota_error":
            counts["quota_error"] += 1
            message = (
                f"[DROP][无额度] {result.folder_name}/{result.file_name} | "
                f"{result.email} | {result.reason}\n"
            )
        else:
            counts["other_error"] += 1
            message = (
                f"[DROP][其他错误] {result.folder_name}/{result.file_name} | "
                f"{result.email} | {result.reason}\n"
            )
        self.convert_queue.put(("progress", finished, message))

    def finish_with_summary(
        self,
        source_count,
        usable_results,
        counts,
        input_signature,
        output_mode,
    ):
        usable_accounts = [
            result.account
            for result in sorted(usable_results, key=lambda item: item.order)
            if result.account is not None
        ]
        payload = (
            build_cap_result(usable_accounts)
            if output_mode == CAP_OUTPUT_MODE
            else build_export_result(usable_accounts)
        )
        payload_text = json.dumps(payload, ensure_ascii=False, indent=2)
        summary = {
            "source_count": source_count,
            "total_candidates": len(usable_results)
            + counts["auth_error"]
            + counts["quota_error"]
            + counts["other_error"],
            "usable_count": len(usable_accounts),
            "average_remaining_quota": calculate_average_remaining_quota(
                usable_results
            ),
            "auth_error_count": counts["auth_error"],
            "quota_error_count": counts["quota_error"],
            "other_error_count": counts["other_error"],
            "payload_text": payload_text,
            "input_signature": input_signature,
            "output_mode": output_mode,
        }
        self.convert_queue.put(("done", summary))

    def poll_queue(self):
        try:
            while True:
                msg = self.convert_queue.get_nowait()
                message_type = msg[0]
                if message_type == "scan":
                    self.handle_scan_message(*msg[1:])
                elif message_type == "progress":
                    finished = msg[1]
                    self.progress["value"] = finished
                    self.status_var.set(
                        f"校验中 {finished}/{int(self.progress['maximum'])}"
                    )
                    self.log.write(msg[2])
                elif message_type == "done":
                    self.handle_done_message(msg[1])
                elif message_type == "remote_done":
                    self.handle_remote_done_message(msg[1], msg[2])
                elif message_type == "remote_error":
                    self.handle_remote_error_message(msg[1], msg[2])
                elif message_type == "extract_done":
                    self.handle_extract_done_message(msg[1])
                elif message_type == "extract_error":
                    self.handle_extract_error_message(msg[1])
        except queue.Empty:
            pass
        self.root.after(100, self.poll_queue)

    def handle_scan_message(self, total_candidates, skipped_duplicates, source_count):
        self.progress["value"] = 0
        self.progress["maximum"] = max(1, total_candidates)
        self.status_var.set(f"校验中 0/{total_candidates}")
        self.log.write(
            f"共扫描到 {total_candidates} 个候选账号，来自 {source_count} 个输入来源\n"
        )
        if skipped_duplicates:
            self.log.write(
                f"跳过 {skipped_duplicates} 个重复账号，避免同一 refresh_token 被重复刷新\n"
            )
        self.log.write(f"并发校验线程数：{MAX_CONCURRENT_CHECKS}\n")

    def handle_done_message(self, summary):
        self.cached_payload_text = summary["payload_text"]
        self.cached_summary = summary
        self.current_input_signature = summary["input_signature"]
        self.cached_output_mode = summary["output_mode"]
        self.set_running(False)
        self.log.write("\n========== 处理完成 ==========\n")
        self.status_var.set(
            f"完成，可用 {summary['usable_count']} / {summary['total_candidates']}"
        )
        self.log.write(
            f"候选账号 {summary['total_candidates']} | 可用账号: {summary['usable_count']}\n"
        )
        self.log.write(
            f"401/授权错误: {summary['auth_error_count']} | "
            f"无额度: {summary['quota_error_count']} | "
            f"其他错误: {summary['other_error_count']}\n"
        )
        self.log.write(
            f"平均剩余额度: {summary['average_remaining_quota']:.2f}%\n"
        )
        detail_lines = [
            f"共处理 {summary['source_count']} 个输入来源",
            f"候选账号 {summary['total_candidates']} 个",
            f"可用账号 {summary['usable_count']} 个",
            f"平均剩余额度 {summary['average_remaining_quota']:.2f}%",
            f"401/授权错误 {summary['auth_error_count']} 个",
            f"无额度 {summary['quota_error_count']} 个",
            f"其他错误 {summary['other_error_count']} 个",
            "转换已完成，可直接重复复制或下载，无需重新执行转换。",
        ]
        self.log.write("转换结果已缓存，现在可以反复点击“复制结果”或“下载结果 JSON”\n")
        messagebox.showinfo(
            f"{self.get_output_mode_label()} 转换完成",
            "\n".join(detail_lines),
        )

    def handle_extract_done_message(self, summary):
        """处理批量解压完成结果。"""

        self.set_running(False)
        self.status_var.set(
            f"解压完成 新增{summary['extracted_count']} 跳过{summary['skipped_count']}"
        )
        self.log.write(
            "批量解压完成: "
            f"found={summary['found_count']} extracted={summary['extracted_count']} "
            f"skipped={summary['skipped_count']} unsupported={summary['unsupported_count']}\n"
        )
        for item in summary["items"]:
            self.log.write(
                f"[EXTRACT][{item['status'].upper()}] {item['archive_path']} -> "
                f"{item['target_dir']} | {item['message']}\n"
            )
        for item in summary["unsupported_items"]:
            self.log.write(
                f"[EXTRACT][UNSUPPORTED] {item['archive_path']} | {item['message']}\n"
            )
        messagebox.showinfo(
            "一键解压完成",
            "\n".join(
                [
                    f"目录：{summary['input_dir']}",
                    f"发现可解压压缩包：{summary['found_count']}",
                    f"成功解压：{summary['extracted_count']}",
                    f"跳过同名目录：{summary['skipped_count']}",
                    f"暂不支持格式：{summary['unsupported_count']}",
                ]
            ),
        )

    def handle_extract_error_message(self, error_message):
        """处理批量解压失败结果。"""

        self.set_running(False)
        self.status_var.set("批量解压失败")
        self.log.write(f"[EXTRACT][ERROR] {error_message}\n")
        messagebox.showerror("一键解压失败", error_message)

    def get_output_mode_label(self):
        if self.cached_output_mode == CAP_OUTPUT_MODE:
            return CAP_OUTPUT_MODE_LABEL
        return OUTPUT_MODE_LABEL

    def ensure_cached_result_available(self):
        input_path = self.in_path.get().strip()
        if not self.cached_payload_text or not self.cached_summary:
            messagebox.showerror("错误", "请先点击“开始转换”生成结果")
            return False
        if self.current_input_signature != self.build_input_signature(input_path):
            messagebox.showerror("错误", "输入已变化，请重新点击“开始转换”")
            return False
        return True

    def copy_cached_result(self):
        if not self.ensure_cached_result_available():
            return
        self.copy_text_to_clipboard(self.cached_payload_text)
        self.log.write("结果已从缓存复制到剪贴板，未重新跑转换流程\n")
        messagebox.showinfo(
            f"{self.get_output_mode_label()} 复制完成",
            "结果已复制到剪贴板，本次未重新跑转换流程。",
        )

    def save_cached_result(self):
        if not self.ensure_cached_result_available():
            return
        input_path = self.in_path.get().strip()
        out_dir = self.out_path.get().strip()
        if not out_dir:
            out_dir = (
                os.path.dirname(input_path)
                if os.path.isfile(input_path)
                else input_path
            )
            self.out_path.set(out_dir)
        os.makedirs(out_dir, exist_ok=True)
        output_path = os.path.join(
            out_dir,
            build_output_file_name(self.cached_output_mode),
        )
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write(self.cached_payload_text)
        self.log.write(f"结果已从缓存写出到文件: {output_path}\n")
        messagebox.showinfo(
            f"{self.get_output_mode_label()} 下载完成",
            f"结果已写出到：\n{output_path}\n\n本次未重新跑转换流程。",
        )

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    ConverterApp().run()
