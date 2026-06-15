"""集成到 Sub2API 独立工具里的 GPT 空间管理页面 UI。"""

from __future__ import annotations

import os
import random
import string
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from newtoken.acc.gpt_space_manager import (
    HarSession,
    add_team_member,
    clear_session_cache,
    fetch_team_members,
    load_session_cache,
    parse_har_file,
    save_session_cache,
)

DEFAULT_RANDOM_DOMAIN = os.getenv("CHATGPT_RANDOM_EMAIL_DOMAIN", "example.com").strip() or "example.com"

_FIRST_NAMES = [
    "alex", "ava", "ben", "chloe", "daniel", "emma", "ethan", "grace",
    "harper", "isabella", "jack", "kate", "liam", "mia", "noah", "olivia",
    "owen", "penelope", "quinn", "riley", "sam", "taylor", "una", "violet",
    "will", "xander", "yara", "zoe", "lucas", "amelia", "james", "evelyn",
    "mason", "sophia", "logan", "aria", "jacob", "ella", "michael", "scarlett",
    "aiden", "layla", "ryan", "nora", "caleb", "hannah", "nathan", "luna",
]
_LAST_NAMES = [
    "smith", "johnson", "williams", "brown", "jones", "garcia", "miller", "davis",
    "rodriguez", "martinez", "anderson", "taylor", "thomas", "moore", "jackson",
    "martin", "lee", "perez", "thompson", "white", "harris", "sanchez", "clark",
    "ramirez", "lewis", "robinson", "walker", "young", "allen", "king", "wright",
    "scott", "torres", "hill", "flores", "green", "adams", "nelson", "baker",
    "hall", "rivera", "campbell", "mitchell", "carter", "roberts", "turner",
]


def _rand_str(length: int = 8) -> str:
    """生成随机串。"""

    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def generate_random_email(domain: str = DEFAULT_RANDOM_DOMAIN, style: str = "name") -> str:
    """生成随机邮箱。"""

    if style == "random":
        local = _rand_str(8)
    else:
        local = (
            random.choice(_FIRST_NAMES)
            + random.choice(_LAST_NAMES)
            + str(random.randint(100, 9999))
        )
    return f"{local}@{domain}"


