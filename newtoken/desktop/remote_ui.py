import threading
import webbrowser
from tkinter import filedialog, messagebox, ttk

from newtoken.desktop.github_updater import (
    GITHUB_PROJECT_LABEL,
    GITHUB_PROJECT_URL,
    QQ_GROUP_LABEL,
    QQ_GROUP_URL,
    build_github_update_check_result,
    prepare_github_update,
)
from newtoken.sub2api.remote import (
    build_remote_config,
    delete_dead_remote_accounts,
    import_to_sub2api_codex_session,
    load_remote_import_defaults,
    mask_secret_value,
    scan_remote_accounts,
    select_remote_accounts_with_auth_error,
    select_remote_accounts_without_quota,
    set_all_remote_openai_account_privacy,
    test_sub2api_connection,
)


class RemoteUIActionsMixin:
    """封装远程 Sub2API 面板、统计展示和相关动作。"""

    def _set_button_state(self, button, state):
        """在按钮存在时更新其状态。"""

        if button is not None:
            button.configure(state=state)

    def init_remote_stats_summary_ui(self, main):
        """初始化顶部远程账号统计模块。"""

        stats_box = ttk.Frame(main)
        stats_box.pack(fill="x", pady=(0, 8))
        stats_box.columnconfigure(0, weight=1)

        self.remote_total_var = self.tk.StringVar(value="未刷新")
        self.remote_alive_var = self.tk.StringVar(value="未刷新")
        self.remote_dead_var = self.tk.StringVar(value="未刷新")
        self.remote_no_quota_var = self.tk.StringVar(value="未刷新")
        self.remote_average_var = self.tk.StringVar(value="未刷新")
        self.remote_today_tokens_var = self.tk.StringVar(value="未刷新")
        self.remote_last_hour_tokens_var = self.tk.StringVar(value="未刷新")
        self.remote_previous_hour_tokens_var = self.tk.StringVar(value="未刷新")
        self.cached_github_update_result = None

        summary_frame = ttk.Frame(stats_box)
        summary_frame.grid(row=0, column=0, sticky="ew")
        self._create_remote_inline_stat(summary_frame, 0, "总", self.remote_total_var)
        self._create_remote_inline_stat(summary_frame, 1, "活", self.remote_alive_var)
        self._create_remote_inline_stat(summary_frame, 2, "死", self.remote_dead_var)
        self._create_remote_inline_stat(summary_frame, 3, "无", self.remote_no_quota_var)
        self._create_remote_inline_stat(summary_frame, 4, "均", self.remote_average_var)
        self._create_remote_inline_stat(
            summary_frame, 5, "今T", self.remote_today_tokens_var
        )
        self._create_remote_inline_stat(
            summary_frame, 6, "1时T", self.remote_last_hour_tokens_var
        )
        self._create_remote_inline_stat(
            summary_frame, 7, "2时T", self.remote_previous_hour_tokens_var
        )
        self.qq_group_link_label = self.tk.Label(
            summary_frame,
            text=QQ_GROUP_LABEL,
            fg="#2563eb",
            cursor="hand2",
        )
        self.qq_group_link_label.grid(row=0, column=8, sticky="w", padx=(4, 12))
        self.qq_group_link_label.bind(
            "<Button-1>",
            lambda _event: self.open_qq_group_link(),
        )
        self.github_project_link_label = self.tk.Label(
            summary_frame,
            text=GITHUB_PROJECT_LABEL,
            fg="#16a34a",
            cursor="hand2",
        )
        self.github_project_link_label.grid(row=0, column=9, sticky="w", padx=(0, 12))
        self.github_project_link_label.bind(
            "<Button-1>",
            lambda _event: self.open_github_project_link(),
        )
        summary_frame.columnconfigure(10, weight=1)
        action_frame = ttk.Frame(summary_frame)
        action_frame.grid(row=0, column=11, sticky="e")
        self.refresh_remote_stats_btn = ttk.Button(
            action_frame,
            text="刷新",
            command=self.start_remote_scan,
        )
        self.refresh_remote_stats_btn.pack(side="left")
        self.check_update_btn = ttk.Button(
            action_frame,
            text="检查更新",
            command=self.start_check_github_update,
        )
        self.check_update_btn.pack(side="left", padx=(8, 0))
        self.apply_update_btn = ttk.Button(
            action_frame,
            text="一键更新",
            command=self.start_apply_github_update,
        )
        self.apply_update_btn.pack(side="left", padx=(8, 0))

    def open_qq_group_link(self):
        """打开 QQ 群邀请链接。"""

        try:
            webbrowser.open(QQ_GROUP_URL)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("打开QQ群失败", str(exc))
            return
        self.status_var.set("已打开 QQ 群链接")
        self.log.write(f"已打开 QQ 群链接: {QQ_GROUP_URL}\n")

    def open_github_project_link(self):
        """打开 GitHub 项目页面。"""

        try:
            webbrowser.open(GITHUB_PROJECT_URL)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("打开GitHub失败", str(exc))
            return
        self.status_var.set("已打开 GitHub 项目页")
        self.log.write(f"已打开 GitHub 项目页: {GITHUB_PROJECT_URL}\n")

    def init_remote_ui(self, main, remote_defaults, *, show_remote_import_tools=True):
        """初始化远程导入配置输入区和远程统计显示区。"""

        frame_title = (
            "Sub2API 远程导入（可选）"
            if show_remote_import_tools
            else "Sub2API 远程管理"
        )
        remote_frame = ttk.LabelFrame(main, text=frame_title, padding=8)
        remote_frame.pack(fill="x", pady=(0, 8))
        self.remote_default_values = dict(remote_defaults)

        self.remote_base_url = self.tk.StringVar(value=remote_defaults["base_url"])
        self.remote_api_key = self.tk.StringVar(
            value=remote_defaults["admin_api_key"]
        )
        self.remote_group_ids = self.tk.StringVar(value=remote_defaults["group_ids"])
        self.remote_proxy_id = self.tk.StringVar(value=remote_defaults["proxy_id"])
        self.remote_import_concurrency = self.tk.StringVar(
            value=remote_defaults["concurrency"]
        )
        self.remote_import_priority = self.tk.StringVar(
            value=remote_defaults["priority"]
        )
        self.remote_update_existing = self.tk.BooleanVar(
            value=remote_defaults["update_existing"]
        )
        self.remote_skip_default_group_bind = self.tk.BooleanVar(
            value=remote_defaults["skip_default_group_bind"]
        )

        remote_frame.columnconfigure(1, weight=1)
        remote_frame.columnconfigure(3, weight=1)

        self._create_remote_entry(remote_frame, 0, 0, "服务器地址", self.remote_base_url)
        self._create_remote_entry(
            remote_frame,
            0,
            2,
            "管理员 API Key",
            self.remote_api_key,
            show="*",
        )
        self._create_remote_entry(remote_frame, 1, 0, "分组 ID", self.remote_group_ids)
        self._create_remote_entry(remote_frame, 1, 2, "代理 ID", self.remote_proxy_id)
        self._create_remote_entry(
            remote_frame,
            2,
            0,
            "导入并发",
            self.remote_import_concurrency,
        )
        self._create_remote_entry(
            remote_frame,
            2,
            2,
            "导入优先级",
            self.remote_import_priority,
        )

        ttk.Checkbutton(
            remote_frame,
            text="重复账号自动更新",
            variable=self.remote_update_existing,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 4))
        ttk.Checkbutton(
            remote_frame,
            text="跳过默认分组绑定",
            variable=self.remote_skip_default_group_bind,
        ).grid(row=3, column=2, columnspan=2, sticky="w", pady=(0, 4))

        ttk.Label(
            remote_frame,
            text=(
                "Sub 聚合 JSON 会走 Wei-Shaw/sub2api 官方 /accounts/data 原生导入，"
                "CAP JSON 会走 import/codex-session。"
                "建议把服务器地址和管理员 Key 放到 .env，避免写进代码。"
                if show_remote_import_tools
                else "这里保留远程管理所需的服务器地址、管理员 Key、默认分组和代理配置。"
            ),
            wraplength=860,
            justify="left",
        ).grid(row=4, column=0, columnspan=4, sticky="w")

        action_frame = ttk.Frame(remote_frame)
        action_frame.grid(row=5, column=0, columnspan=4, sticky="w", pady=(8, 0))
        self.reload_remote_defaults_btn = ttk.Button(
            action_frame,
            text="读取 .env 配置",
            command=self.reload_remote_defaults_from_env,
        )
        self.reload_remote_defaults_btn.pack(side="left", padx=(0, 8))
        self.clear_remote_config_btn = ttk.Button(
            action_frame,
            text="清空远程配置",
            command=self.clear_remote_import_config,
        )
        self.clear_remote_config_btn.pack(side="left")
        self.set_privacy_btn = ttk.Button(
            action_frame,
            text="一键隐私",
            command=self.start_set_all_remote_account_privacy,
        )
        self.set_privacy_btn.pack(side="left", padx=(8, 0))

    def _create_remote_entry(self, parent, row, column, label_text, variable, show=""):
        """创建远程配置输入项。"""

        ttk.Label(parent, text=label_text).grid(
            row=row,
            column=column,
            sticky="w",
            padx=(0 if column == 0 else 12, 8),
            pady=(0, 6),
        )
        ttk.Entry(parent, textvariable=variable, show=show).grid(
            row=row,
            column=column + 1,
            sticky="ew",
            pady=(0, 6),
        )

    def _create_remote_stat(self, parent, column, label_text, variable):
        """创建远程统计项。"""

        ttk.Label(parent, text=label_text).grid(row=0, column=column, sticky="w")
        ttk.Label(parent, textvariable=variable).grid(row=1, column=column, sticky="w")

    def _create_remote_inline_stat(self, parent, column, prefix_text, variable):
        """创建单行紧凑远程统计项。"""

        stat_frame = ttk.Frame(parent)
        stat_frame.grid(row=0, column=column, sticky="w", padx=(0, 12))
        ttk.Label(stat_frame, text=prefix_text).pack(side="left")
        ttk.Label(stat_frame, textvariable=variable).pack(side="left", padx=(4, 0))

    def format_remote_token_count(self, raw_value):
        """把 token 数压缩成紧凑展示文本。"""

        if raw_value is None:
            return "--"
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            return "--"
        if value >= 1_000_000_000:
            return f"{value / 1_000_000_000:.2f}B"
        if value >= 1_000_000:
            return f"{value / 1_000_000:.2f}M"
        if value >= 1_000:
            return f"{value / 1_000:.2f}K"
        return str(value)

    def apply_remote_defaults(self, remote_defaults):
        """把读取到的远程默认配置批量回填到界面。"""

        self.remote_default_values = dict(remote_defaults)
        self.remote_base_url.set(remote_defaults["base_url"])
        self.remote_api_key.set(remote_defaults["admin_api_key"])
        self.remote_group_ids.set(remote_defaults["group_ids"])
        self.remote_proxy_id.set(remote_defaults["proxy_id"])
        self.remote_import_concurrency.set(remote_defaults["concurrency"])
        self.remote_import_priority.set(remote_defaults["priority"])
        self.remote_update_existing.set(remote_defaults["update_existing"])
        self.remote_skip_default_group_bind.set(
            remote_defaults["skip_default_group_bind"]
        )

    def reload_remote_defaults_from_env(self):
        """重新读取项目目录下的 .env 并刷新远程配置输入框。"""

        remote_defaults = load_remote_import_defaults()
        self.apply_remote_defaults(remote_defaults)
        self.update_remote_buttons_state()
        self.status_var.set("已读取 .env 远程配置")
        self.log.write("已从 .env 重新读取远程配置并回填到界面\n")

    def clear_remote_import_config(self):
        """清空当前远程配置输入。"""

        self.remote_base_url.set("")
        self.remote_api_key.set("")
        self.remote_group_ids.set("")
        self.remote_proxy_id.set("")
        self.remote_import_concurrency.set("")
        self.remote_import_priority.set("")
        self.remote_update_existing.set(True)
        self.remote_skip_default_group_bind.set(False)
        self.update_remote_buttons_state()
        self.status_var.set("已清空远程配置")
        self.log.write("已清空远程配置输入框\n")

    def build_remote_import_config(self):
        """把界面中的远程导入配置转换成统一对象。"""

        return build_remote_config(
            base_url=self.remote_base_url.get(),
            admin_api_key=self.remote_api_key.get(),
            group_ids_text=self.remote_group_ids.get(),
            proxy_id_text=self.remote_proxy_id.get(),
            concurrency_text=self.remote_import_concurrency.get(),
            priority_text=self.remote_import_priority.get(),
            update_existing=self.remote_update_existing.get(),
            skip_default_group_bind=self.remote_skip_default_group_bind.get(),
        )

    def update_remote_buttons_state(self):
        """根据运行状态和缓存结果刷新远程按钮可用性。"""

        if self.is_running:
            self._set_button_state(self.reload_remote_defaults_btn, "disabled")
            self._set_button_state(self.clear_remote_config_btn, "disabled")
            self._set_button_state(self.refresh_remote_stats_btn, "disabled")
            self._set_button_state(self.check_update_btn, "disabled")
            self._set_button_state(self.apply_update_btn, "disabled")
            self._set_button_state(self.set_privacy_btn, "disabled")
            self._set_button_state(self.test_remote_btn, "disabled")
            self._set_button_state(self.remote_import_btn, "disabled")
            self._set_button_state(self.remote_import_file_btn, "disabled")
            self._set_button_state(self.refresh_remote_btn, "disabled")
            self._set_button_state(self.delete_dead_btn, "disabled")
            self._set_button_state(self.delete_auth_error_btn, "disabled")
            self._set_button_state(self.delete_no_quota_btn, "disabled")
            return
        self._set_button_state(self.reload_remote_defaults_btn, "normal")
        self._set_button_state(self.clear_remote_config_btn, "normal")
        self._set_button_state(self.refresh_remote_stats_btn, "normal")
        self._set_button_state(self.check_update_btn, "normal")
        self._set_button_state(self.apply_update_btn, "normal")
        self._set_button_state(self.set_privacy_btn, "normal")
        self._set_button_state(self.test_remote_btn, "normal")
        self._set_button_state(self.refresh_remote_btn, "normal")
        self._set_button_state(self.remote_import_file_btn, "normal")
        self._set_button_state(
            self.remote_import_btn,
            "normal" if self.cached_payload_text else "disabled",
        )
        self._set_button_state(
            self.delete_dead_btn,
            (
                "normal"
                if self.cached_remote_scan_summary
                and self.cached_remote_scan_summary.get("dead_count", 0) > 0
                else "disabled"
            ),
        )
        self._set_button_state(
            self.delete_auth_error_btn,
            "normal" if self.get_remote_auth_error_items() else "disabled",
        )
        self._set_button_state(
            self.delete_no_quota_btn,
            "normal" if self.get_remote_no_quota_items() else "disabled",
        )

    def start_test_remote_connection(self):
        """异步测试远程 Sub2API 管理接口连通性。"""

        try:
            remote_config = self.build_remote_import_config()
        except ValueError as exc:
            messagebox.showerror("错误", str(exc))
            return
        self.set_running(True)
        self.status_var.set("测试 Sub2API 连接中...")
        self.log.write(
            "开始测试 Sub2API 管理接口连接: "
            f"{remote_config.base_url} | key {mask_secret_value(remote_config.admin_api_key)}\n"
        )
        threading.Thread(
            target=self._run_test_remote_connection,
            args=(remote_config,),
            daemon=True,
        ).start()

    def _run_test_remote_connection(self, remote_config):
        """在后台线程中执行远程连接测试。"""

        try:
            result = test_sub2api_connection(remote_config)
            self.convert_queue.put(("remote_done", "test", result))
        except Exception as exc:  # noqa: BLE001
            self.convert_queue.put(("remote_error", "test", str(exc)))

    def start_remote_import(self):
        """复用缓存结果一键导入远程 Sub2API。"""

        if not self.ensure_cached_result_available():
            return
        try:
            remote_config = self.build_remote_import_config()
        except ValueError as exc:
            messagebox.showerror("错误", str(exc))
            return
        self.set_running(True)
        self.status_var.set("导入 Sub2API 中...")
        self.log.write(
            "开始一键导入 Sub2API: "
            f"{remote_config.base_url} | key {mask_secret_value(remote_config.admin_api_key)}\n"
        )
        threading.Thread(
            target=self._run_remote_import,
            args=(remote_config, self.cached_payload_text),
            daemon=True,
        ).start()

    def start_remote_import_from_file(self):
        """直接选择本地 JSON 文件并上传到远程 Sub2API。"""

        try:
            remote_config = self.build_remote_import_config()
        except ValueError as exc:
            messagebox.showerror("错误", str(exc))
            return
        file_path = filedialog.askopenfilename(
            title="选择要上传到 Sub2API 的 JSON 文件",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
        )
        if not file_path:
            return
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                payload_text = handle.read()
        except OSError as exc:
            messagebox.showerror("错误", f"读取 JSON 文件失败：{exc}")
            return

        self.set_running(True)
        self.status_var.set("上传本地 JSON 到 Sub2API 中...")
        self.log.write(
            "开始上传本地 JSON 到 Sub2API: "
            f"{file_path} | {remote_config.base_url} | key {mask_secret_value(remote_config.admin_api_key)}\n"
        )
        threading.Thread(
            target=self._run_remote_import,
            args=(remote_config, payload_text),
            daemon=True,
        ).start()

    def _run_remote_import(self, remote_config, payload_text):
        """在后台线程中执行一键导入。"""

        try:
            result = import_to_sub2api_codex_session(remote_config, payload_text)
            self.convert_queue.put(("remote_done", "import", result))
        except Exception as exc:  # noqa: BLE001
            self.convert_queue.put(("remote_error", "import", str(exc)))

    def start_remote_scan(self, announce=True):
        """刷新远程账号活号、死号和平均额度统计。"""

        try:
            remote_config = self.build_remote_import_config()
        except ValueError as exc:
            messagebox.showerror("错误", str(exc))
            return
        self.set_running(True)
        self.status_var.set("刷新远程账号状态中...")
        self.log.write(
            "开始刷新远程账号状态: "
            f"{remote_config.base_url} | key {mask_secret_value(remote_config.admin_api_key)}\n"
        )
        threading.Thread(
            target=self._run_remote_scan,
            args=(remote_config, announce),
            daemon=True,
        ).start()

    def _run_remote_scan(self, remote_config, announce):
        """在后台线程中拉取远程账号并执行活死统计。"""

        try:
            result = scan_remote_accounts(remote_config)
            action_name = "scan" if announce else "scan_quiet"
            self.convert_queue.put(("remote_done", action_name, result))
        except Exception as exc:  # noqa: BLE001
            action_name = "scan" if announce else "scan_quiet"
            self.convert_queue.put(("remote_error", action_name, str(exc)))

    def get_github_update_context_file(self):
        """返回 GitHub 版本检查使用的本地入口文件。"""

        return getattr(self, "update_context_file", __file__)

    def start_check_github_update(self):
        """异步检查 GitHub 是否有新版本。"""

        self.set_running(True)
        self.status_var.set("检查 GitHub 更新中...")
        self.log.write("开始检查 GitHub 最新版本...\n")
        threading.Thread(
            target=self._run_check_github_update,
            args=(self.get_github_update_context_file(),),
            daemon=True,
        ).start()

    def _run_check_github_update(self, module_file):
        """后台检查 GitHub 更新。"""

        try:
            result = build_github_update_check_result(module_file)
            self.convert_queue.put(("remote_done", "github_check", result))
        except Exception as exc:  # noqa: BLE001
            self.convert_queue.put(("remote_error", "github_check", str(exc)))

    def start_apply_github_update(self):
        """异步执行一键更新。"""

        self.set_running(True)
        self.status_var.set("准备一键更新中...")
        self.log.write("开始执行 GitHub 一键更新...\n")
        threading.Thread(
            target=self._run_apply_github_update,
            args=(self.get_github_update_context_file(),),
            daemon=True,
        ).start()

    def _run_apply_github_update(self, module_file):
        """后台下载更新包并准备替换。"""

        try:
            result = prepare_github_update(module_file)
            self.convert_queue.put(("remote_done", "github_apply", result))
        except Exception as exc:  # noqa: BLE001
            self.convert_queue.put(("remote_error", "github_apply", str(exc)))

    def start_set_all_remote_account_privacy(self):
        """异步拉取远程账号并逐个设置隐私。"""

        try:
            remote_config = self.build_remote_import_config()
        except ValueError as exc:
            messagebox.showerror("错误", str(exc))
            return
        self.set_running(True)
        self.status_var.set("批量设置远程账号隐私中...")
        self.log.write(
            "开始批量设置远程账号隐私: "
            f"{remote_config.base_url} | key {mask_secret_value(remote_config.admin_api_key)}\n"
        )
        threading.Thread(
            target=self._run_set_all_remote_account_privacy,
            args=(remote_config,),
            daemon=True,
        ).start()

    def _run_set_all_remote_account_privacy(self, remote_config):
        """在后台线程中执行远程账号隐私设置。"""

        try:
            result = set_all_remote_openai_account_privacy(remote_config)
            self.convert_queue.put(("remote_done", "privacy", result))
        except Exception as exc:  # noqa: BLE001
            self.convert_queue.put(("remote_error", "privacy", str(exc)))

    def update_remote_stats_ui(self, summary):
        """把远程账号统计结果刷新到界面中。"""

        self.remote_total_var.set(str(summary.get("total_count", 0)))
        self.remote_alive_var.set(str(summary.get("alive_count", 0)))
        self.remote_dead_var.set(str(summary.get("dead_count", 0)))
        self.remote_no_quota_var.set(str(summary.get("no_quota_count", 0)))
        self.remote_average_var.set(
            f"{summary.get('average_remaining_quota', 0.0):.2f}%"
        )
        self.remote_today_tokens_var.set(
            self.format_remote_token_count(summary.get("today_tokens"))
        )
        self.remote_last_hour_tokens_var.set(
            self.format_remote_token_count(summary.get("last_hour_tokens"))
        )
        self.remote_previous_hour_tokens_var.set(
            self.format_remote_token_count(summary.get("previous_hour_tokens"))
        )

    def get_remote_no_quota_items(self):
        """返回最近一次扫描里无可用额度的远程账号。"""

        if not self.cached_remote_scan_summary:
            return []
        return select_remote_accounts_without_quota(
            self.cached_remote_scan_summary.get("no_quota_items")
            or self.cached_remote_scan_summary.get("dead_items")
            or []
        )

    def get_remote_auth_error_items(self):
        """返回最近一次扫描里 401 认证失效的远程账号。"""

        if not self.cached_remote_scan_summary:
            return []
        return select_remote_accounts_with_auth_error(
            self.cached_remote_scan_summary.get("dead_items") or []
        )

    def start_delete_no_quota_remote_accounts(self):
        """删除上一轮远程扫描中无可用额度的账号。"""

        if not self.cached_remote_scan_summary:
            messagebox.showerror("错误", "请先点击“刷新远程账号状态”")
            return
        no_quota_items = self.get_remote_no_quota_items()
        if not no_quota_items:
            messagebox.showinfo("提示", "当前没有可删除的无额度账号")
            return
        if not messagebox.askyesno(
            "确认删除无额度账号",
            f"即将删除 {len(no_quota_items)} 个无可用额度账号，此操作不可撤销，是否继续？",
        ):
            return
        try:
            remote_config = self.build_remote_import_config()
        except ValueError as exc:
            messagebox.showerror("错误", str(exc))
            return
        self.set_running(True)
        self.status_var.set("删除无额度账号中...")
        self.log.write(f"开始删除无额度账号，共 {len(no_quota_items)} 个\n")
        threading.Thread(
            target=self._run_delete_no_quota_remote_accounts,
            args=(remote_config, no_quota_items),
            daemon=True,
        ).start()

    def _run_delete_no_quota_remote_accounts(self, remote_config, no_quota_items):
        """在后台线程中批量删除无额度账号。"""

        try:
            result = delete_dead_remote_accounts(remote_config, no_quota_items)
            self.convert_queue.put(("remote_done", "delete_no_quota", result))
        except Exception as exc:  # noqa: BLE001
            self.convert_queue.put(("remote_error", "delete_no_quota", str(exc)))

    def start_delete_auth_error_remote_accounts(self):
        """删除上一轮远程扫描中 401 认证失效的账号。"""

        if not self.cached_remote_scan_summary:
            messagebox.showerror("错误", "请先点击“刷新远程账号状态”")
            return
        auth_error_items = self.get_remote_auth_error_items()
        if not auth_error_items:
            messagebox.showinfo("提示", "当前没有可删除的 401 错误账号")
            return
        if not messagebox.askyesno(
            "确认删除401错误账号",
            f"即将删除 {len(auth_error_items)} 个 401 认证失效账号，此操作不可撤销，是否继续？",
        ):
            return
        try:
            remote_config = self.build_remote_import_config()
        except ValueError as exc:
            messagebox.showerror("错误", str(exc))
            return
        self.set_running(True)
        self.status_var.set("删除401错误账号中...")
        self.log.write(f"开始删除401错误账号，共 {len(auth_error_items)} 个\n")
        threading.Thread(
            target=self._run_delete_auth_error_remote_accounts,
            args=(remote_config, auth_error_items),
            daemon=True,
        ).start()

    def _run_delete_auth_error_remote_accounts(self, remote_config, auth_error_items):
        """在后台线程中批量删除 401 认证失效账号。"""

        try:
            result = delete_dead_remote_accounts(remote_config, auth_error_items)
            self.convert_queue.put(("remote_done", "delete_auth_error", result))
        except Exception as exc:  # noqa: BLE001
            self.convert_queue.put(("remote_error", "delete_auth_error", str(exc)))

    def start_delete_dead_remote_accounts(self):
        """删除上一轮远程扫描中识别出的死号。"""

        if not self.cached_remote_scan_summary:
            messagebox.showerror("错误", "请先点击“刷新远程账号状态”")
            return
        dead_items = self.cached_remote_scan_summary.get("dead_items") or []
        if not dead_items:
            messagebox.showinfo("提示", "当前没有可删除的死号")
            return
        if not messagebox.askyesno(
            "确认删除死号",
            f"即将删除 {len(dead_items)} 个远程死号，此操作不可撤销，是否继续？",
        ):
            return
        try:
            remote_config = self.build_remote_import_config()
        except ValueError as exc:
            messagebox.showerror("错误", str(exc))
            return
        self.set_running(True)
        self.status_var.set("删除远程死号中...")
        self.log.write(f"开始删除远程死号，共 {len(dead_items)} 个\n")
        threading.Thread(
            target=self._run_delete_dead_remote_accounts,
            args=(remote_config, dead_items),
            daemon=True,
        ).start()

    def _run_delete_dead_remote_accounts(self, remote_config, dead_items):
        """在后台线程中批量删除远程死号。"""

        try:
            result = delete_dead_remote_accounts(remote_config, dead_items)
            self.convert_queue.put(("remote_done", "delete", result))
        except Exception as exc:  # noqa: BLE001
            self.convert_queue.put(("remote_error", "delete", str(exc)))

    def handle_remote_done_message(self, action_name, result):
        """处理远程动作成功结果。"""

        self.set_running(False)
        if action_name == "github_check":
            self.cached_github_update_result = result
            self.update_remote_buttons_state()
            latest_label = result.latest_version_label
            latest_time = result.latest_published_at_display
            if result.update_available:
                self.status_var.set(f"发现新版本 {latest_label}")
                self.log.write(
                    "[GITHUB][UPDATE][FOUND] "
                    f"repo={result.repo} current={result.current_version_label} "
                    f"latest={latest_label} published={latest_time} "
                    f"auto={result.can_auto_update}\n"
                )
                messagebox.showinfo(
                    "发现新版本",
                    "\n".join(
                        [
                            f"仓库：{result.repo}",
                            f"当前：{result.current_version_label} | {result.current_modified_at_display}",
                            f"最新：{latest_label} | {latest_time}",
                            (
                                "支持一键更新：是"
                                if result.can_auto_update
                                else "支持一键更新：否（会打开 GitHub 页面）"
                            ),
                        ]
                    ),
                )
            else:
                self.status_var.set("当前已是最新版本")
                self.log.write(
                    "[GITHUB][UPDATE][LATEST] "
                    f"repo={result.repo} current={result.current_version_label} "
                    f"latest={latest_label} published={latest_time}\n"
                )
                messagebox.showinfo(
                    "已是最新版本",
                    "\n".join(
                        [
                            f"仓库：{result.repo}",
                            f"当前：{result.current_version_label} | {result.current_modified_at_display}",
                            f"最新：{latest_label} | {latest_time}",
                        ]
                    ),
                )
            return

        if action_name == "github_apply":
            check = result.get("check") or {}
            self.cached_github_update_result = check or self.cached_github_update_result
            status = str(result.get("status") or "").strip()
            if status == "up_to_date":
                self.status_var.set("当前已是最新版本")
                self.log.write("[GITHUB][UPDATE][SKIP] 当前已是最新版本，无需更新\n")
                messagebox.showinfo("无需更新", "当前已经是最新版本。")
                return
            if status == "open_browser":
                latest_url = str(check.get("latest_url") or "").strip()
                if latest_url:
                    webbrowser.open(latest_url)
                self.status_var.set("仓库暂无可自动更新包，已打开 GitHub 页面")
                self.log.write(
                    "[GITHUB][UPDATE][OPEN_BROWSER] "
                    f"url={latest_url or '--'}\n"
                )
                messagebox.showinfo(
                    "已打开 GitHub 页面",
                    "当前仓库还没有可自动替换的 Release exe，已帮你打开项目页面。",
                )
                return
            if status == "scheduled":
                downloaded_path = str(result.get("downloaded_path") or "").strip()
                script_path = str(result.get("script_path") or "").strip()
                asset_name = str(check.get("preferred_asset_name") or "").strip()
                self.status_var.set("更新包已下载，程序即将退出并自动完成更新")
                self.log.write(
                    "[GITHUB][UPDATE][SCHEDULED] "
                    f"asset={asset_name or '--'} "
                    f"downloaded={downloaded_path or '--'} "
                    f"script={script_path or '--'}\n"
                )
                messagebox.showinfo(
                    "开始更新",
                    "更新包已下载完成。\n程序现在会退出，并在退出后自动替换为新版本。",
                )
                self.root.after(200, self.root.destroy)
                return

        if action_name == "test":
            self.status_var.set("远程连接测试成功")
            self.log.write(
                "Sub2API 连接测试成功: "
                f"{result['url']} | 账号总数 {result.get('account_total', '未知')}\n"
            )
            messagebox.showinfo(
                "连接测试成功",
                "Sub2API 管理接口可访问。\n"
                f"地址：{result['url']}\n"
                f"账号总数：{result.get('account_total', '未知')}",
            )
            return

        if action_name in {"scan", "scan_quiet"}:
            self.cached_remote_scan_summary = result
            self.update_remote_stats_ui(result)
            self.update_remote_buttons_state()
            self.status_var.set(
                "远程状态已刷新 "
                f"活号{result['alive_count']} "
                f"死号{result['dead_count']} "
                f"无额度{result.get('no_quota_count', 0)}"
            )
            self.log.write(
                "远程账号状态刷新完成: "
                f"total={result['total_count']} alive={result['alive_count']} "
                f"dead={result['dead_count']} "
                f"no_quota={result.get('no_quota_count', 0)} "
                f"today_tokens={result.get('today_tokens')} "
                f"last_hour_tokens={result.get('last_hour_tokens')} "
                f"previous_hour_tokens={result.get('previous_hour_tokens')} "
                f"avg={result['average_remaining_quota']:.2f}%\n"
            )
            for item in result["dead_items"]:
                self.log.write(
                    f"[REMOTE][DEAD] {item['name']} | {item['email']} | {item['reason']}\n"
                )
            for item in result.get("no_quota_items") or []:
                self.log.write(
                    f"[REMOTE][NO_QUOTA] {item['name']} | {item['email']} | {item['reason']}\n"
                )
            if result.get("token_stats_error"):
                self.log.write(
                    f"[REMOTE][TOKEN_STATS][WARN] {result['token_stats_error']}\n"
                )
            if result["unmatched_names"]:
                self.log.write(
                    "远程导出与列表未完全匹配，已跳过: "
                    f"{', '.join(result['unmatched_names'][:10])}\n"
                )
            if action_name == "scan":
                messagebox.showinfo(
                    "远程账号状态已刷新",
                    "\n".join(
                        [
                            f"远程总账号：{result['total_count']}",
                            f"活号：{result['alive_count']}",
                            f"死号：{result['dead_count']}",
                            f"无额度：{result.get('no_quota_count', 0)}",
                            f"今日 Token：{self.format_remote_token_count(result.get('today_tokens'))}",
                            f"上一小时 Token：{self.format_remote_token_count(result.get('last_hour_tokens'))}",
                            f"上上小时 Token：{self.format_remote_token_count(result.get('previous_hour_tokens'))}",
                            f"活号平均额度：{result['average_remaining_quota']:.2f}%",
                        ]
                    ),
                )
            return

        if action_name == "delete":
            self.status_var.set(
                f"删除死号完成 成功{result['deleted']} 失败{result['failed']}"
            )
            self.log.write(
                f"远程死号删除完成: deleted={result['deleted']} failed={result['failed']}\n"
            )
            for item in result["items"]:
                if item["success"]:
                    self.log.write(
                        f"[REMOTE][DELETE][OK] {item['account_id']} {item['name']}\n"
                    )
                else:
                    self.log.write(
                        f"[REMOTE][DELETE][FAIL] {item['account_id']} {item['name']} | {item['error']}\n"
                    )
            messagebox.showinfo(
                "删除死号完成",
                f"成功删除 {result['deleted']} 个，失败 {result['failed']} 个。",
            )
            self.start_remote_scan(announce=False)
            return

        if action_name == "delete_no_quota":
            self.status_var.set(
                f"删除无额度账号完成 成功{result['deleted']} 失败{result['failed']}"
            )
            self.log.write(
                f"无额度账号删除完成: deleted={result['deleted']} failed={result['failed']}\n"
            )
            for item in result["items"]:
                if item["success"]:
                    self.log.write(
                        f"[REMOTE][DELETE][NO_QUOTA][OK] {item['account_id']} {item['name']}\n"
                    )
                else:
                    self.log.write(
                        f"[REMOTE][DELETE][NO_QUOTA][FAIL] {item['account_id']} {item['name']} | {item['error']}\n"
                    )
            messagebox.showinfo(
                "删除所有无额度完成",
                f"成功删除 {result['deleted']} 个，失败 {result['failed']} 个。",
            )
            self.start_remote_scan(announce=False)
            return

        if action_name == "delete_auth_error":
            self.status_var.set(
                f"删除401错误账号完成 成功{result['deleted']} 失败{result['failed']}"
            )
            self.log.write(
                f"401错误账号删除完成: deleted={result['deleted']} failed={result['failed']}\n"
            )
            for item in result["items"]:
                if item["success"]:
                    self.log.write(
                        f"[REMOTE][DELETE][401][OK] {item['account_id']} {item['name']}\n"
                    )
                else:
                    self.log.write(
                        f"[REMOTE][DELETE][401][FAIL] {item['account_id']} {item['name']} | {item['error']}\n"
                    )
            messagebox.showinfo(
                "删除401错误账号完成",
                f"成功删除 {result['deleted']} 个，失败 {result['failed']} 个。",
            )
            self.start_remote_scan(announce=False)
            return

        if action_name == "privacy":
            self.status_var.set(
                f"一键隐私完成 成功{result['success']} 失败{result['failed']}"
            )
            self.log.write(
                f"远程账号隐私设置完成: total={result['total']} success={result['success']} failed={result['failed']}\n"
            )
            for item in result["items"]:
                if item["success"]:
                    privacy_mode = item.get("privacy_mode") or "unknown"
                    self.log.write(
                        f"[REMOTE][PRIVACY][OK] {item['account_id']} {item['name']} | mode={privacy_mode}\n"
                    )
                else:
                    self.log.write(
                        f"[REMOTE][PRIVACY][FAIL] {item['account_id']} {item['name']} | {item['error']}\n"
                    )
            messagebox.showinfo(
                "一键隐私完成",
                "\n".join(
                    [
                        f"总账号数：{result['total']}",
                        f"成功：{result['success']}",
                        f"失败：{result['failed']}",
                    ]
                ),
            )
            self.start_remote_scan(announce=False)
            return

        self.status_var.set(
            f"导入完成 新增{result['created']} 更新{result['updated']} 复用{result.get('reused', 0)}"
        )
        self.log.write(
            "Sub2API 导入完成: "
            f"total={result['total']} created={result['created']} "
            f"updated={result['updated']} skipped={result['skipped']} "
            f"failed={result['failed']} reused={result.get('reused', 0)} "
            f"strategy={result.get('import_strategy', 'unknown')}\n"
        )
        if result.get("post_import_update"):
            post_update = result["post_import_update"]
            self.log.write(
                "Sub2API 导入后已自动套用 OpenAI 默认配置: "
                f"group_ids={result.get('applied_group_ids', [])} "
                f"concurrency={result.get('applied_concurrency')} "
                f"bulk_success={post_update['success']} bulk_failed={post_update['failed']}\n"
            )
        for item in result["items"]:
            self.log.write(
                f"[IMPORT][{item.get('action', 'unknown')}] "
                f"#{item.get('index', '?')} {item.get('name', '')} "
                f"{item.get('message', '')}\n"
            )
        for warning in result["warnings"]:
            self.log.write(
                f"[IMPORT][WARN] #{warning.get('index', '?')} "
                f"{warning.get('name', '')} {warning.get('message', '')}\n"
            )
        for error in result["errors"]:
            self.log.write(
                f"[IMPORT][ERROR] #{error.get('index', '?')} "
                f"{error.get('name', '')} {error.get('message', '')}\n"
            )
        messagebox.showinfo(
            "Sub2API 导入完成",
            "\n".join(
                [
                    f"目标地址：{result['url']}",
                    f"总条数：{result['total']}",
                    f"新增：{result['created']}",
                    f"更新：{result['updated']}",
                    f"复用已有：{result.get('reused', 0)}",
                    f"跳过：{result['skipped']}",
                    f"失败：{result['failed']}",
                    (
                        "导入策略：Sub 聚合原生导入"
                        if result.get("import_strategy") == "data"
                        else "导入策略：Codex Session 导入"
                    ),
                    "自动透传：开启",
                    "WS mode：透传（passthrough）",
                    f"并发：{result.get('applied_concurrency')}",
                    f"分组：{', '.join(str(item) for item in result.get('applied_group_ids', []))}",
                    "本次导入复用了缓存结果，没有重新跑转换。",
                ]
            ),
        )

    def handle_remote_error_message(self, action_name, error_message):
        """处理远程动作失败结果。"""

        self.set_running(False)
        self.status_var.set("远程操作失败")
        self.log.write(f"[REMOTE][{action_name.upper()}][ERROR] {error_message}\n")
        title_map = {
            "test": "连接测试失败",
            "scan": "远程状态刷新失败",
            "delete": "删除死号失败",
            "delete_auth_error": "删除401错误账号失败",
            "delete_no_quota": "删除所有无额度失败",
            "import": "导入失败",
            "privacy": "一键隐私失败",
            "github_check": "检查更新失败",
            "github_apply": "一键更新失败",
        }
        if action_name == "scan_quiet":
            return
        messagebox.showerror(title_map.get(action_name, "远程操作失败"), error_message)
