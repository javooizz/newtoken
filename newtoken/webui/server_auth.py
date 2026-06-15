"""OAuth callback handler and login page for the WebUI server."""

from __future__ import annotations

from newtoken.webui.oauth import complete_oauth_from_callback
from newtoken.webui.config import WebState
from newtoken.webui.utils import html_escape


CALLBACK_HTML_HEAD = (
    "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
    "<style>body{{font-family:system-ui;margin:0;background:#f7f8fa;color:#172033}}"
    "main{{max-width:420px;margin:14vh auto;background:white;"
    "border:1px solid #d8dde6;border-radius:8px;padding:22px;text-align:center}}"
    ".ok{{color:#087443;font-weight:750}}.bad{{color:#b42318}}</style></head>"
    "<body><main>"
)
CALLBACK_HTML_TAIL = "</main></body></html>"


def build_login_html(error_message: str = "") -> str:
    err = f"<p class='bad'>{html_escape(error_message)}</p>" if error_message else ""
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>登录</title>
<style>:root{{--bg:#eef2f6;--surface:#fff;--line:#d7dee8;--text:#17202f;--brand:#0f766e;--brand-2:#115e59;--danger:#b42318}}*{{box-sizing:border-box}}body{{font-family:system-ui;margin:0;background:var(--bg);color:var(--text)}}main{{max-width:420px;margin:14vh auto;background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:22px}}input,button{{width:100%;padding:10px;margin-top:8px;font:inherit}}button{{background:var(--brand);color:white;border:0;border-radius:6px}}button:hover{{background:var(--brand-2)}}.bad{{color:var(--danger)}}</style></head>
<body><main><h1>Sub2API WebUI</h1>{err}<form method="post" action="/login"><label>Web 密码</label><input name="password" type="password" autofocus><button>登录</button></form></main></body></html>"""


def oauth_callback_html(state: WebState, host: str, path: str) -> str:
    callback_url = f"http://{host}{path}"
    try:
        result = complete_oauth_from_callback(state, callback_url)
        status_text = result.get("status", "")
        if status_text == "done":
            account_id = result.get("account_id", "")
            return (
                CALLBACK_HTML_HEAD
                + "<title>OAuth 建号完成</title>"
                + f"<h3>OAuth 建号完成</h3><p>账号 ID：<span class=\"ok\">{html_escape(str(account_id))}</span></p><p>可以关闭当前页面，回到 WebUI 查看账号。</p>"
                + CALLBACK_HTML_TAIL
            )
        if status_text == "creating_account":
            return (
                CALLBACK_HTML_HEAD
                + "<title>OAuth 处理中</title>"
                + "<h3>OAuth 回调已接收</h3><p>正在创建 Sub2API 账号，请稍候...</p>"
                + CALLBACK_HTML_TAIL
            )
        error = result.get("error", "")
        return (
            CALLBACK_HTML_HEAD
            + "<title>OAuth 失败</title>"
            + f"<h3>OAuth 回调失败</h3><p class=\"bad\">{html_escape(error)}</p>"
            + CALLBACK_HTML_TAIL
        )
    except Exception as exc:  # noqa: BLE001
        return (
            CALLBACK_HTML_HEAD
            + "<title>OAuth 回调错误</title>"
            + f"<h3>OAuth 回调处理失败</h3><p class=\"bad\">{html_escape(str(exc))}</p><p>请回到 WebUI 查看状态或使用手动 Code 兜底。</p>"
            + CALLBACK_HTML_TAIL
        )
