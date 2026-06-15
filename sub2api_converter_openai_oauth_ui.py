# -*- coding: utf-8 -*-
"""席位管理工具里的 Sub2API OpenAI OAuth 一键建号面板。"""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from sub2api_converter_remote import build_remote_config, fetch_remote_groups, parse_int_list_text
from sub2api_converter_remote_openai_oauth import (
    DEFAULT_OAUTH_GROUP_NAME,
    DEFAULT_OAUTH_PROXY_NAME,
    LocalOAuthCallbackListener,
    PendingOpenAIOAuthSession,
    complete_openai_oauth_account_creation,
    create_openai_oauth_pending_session,
    fetch_remote_proxies,
    generate_random_oauth_account_name,
    launch_private_auth_browser,
    load_openai_oauth_defaults,
    normalize_oauth_concurrency,
)


class OpenAIOAuthAccountPanel:
    """承载 Sub2API OpenAI OAuth 一键授权建号交互。"""

    def __init__(self, parent, on_account_created=None):
        self.parent = parent
        self.on_account_created = on_account_created
        self._auth_completion_running = False
        self._resource_loading = False
        self._browser_process = None
        self._callback_listener = None
        self._pending_remote_config = None
        self._pending_session: PendingOpenAIOAuthSession | None = None
        self._proxy_options: list[dict] = []
        self._group_options: list[dict] = []
        self._oauth_defaults = load_openai_oauth_defaults()

        frame = ttk.LabelFrame(parent, text="Sub2API 一键授权建号", padding=6)
        frame.pack(fill="x", pady=(8, 0))
        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(3, weight=1)

        self.base_url_var = tk.StringVar(value=self._oauth_defaults["base_url"])
        self.api_key_var = tk.StringVar(value=self._oauth_defaults["admin_api_key"])
        self.redirect_uri_var = tk.StringVar(value=self._oauth_defaults["redirect_uri"])
        self.account_name_var = tk.StringVar(value=generate_random_oauth_account_name())
        self.proxy_choice_var = tk.StringVar(value="不使用代理")
        self.group_choice_var = tk.StringVar(value="不绑定分组")
        self.manual_proxy_url_var = tk.StringVar(value=self._oauth_defaults["proxy_url"])
        self.concurrency_var = tk.StringVar(value=self._oauth_defaults["concurrency"])
        self.auth_url_var = tk.StringVar()
        self.auth_input_var = tk.StringVar()
        self.status_var = tk.StringVar(value="就绪，先点“生成授权并打开隐私浏览器”")

        self._create_entry(frame, 0, 0, "服务器地址", self.base_url_var)
        self._create_entry(frame, 0, 2, "管理员 API Key", self.api_key_var, show="*")
        self._create_entry(frame, 1, 0, "回调地址", self.redirect_uri_var)
        self._create_entry(frame, 1, 2, "随机账号名", self.account_name_var)

        ttk.Label(frame, text="远程代理").grid(row=2, column=0, sticky="w", pady=(0, 6))
        self.proxy_combo = ttk.Combobox(
            frame,
            textvariable=self.proxy_choice_var,
            state="readonly",
            values=["不使用代理"],
        )
        self.proxy_combo.grid(row=2, column=1, sticky="ew", pady=(0, 6))

        ttk.Label(frame, text="远程分组").grid(row=2, column=2, sticky="w", padx=(12, 8), pady=(0, 6))
        self.group_combo = ttk.Combobox(
            frame,
            textvariable=self.group_choice_var,
            state="readonly",
            values=["不绑定分组"],
        )
        self.group_combo.grid(row=2, column=3, sticky="ew", pady=(0, 6))

        self._create_entry(frame, 3, 0, "备用代理 URL", self.manual_proxy_url_var)
        self._create_entry(frame, 3, 2, "并发", self.concurrency_var)

        note_text = (
            "固定配置：平台 openai | 类型 oauth | 状态启用 | 自动透传开启 | "
            "WS mode=passthrough | 仅允许 Codex 官方客户端。\n"
            "代理优先使用下拉选择；若远程还没有代理，也可留空不使用，或在“备用代理 URL”里手填。\n"
            "分组默认按 .env 回填并自动尝试匹配；浏览器只会关闭本工具上一次启动的授权窗口。"
        )
        ttk.Label(
            frame,
            text=note_text,
            justify="left",
            wraplength=860,
        ).grid(row=4, column=0, columnspan=4, sticky="w", pady=(0, 6))

        button_row = ttk.Frame(frame)
        button_row.grid(row=5, column=0, columnspan=4, sticky="w", pady=(0, 6))
        self.reload_env_btn = ttk.Button(
            button_row,
            text="读取 .env",
            command=self._reload_remote_defaults,
        )
        self.reload_env_btn.pack(side="left", padx=(0, 8))
        self.reload_resources_btn = ttk.Button(
            button_row,
            text="刷新代理/分组",
            command=self.start_load_remote_resources,
        )
        self.reload_resources_btn.pack(side="left", padx=(0, 8))
        ttk.Button(button_row, text="重新随机", command=self._reroll_account_name).pack(
            side="left", padx=(0, 8)
        )
        self.start_auth_btn = ttk.Button(
            button_row,
            text="生成授权并打开隐私浏览器",
            command=self.start_create_auth_session,
        )
        self.start_auth_btn.pack(side="left", padx=(0, 8))
        self.copy_auth_btn = ttk.Button(
            button_row,
            text="复制授权链接",
            command=self._copy_auth_url,
            state="disabled",
        )
        self.copy_auth_btn.pack(side="left")

        self._create_entry(
            frame,
            6,
            0,
            "授权链接",
            self.auth_url_var,
            entry_state="readonly",
            columnspan=3,
        )

        ttk.Label(
            frame,
            text=(
                "默认会自动接收 localhost 回调并继续建号。\n"
                "如果自动接收失败，再手动复制完整回调链接或只复制 code 参数值。"
            ),
            justify="left",
            wraplength=860,
        ).grid(row=7, column=0, columnspan=4, sticky="w", pady=(0, 4))

        self._create_entry(
            frame,
            8,
            0,
            "授权链接或 Code",
            self.auth_input_var,
            columnspan=2,
        )

        self.finish_auth_btn = ttk.Button(
            frame,
            text="完成授权并创建账号",
            command=self.start_complete_auth,
            state="disabled",
        )
        self.finish_auth_btn.grid(row=8, column=3, sticky="w", pady=(0, 6))

        ttk.Label(frame, textvariable=self.status_var, foreground="#1d4ed8").grid(
            row=9, column=0, columnspan=4, sticky="w"
        )

        self._reset_resource_options()
        if self.base_url_var.get().strip() and self.api_key_var.get().strip():
            self.parent.after(150, self.start_load_remote_resources)

    def _create_entry(
        self,
        parent,
        row,
        column,
        label_text,
        variable,
        show="",
        entry_state="normal",
        columnspan=1,
    ):
        ttk.Label(parent, text=label_text).grid(
            row=row,
            column=column,
            sticky="w",
            padx=(0 if column == 0 else 12, 8),
            pady=(0, 6),
        )
        entry = ttk.Entry(parent, textvariable=variable, show=show, state=entry_state)
        entry.grid(
            row=row,
            column=column + 1,
            columnspan=columnspan,
            sticky="ew",
            pady=(0, 6),
        )

    def _set_busy(self, busy: bool):
        state = "disabled" if busy else "normal"
        combo_state = "disabled" if busy else "readonly"
        self.reload_env_btn.configure(state=state)
        self.reload_resources_btn.configure(state=("disabled" if busy or self._resource_loading else "normal"))
        self.start_auth_btn.configure(state=state)
        self.finish_auth_btn.configure(
            state=("disabled" if busy or not self._pending_session else "normal")
        )
        self.copy_auth_btn.configure(
            state=("normal" if (not busy and self.auth_url_var.get().strip()) else "disabled")
        )
        self.proxy_combo.configure(state=combo_state)
        self.group_combo.configure(state=combo_state)

    def _reset_resource_options(self):
        self._proxy_options = [{"label": "不使用代理", "id": None}]
        self._group_options = [{"label": "不绑定分组", "id": None}]
        self.proxy_combo.configure(values=[item["label"] for item in self._proxy_options])
        self.group_combo.configure(values=[item["label"] for item in self._group_options])
        self.proxy_choice_var.set(self._proxy_options[0]["label"])
        self.group_choice_var.set(self._group_options[0]["label"])

    def _reroll_account_name(self):
        self.account_name_var.set(generate_random_oauth_account_name())

    def _reload_remote_defaults(self):
        self._oauth_defaults = load_openai_oauth_defaults()
        self.base_url_var.set(self._oauth_defaults["base_url"])
        self.api_key_var.set(self._oauth_defaults["admin_api_key"])
        self.redirect_uri_var.set(self._oauth_defaults["redirect_uri"])
        self.manual_proxy_url_var.set(self._oauth_defaults["proxy_url"])
        self.concurrency_var.set(self._oauth_defaults["concurrency"])
        self.status_var.set("已从 .env 回填远程配置")
        self.start_load_remote_resources()

    def _copy_auth_url(self):
        auth_url = self.auth_url_var.get().strip()
        if not auth_url:
            return
        self.parent.clipboard_clear()
        self.parent.clipboard_append(auth_url)
        self.parent.update()
        self.status_var.set("授权链接已复制")

    def _build_proxy_label(self, item: dict) -> str:
        proxy_id = item.get("id")
        name = str(item.get("name", "")).strip() or DEFAULT_OAUTH_PROXY_NAME
        protocol = str(item.get("protocol", "")).strip().lower()
        host = str(item.get("host", "")).strip()
        port = str(item.get("port", "")).strip()
        location = f"{protocol}://{host}:{port}" if protocol and host and port else "地址未知"
        return f"{name} (#{proxy_id} | {location})"

    def _build_group_label(self, item: dict) -> str:
        group_id = item.get("id")
        name = str(item.get("name", "")).strip() or f"group-{group_id}"
        platform = str(item.get("platform", "")).strip().lower() or "-"
        return f"{name} (#{group_id} | {platform})"

    def _parse_default_group_ids(self) -> list[int]:
        try:
            return parse_int_list_text(self._oauth_defaults.get("group_ids", ""))
        except Exception:
            return []

    def _apply_resource_defaults(self):
        preferred_proxy_id = self._oauth_defaults.get("proxy_id", "").strip()
        preferred_proxy_name = (
            self._oauth_defaults.get("proxy_name", "").strip() or DEFAULT_OAUTH_PROXY_NAME
        )
        selected_proxy_label = self._proxy_options[0]["label"]
        if preferred_proxy_id:
            for item in self._proxy_options:
                if str(item.get("id")) == preferred_proxy_id:
                    selected_proxy_label = item["label"]
                    break
        elif self.manual_proxy_url_var.get().strip():
            for item in self._proxy_options:
                if preferred_proxy_name and item["label"].startswith(preferred_proxy_name):
                    selected_proxy_label = item["label"]
                    break
        self.proxy_choice_var.set(selected_proxy_label)

        preferred_group_ids = self._parse_default_group_ids()
        preferred_group_name = (
            self._oauth_defaults.get("group_name", "").strip() or DEFAULT_OAUTH_GROUP_NAME
        )
        selected_group_label = self._group_options[0]["label"]
        if preferred_group_ids:
            target_group_id = preferred_group_ids[0]
            for item in self._group_options:
                if item.get("id") == target_group_id:
                    selected_group_label = item["label"]
                    break
        elif preferred_group_name:
            target_name = preferred_group_name.lower()
            for item in self._group_options:
                if str(item.get("name", "")).strip().lower() == target_name:
                    selected_group_label = item["label"]
                    break
        self.group_choice_var.set(selected_group_label)

    def start_load_remote_resources(self):
        if self._resource_loading:
            return
        base_url = self.base_url_var.get().strip()
        api_key = self.api_key_var.get().strip()
        if not base_url or not api_key:
            self.status_var.set("请先填写远程服务器地址和管理员 API Key")
            return
        self._resource_loading = True
        self.reload_resources_btn.configure(state="disabled")
        self.status_var.set("正在读取远程代理和分组...")
        threading.Thread(
            target=self._run_load_remote_resources,
            args=(base_url, api_key),
            daemon=True,
        ).start()

    def _run_load_remote_resources(self, base_url: str, api_key: str):
        try:
            config = build_remote_config(
                base_url=base_url,
                admin_api_key=api_key,
            )
            proxies = fetch_remote_proxies(config)
            groups = fetch_remote_groups(config)
            self.parent.after(
                0,
                lambda: self._on_remote_resources_loaded(proxies, groups),
            )
        except Exception as exc:  # noqa: BLE001
            self.parent.after(0, lambda e=str(exc): self._on_remote_resources_error(e))

    def _on_remote_resources_loaded(self, proxies: list[dict], groups: list[dict]):
        self._resource_loading = False
        proxy_options = [{"label": "不使用代理", "id": None}]
        for item in proxies:
            if not isinstance(item, dict):
                continue
            try:
                proxy_id = int(item.get("id", 0) or 0)
            except (TypeError, ValueError):
                proxy_id = 0
            if proxy_id <= 0:
                continue
            proxy_options.append(
                {
                    "label": self._build_proxy_label(item),
                    "id": proxy_id,
                    "name": str(item.get("name", "")).strip(),
                }
            )
        group_options = [{"label": "不绑定分组", "id": None, "name": ""}]
        for item in groups:
            if not isinstance(item, dict):
                continue
            try:
                group_id = int(item.get("id", 0) or 0)
            except (TypeError, ValueError):
                group_id = 0
            if group_id <= 0:
                continue
            platform = str(item.get("platform", "")).strip().lower()
            if platform and platform != "openai":
                continue
            group_options.append(
                {
                    "label": self._build_group_label(item),
                    "id": group_id,
                    "name": str(item.get("name", "")).strip(),
                }
            )
        self._proxy_options = proxy_options
        self._group_options = group_options
        self.proxy_combo.configure(values=[item["label"] for item in self._proxy_options])
        self.group_combo.configure(values=[item["label"] for item in self._group_options])
        self._apply_resource_defaults()
        self.reload_resources_btn.configure(state="normal")
        self.status_var.set(
            f"远程资源已刷新：代理 {max(0, len(self._proxy_options) - 1)} 个，分组 {max(0, len(self._group_options) - 1)} 个"
        )

    def _on_remote_resources_error(self, error_message: str):
        self._resource_loading = False
        self.reload_resources_btn.configure(state="normal")
        self.status_var.set("读取远程代理/分组失败")
        messagebox.showerror("读取远程代理/分组失败", error_message)

    def _get_selected_proxy_id(self) -> int | None:
        selected_label = self.proxy_choice_var.get().strip()
        for item in self._proxy_options:
            if item["label"] == selected_label:
                return item.get("id")
        return None

    def _get_selected_group_ids(self) -> list[int]:
        selected_label = self.group_choice_var.get().strip()
        for item in self._group_options:
            if item["label"] == selected_label and item.get("id"):
                return [int(item["id"])]
        return []

    def start_create_auth_session(self):
        base_url = self.base_url_var.get().strip()
        api_key = self.api_key_var.get().strip()
        if not base_url or not api_key:
            messagebox.showerror("错误", "请先填写远程服务器地址和管理员 API Key")
            return
        selected_proxy_id = self._get_selected_proxy_id()
        selected_group_ids = self._get_selected_group_ids()
        manual_proxy_url = self.manual_proxy_url_var.get().strip()
        redirect_uri = self.redirect_uri_var.get().strip()
        account_name = self.account_name_var.get().strip()
        concurrency = normalize_oauth_concurrency(self.concurrency_var.get().strip())
        self._set_busy(True)
        self._stop_callback_listener()
        self.status_var.set("正在生成授权链接，并准备启动本地回调监听...")
        threading.Thread(
            target=self._run_create_auth_session,
            args=(
                base_url,
                api_key,
                selected_proxy_id,
                manual_proxy_url,
                redirect_uri,
                account_name,
                selected_group_ids,
                concurrency,
            ),
            daemon=True,
        ).start()

    def _run_create_auth_session(
        self,
        base_url: str,
        api_key: str,
        selected_proxy_id: int | None,
        manual_proxy_url: str,
        redirect_uri: str,
        account_name: str,
        selected_group_ids: list[int],
        concurrency: int,
    ):
        try:
            result = create_openai_oauth_pending_session(
                base_url=base_url,
                admin_api_key=api_key,
                proxy_id=selected_proxy_id,
                proxy_url=("" if selected_proxy_id else manual_proxy_url),
                proxy_name=self._oauth_defaults.get("proxy_name", "").strip() or DEFAULT_OAUTH_PROXY_NAME,
                redirect_uri=redirect_uri,
                account_name=account_name,
                group_ids=selected_group_ids,
                group_name=self._oauth_defaults.get("group_name", "").strip() or DEFAULT_OAUTH_GROUP_NAME,
                concurrency=concurrency,
            )
            self.parent.after(0, lambda r=result: self._on_auth_session_created(r))
        except Exception as exc:  # noqa: BLE001
            self.parent.after(0, lambda e=str(exc): self._on_auth_session_error(e))

    def _on_auth_session_created(self, result):
        self._pending_remote_config = result["remote_config"]
        self._pending_session = result["pending_session"]
        self.auth_url_var.set(self._pending_session.auth_url)
        self.account_name_var.set(self._pending_session.account_name)
        self.finish_auth_btn.configure(state="normal")
        self.copy_auth_btn.configure(state="normal")
        listener_started = self._start_callback_listener()
        browser_result = launch_private_auth_browser(
            self._pending_session.auth_url,
            self._browser_process,
        )
        self._browser_process = browser_result.get("process")
        browser_name = browser_result.get("browser_name") or "浏览器"
        if browser_result.get("opened"):
            if listener_started:
                self.status_var.set(
                    f"授权链接已生成，已用 {browser_name} 隐私窗口打开，正在等待 localhost 自动回调。"
                )
            else:
                self.status_var.set(
                    f"授权链接已生成，已用 {browser_name} 隐私窗口打开。自动接收不可用时请手动粘贴链接或 code。"
                )
        else:
            if listener_started:
                self.status_var.set(
                    "授权链接已生成，未自动打开浏览器；你手动打开后，程序仍会自动等待 localhost 回调。"
                )
            else:
                self.status_var.set("授权链接已生成，但未自动打开浏览器，请手动复制链接打开。")
        self._set_busy(False)

    def _on_auth_session_error(self, error_message: str):
        self._set_busy(False)
        self.status_var.set("生成授权链接失败")
        messagebox.showerror("生成授权失败", error_message)

    def start_complete_auth(self):
        if not self._pending_session or not self._pending_remote_config:
            messagebox.showerror("错误", "请先点击“生成授权并打开隐私浏览器”")
            return
        auth_input = self.auth_input_var.get().strip()
        if not auth_input:
            messagebox.showerror("错误", "请粘贴完整授权链接或 code")
            return
        self._begin_complete_auth(auth_input, from_auto_callback=False)

    def _begin_complete_auth(self, auth_input: str, *, from_auto_callback: bool):
        """开始执行 OAuth 建号完成动作。"""

        if not self._pending_session or not self._pending_remote_config:
            return
        if self._auth_completion_running:
            return
        self._auth_completion_running = True
        self._set_busy(True)
        if from_auto_callback:
            self.status_var.set("已自动接收到 localhost 回调，正在创建 Sub2API 账号...")
        else:
            self.status_var.set("正在完成授权并创建 Sub2API 账号...")
        threading.Thread(
            target=self._run_complete_auth,
            args=(auth_input,),
            daemon=True,
        ).start()

    def _run_complete_auth(self, auth_input: str):
        """在后台线程中完成 OAuth 建号。"""

        try:
            result = complete_openai_oauth_account_creation(
                remote_config=self._pending_remote_config,
                pending_session=self._pending_session,
                auth_input=auth_input,
            )
            if callable(self.on_account_created):
                try:
                    result["after_create_result"] = self.on_account_created(result)
                except Exception as exc:  # noqa: BLE001
                    result["after_create_error"] = str(exc)
            self.parent.after(0, lambda r=result: self._on_complete_auth_done(r))
        except Exception as exc:  # noqa: BLE001
            self.parent.after(0, lambda e=str(exc): self._on_complete_auth_error(e))

    def _format_group_ids(self, group_ids: list[int]) -> str:
        if not group_ids:
            return "未绑定"
        return ", ".join(str(item) for item in group_ids)

    def _format_proxy_display(self, result: dict) -> str:
        proxy_id = result.get("proxy_id")
        proxy_name = str(result.get("proxy_name", "")).strip() or "未指定代理"
        if proxy_id in (None, "", 0):
            return proxy_name
        return f"{proxy_name} #{proxy_id}"

    def _on_complete_auth_done(self, result):
        self._auth_completion_running = False
        self._set_busy(False)

        after_create_result = result.get("after_create_result")
        after_create_error = result.get("after_create_error")
        extra_lines = []
        if isinstance(after_create_result, dict):
            if after_create_result.get("disabled"):
                extra_lines.append("ACC席位：Codex，已自动关闭这个账号的 Sub2API 调用")
            elif after_create_result.get("matched_member"):
                extra_lines.append("ACC成员缓存已命中，但当前不是 Codex 席位，保持可调用")
            elif after_create_result.get("email"):
                extra_lines.append("ACC成员缓存未命中，保持默认可调用")
            if after_create_result.get("error"):
                extra_lines.append(f"后处理提示：{after_create_result['error']}")

        if result.get("post_update_error") or after_create_error:
            warning_lines = [
                f"账号 ID：{result['account_id']}",
                f"账号名：{result['account_name']}",
                f"代理：{self._format_proxy_display(result)}",
                f"分组：{self._format_group_ids(result['group_ids'])}",
            ]
            if result.get("post_update_error"):
                warning_lines.append(f"后置更新失败：{result['post_update_error']}")
            if after_create_error:
                warning_lines.append(f"成员联动失败：{after_create_error}")
            warning_lines.extend(extra_lines)
            messagebox.showwarning(
                "账号已创建，但部分后处理未完全完成",
                "\n".join(warning_lines),
            )
            self._reset_form_after_successful_creation(
                f"账号已创建 #{result['account_id']}，页面已自动刷新，可继续下一次授权。"
            )
            return

        messagebox.showinfo(
            "Sub2API 账号创建完成",
            "\n".join(
                [
                    f"账号 ID：{result['account_id']}",
                    f"账号名：{result['account_name']}",
                    f"代理：{self._format_proxy_display(result)}",
                    f"分组：{self._format_group_ids(result['group_ids'])}",
                    f"并发：{result['concurrency']}",
                    "自动透传：已开启",
                    "WS mode：透传（passthrough）",
                    "仅允许 Codex 官方客户端：已开启",
                    *extra_lines,
                ]
            ),
        )
        self._reset_form_after_successful_creation(
            f"账号创建完成 #{result['account_id']}，页面已自动刷新，可继续下一次授权。"
        )

    def _on_complete_auth_error(self, error_message: str):
        self._auth_completion_running = False
        self._set_busy(False)
        self.status_var.set("授权建号失败")
        messagebox.showerror("授权建号失败", error_message)

    def _start_callback_listener(self) -> bool:
        """启动 localhost 回调自动接收监听。"""

        self._stop_callback_listener()
        try:
            self._callback_listener = LocalOAuthCallbackListener(
                self.redirect_uri_var.get().strip(),
                on_callback=self._handle_auto_callback_received,
                on_error=self._handle_auto_callback_error,
            )
            self._callback_listener.start()
            return True
        except Exception as exc:  # noqa: BLE001
            self._callback_listener = None
            self.status_var.set(
                f"自动回调监听启动失败：{exc}，可继续手动粘贴链接或 code。"
            )
            return False

    def _stop_callback_listener(self):
        """停止当前 localhost 回调监听。"""

        if not self._callback_listener:
            return
        self._callback_listener.stop()
        self._callback_listener = None

    def _handle_auto_callback_received(self, callback_url: str):
        """在自动接收到 localhost 回调后回填并继续建号。"""

        self.parent.after(0, lambda url=callback_url: self._on_auto_callback_received(url))

    def _on_auto_callback_received(self, callback_url: str):
        """在主线程里消费自动接收到的回调地址。"""

        if not self._pending_session or not self._pending_remote_config:
            return
        self.auth_input_var.set(callback_url)
        self._begin_complete_auth(callback_url, from_auto_callback=True)

    def _handle_auto_callback_error(self, error_message: str):
        """处理 localhost 回调监听过程中发生的错误。"""

        self.parent.after(0, lambda e=error_message: self._on_auto_callback_error(e))

    def _on_auto_callback_error(self, error_message: str):
        """在主线程里提示自动回调监听失败。"""

        if self._pending_session:
            self.status_var.set(f"自动回调接收失败：{error_message}，请改为手动粘贴链接或 code。")

    def _reset_form_after_successful_creation(self, status_text: str):
        """在账号创建成功后把授权页恢复到可继续下一次建号的初始状态。"""

        self._stop_callback_listener()
        self._pending_session = None
        self._pending_remote_config = None
        self._browser_process = None
        self.auth_url_var.set("")
        self.auth_input_var.set("")
        self.account_name_var.set(generate_random_oauth_account_name())
        self.finish_auth_btn.configure(state="disabled")
        self.copy_auth_btn.configure(state="disabled")
        self.status_var.set(status_text)


class OpenAIOAuthAccountPageWindow:
    """独立的一键授权建号窗口。"""

    def __init__(self, master, on_close=None, on_account_created=None):
        self.master = master
        self.on_close = on_close
        self.window = tk.Toplevel(master)
        self.window.title("Sub2API 一键授权建号页")
        self.window.geometry("980x620")
        self.window.minsize(860, 460)
        self.window.protocol("WM_DELETE_WINDOW", self._handle_close)

        container = ttk.Frame(self.window, padding=12)
        container.pack(fill="both", expand=True)
        self.panel = OpenAIOAuthAccountPanel(
            container,
            on_account_created=on_account_created,
        )

    def _handle_close(self):
        """关闭窗口并通知外部释放引用。"""

        if callable(self.on_close):
            self.on_close()
        self.window.destroy()

    def focus(self):
        """把窗口切到前台。"""

        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()