class StandaloneGptSpaceManagerPanel:
    """GPT 空间成员管理面板。"""

    def __init__(self, parent, session_cache_path: str | None = None):
        self.parent = parent
        self.session_cache_path = session_cache_path
        self._session: HarSession | None = None
        self._members: list[dict] = []

        top_frame = ttk.Frame(parent)
        top_frame.pack(fill="x", pady=(0, 8))

        self.har_path_var = tk.StringVar()
        self.har_status_var = tk.StringVar(value="未加载 HAR 文件（可选，支持缓存恢复）")
        ttk.Label(top_frame, text="HAR 文件：").pack(side="left")
        ttk.Entry(top_frame, textvariable=self.har_path_var, width=52).pack(
            side="left", fill="x", expand=True, padx=(4, 8)
        )
        ttk.Button(top_frame, text="浏览...", command=self._browse_har).pack(side="left", padx=(0, 8))
        ttk.Button(top_frame, text="加载 HAR", command=self._load_har).pack(side="left")
        ttk.Button(top_frame, text="清空缓存", command=self._clear_session_cache).pack(side="left", padx=(8, 0))
        ttk.Label(top_frame, textvariable=self.har_status_var, foreground="gray").pack(side="left", padx=(12, 0))

        list_frame = ttk.LabelFrame(parent, text="GPT 空间成员列表", padding=4)
        list_frame.pack(fill="both", expand=True, pady=(0, 8))

        columns = ("email", "name", "seat", "status")
        self.tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=12)
        self.tree.heading("email", text="邮箱")
        self.tree.heading("name", text="名称")
        self.tree.heading("seat", text="席位")
        self.tree.heading("status", text="状态")
        self.tree.column("email", width=320)
        self.tree.column("name", width=180)
        self.tree.column("seat", width=120)
        self.tree.column("status", width=100)

        scrollbar = ttk.Scrollbar(list_frame, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<Double-1>", self._copy_cell)

        list_button_row = ttk.Frame(list_frame)
        list_button_row.pack(fill="x", pady=(4, 0))
        ttk.Button(list_button_row, text="刷新成员列表", command=self._refresh_members).pack(side="left", padx=(0, 8))
        ttk.Button(list_button_row, text="复制选中邮箱", command=self._copy_selected_email).pack(side="left", padx=(0, 8))
        ttk.Button(list_button_row, text="复制全部邮箱", command=self._copy_all_emails).pack(side="left")

        add_frame = ttk.LabelFrame(parent, text="手动添加成员", padding=4)
        add_frame.pack(fill="x")
        add_row = ttk.Frame(add_frame)
        add_row.pack(fill="x")
        ttk.Label(add_row, text="邮箱：").pack(side="left")
        self.add_email_var = tk.StringVar()
        ttk.Entry(add_row, textvariable=self.add_email_var, width=42).pack(
            side="left", fill="x", expand=True, padx=(4, 8)
        )
        ttk.Label(add_row, text="席位：").pack(side="left")
        self.seat_var = tk.StringVar(value="codex")
        ttk.Entry(add_row, textvariable=self.seat_var, width=12).pack(side="left", padx=(4, 8))
        self.add_btn = ttk.Button(add_row, text="添加成员", command=self._add_member, state="disabled")
        self.add_btn.pack(side="left")
        self.add_status_var = tk.StringVar()
        ttk.Label(add_row, textvariable=self.add_status_var, foreground="green").pack(side="left", padx=(12, 0))

        random_frame = ttk.LabelFrame(parent, text="随机邮箱拉人", padding=4)
        random_frame.pack(fill="x", pady=(8, 0))
        random_row = ttk.Frame(random_frame)
        random_row.pack(fill="x")
        ttk.Label(random_row, text="数量：").pack(side="left")
        self.rand_count_var = tk.StringVar(value="1")
        ttk.Spinbox(random_row, textvariable=self.rand_count_var, from_=1, to=100, width=5).pack(side="left", padx=(4, 8))
        ttk.Label(random_row, text="域名：").pack(side="left")
        self.rand_domain_var = tk.StringVar(value=DEFAULT_RANDOM_DOMAIN)
        ttk.Entry(random_row, textvariable=self.rand_domain_var, width=22).pack(side="left", padx=(4, 8))
        self.rand_type_var = tk.StringVar(value="name")
        ttk.Radiobutton(random_row, text="姓名+数字", variable=self.rand_type_var, value="name").pack(side="left", padx=(0, 4))
        ttk.Radiobutton(random_row, text="纯随机", variable=self.rand_type_var, value="random").pack(side="left")
        self.rand_btn = ttk.Button(
            random_row,
            text="随机生成并拉人",
            command=self._random_add_members,
            state="disabled",
        )
        self.rand_btn.pack(side="left", padx=(12, 8))
        self.rand_status_var = tk.StringVar()
        ttk.Label(random_row, textvariable=self.rand_status_var, foreground="green").pack(side="left")

        self._restore_cached_session_if_available()

    def _browse_har(self) -> None:
        """选择 HAR 文件。"""

        path = filedialog.askopenfilename(
            title="选择 chatgpt.com.har",
            filetypes=[("HAR 文件", "*.har"), ("所有文件", "*.*")],
        )
        if path:
            self.har_path_var.set(path)

    def _set_session_ready_state(self) -> None:
        """会话恢复后开启操作按钮。"""

        self.add_btn.configure(state="normal")
        self.rand_btn.configure(state="normal")

    def _load_har(self) -> None:
        """加载 HAR 并刷新成员列表。"""

        path = self.har_path_var.get().strip()
        if not path:
            messagebox.showerror("错误", "请先选择 HAR 文件")
            return
        if not os.path.isfile(path):
            messagebox.showerror("错误", "文件不存在，请重新选择 HAR 文件")
            self.har_path_var.set("")
            return
        try:
            self._session = parse_har_file(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("HAR 解析失败", str(exc))
            return
        if not self._session or not self._session.is_valid:
            self._session = None
            messagebox.showerror("错误", "未在 HAR 中找到有效的 session token")
            return
        try:
            save_session_cache(self._session, self.session_cache_path)
            self.har_status_var.set("HAR 已加载，缓存已更新")
        except Exception as exc:  # noqa: BLE001
            self.har_status_var.set("HAR 已加载，缓存写入失败")
            messagebox.showwarning("缓存写入失败", str(exc))
        self._set_session_ready_state()
        self._refresh_members()

    def _restore_cached_session_if_available(self) -> None:
        """启动时自动恢复本地缓存。"""

        try:
            session = load_session_cache(self.session_cache_path)
        except Exception:  # noqa: BLE001
            self.har_status_var.set("会话缓存损坏，请重新加载 HAR")
            return
        if not session:
            return
        self._session = session
        self._set_session_ready_state()
        self.har_status_var.set("已恢复缓存会话，无需 HAR 文件")
        self._refresh_members()

    def _clear_session_cache(self) -> None:
        """清空本地会话缓存。"""

        try:
            removed = clear_session_cache(self.session_cache_path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("清空缓存失败", str(exc))
            return
        if removed:
            if self._session and self._session.is_valid:
                self.har_status_var.set("已清空缓存，当前会话仍可使用")
            else:
                self.har_status_var.set("已清空缓存")
        else:
            self.har_status_var.set("未找到会话缓存")

    def _refresh_members(self) -> None:
        """刷新成员列表。"""

        if not self._session:
            return
        self.har_status_var.set("获取成员列表中...")
        self.tree.delete(*self.tree.get_children())

        def run() -> None:
            try:
                members = fetch_team_members(self._session)
                self.parent.after(0, lambda value=members: self._on_members_loaded(value))
            except Exception as exc:  # noqa: BLE001
                self.parent.after(0, lambda error=exc: self._on_members_error(str(error)))

        threading.Thread(target=run, daemon=True).start()

    def _on_members_loaded(self, members: list[dict]) -> None:
        """把成员列表渲染到表格。"""

        self._members = members
        self.tree.delete(*self.tree.get_children())
        for item in members:
            self.tree.insert(
                "",
                "end",
                values=(
                    item.get("email", ""),
                    item.get("name", ""),
                    item.get("seat_type", ""),
                    item.get("status", ""),
                ),
            )
        self.har_status_var.set(f"已加载 {len(members)} 个成员")

    def _on_members_error(self, error_message: str) -> None:
        """处理成员刷新失败。"""

        self.har_status_var.set("获取成员失败")
        messagebox.showerror("获取成员失败", error_message[:500])

    def _add_member(self) -> None:
        """手动添加成员。"""

        email = self.add_email_var.get().strip()
        if not email or "@" not in email:
            messagebox.showerror("错误", "请输入有效的邮箱地址")
            return
        if not self._session:
            return
        seat = self.seat_var.get().strip() or "codex"
        self.add_btn.configure(state="disabled")
        self.add_status_var.set("添加中...")

        def run() -> None:
            try:
                add_team_member(self._session, email, seat)
                self.parent.after(0, lambda: self._on_add_done(email))
            except Exception as exc:  # noqa: BLE001
                self.parent.after(0, lambda error=exc: self._on_add_error(str(error)))

        threading.Thread(target=run, daemon=True).start()

    def _on_add_done(self, email: str) -> None:
        """添加完成后更新状态。"""

        self.add_status_var.set(f"已添加 {email}")
        self.add_email_var.set("")
        self.add_btn.configure(state="normal")
        self._refresh_members()

    def _on_add_error(self, error_message: str) -> None:
        """处理添加失败。"""

        self.add_status_var.set("添加失败")
        self.add_btn.configure(state="normal")
        messagebox.showerror("添加成员失败", error_message[:500])

    def _random_add_members(self) -> None:
        """批量随机拉人。"""

        if not self._session:
            return
        try:
            count = int(self.rand_count_var.get())
        except ValueError:
            count = 1
        count = max(1, min(count, 100))
        domain = self.rand_domain_var.get().strip() or DEFAULT_RANDOM_DOMAIN
        style = self.rand_type_var.get()
        emails = [generate_random_email(domain, style) for _ in range(count)]
        self.rand_btn.configure(state="disabled")
        self.rand_status_var.set(f"正在拉 {count} 人...")

        def run() -> None:
            ok_count = 0
            failed_count = 0
            for email in emails:
                try:
                    add_team_member(self._session, email, "codex")
                    ok_count += 1
                    self.parent.after(
                        0,
                        lambda done=ok_count, current=email: self.rand_status_var.set(
                            f"已拉 {done}/{count} {current}"
                        ),
                    )
                except Exception:  # noqa: BLE001
                    failed_count += 1
            self.parent.after(0, lambda: self._on_random_done(ok_count, failed_count, count))

        threading.Thread(target=run, daemon=True).start()

    def _on_random_done(self, ok_count: int, failed_count: int, total_count: int) -> None:
        """随机拉人完成。"""

        self.rand_status_var.set(f"完成 成功{ok_count} 失败{failed_count}/{total_count}")
        self.rand_btn.configure(state="normal")
        self._refresh_members()

    def _copy_cell(self, event) -> None:
        """双击复制单元格。"""

        selection = self.tree.selection()
        if not selection:
            return
        column = self.tree.identify_column(event.x)
        column_index = int(column.replace("#", "")) - 1
        item = self.tree.item(selection[0])
        values = item.get("values", [])
        value = values[column_index] if column_index < len(values) else ""
        if value:
            self.parent.clipboard_clear()
            self.parent.clipboard_append(str(value))
            self.parent.update()

    def _copy_selected_email(self) -> None:
        """复制选中邮箱。"""

        selection = self.tree.selection()
        if not selection:
            return
        emails = []
        for item_id in selection:
            values = self.tree.item(item_id).get("values", [])
            if values and values[0]:
                emails.append(str(values[0]))
        if emails:
            self.parent.clipboard_clear()
            self.parent.clipboard_append("\n".join(emails))
            self.parent.update()

    def _copy_all_emails(self) -> None:
        """复制全部邮箱。"""

        emails = [item.get("email", "") for item in self._members if item.get("email")]
        if emails:
            self.parent.clipboard_clear()
            self.parent.clipboard_append("\n".join(emails))
            self.parent.update()


class StandaloneGptSpaceManagerWindow:
    """GPT 空间管理独立窗口。"""

    def __init__(self, parent, on_close=None):
        self.parent = parent
        self.on_close = on_close
        self.window = tk.Toplevel(parent)
        self.window.title("GPT空间管理页面")
        self.window.geometry("1120x760")
        self.window.minsize(900, 620)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        container = ttk.Frame(self.window, padding=12)
        container.pack(fill="both", expand=True)
        self.panel = StandaloneGptSpaceManagerPanel(container)

    def focus(self) -> None:
        """把窗口拉到前台。"""

        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()

    def close(self) -> None:
        """关闭窗口并通知宿主。"""

        if self.window.winfo_exists():
            self.window.destroy()
        if callable(self.on_close):
            self.on_close()
