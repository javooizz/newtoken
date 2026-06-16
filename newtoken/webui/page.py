"""HTML template rendering for the WebUI."""

from __future__ import annotations

from newtoken.common.http_client import mask_proxy_url, parse_socks5_proxy_url
from newtoken.sub2api.converter_core import CAP_OUTPUT_MODE, DEFAULT_OUTPUT_MODE
from newtoken.sub2api.remote_oauth import load_openai_oauth_defaults
from newtoken.webui.assets import WEBUI_CSS, WEBUI_JS
from newtoken.webui.config import (
    LOW_QUOTA_THRESHOLD_PERCENT,
    WEB_DEFAULT_HOST,
    WEB_DEFAULT_PORT,
    WebState,
)
from newtoken.webui.tasks import MAX_WEB_TASK_WORKERS
from newtoken.webui.utils import html_escape, redact_config


def build_index_html(values: dict[str, str], state: WebState) -> str:
    """Render the main single-page WebUI."""

    view = build_index_view(values, state)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sub2API ACC 控制台</title>
  <style>{WEBUI_CSS}</style>
</head>
<body data-base-path="{html_escape(state.base_path)}">
<div class="app">
  <aside>
    <div class="brand">Sub2API ACC 控制台</div>
    <div class="sub">端口 {view['port']}<br>出站代理：{html_escape(view['proxy_status'])}</div>
    <nav>
      <a href="#overview">总览</a>
      <a href="#acc-import">ACC 导入</a>
      <a href="#acc">ACC 策略</a>
      <a href="#remote">远程账号</a>
      <a href="#import">转换导入</a>
      <a href="#oauth">OAuth</a>
      <a href="#config">配置</a>
      <a href="#tasks">任务</a>
      <a href="#policy-events">更换记录</a>
    </nav>
  </aside>
  <main>
    <input id="csrf" type="hidden" value="{view['csrf']}">
    <div class="topbar" id="overview">
      <div>
        <h1>运行总览</h1>
        <div class="meta mono">{html_escape(str(state.env_path))}</div>
      </div>
      <span class="pill" id="scheduler_status">自动策略初始化中</span>
    </div>

    <div class="stats">
      <div class="stat"><span class="meta">ChatGPT 席位</span><b id="stat_chatgpt">--/2</b><span class="mini">硬限制 2</span></div>
      <div class="stat"><span class="meta">低额度账号</span><b id="stat_low">--</b><span class="mini">阈值 {LOW_QUOTA_THRESHOLD_PERCENT:g}%</span></div>
      <div class="stat"><span class="meta">Sub2API</span><b id="stat_remote">--</b><span class="mini">连接检测</span></div>
      <div class="stat"><span class="meta">自动策略</span><b id="stat_policy">30s</b><span class="mini">后台常驻</span></div>
    </div>

    <section class="band" id="config">
      <div class="section-head">
        <div>
          <h2>运行配置</h2>
          <div class="meta">保存 Sub2API、代理、端口、回调和自动策略配置。密钥留空表示不修改。</div>
        </div>
        <span id="config_status" class="status"></span>
      </div>
      <div class="grid">
        <div><label>Sub2API 地址</label><input id="cfg_base_url" value="{view['remote_base']}"></div>
        <div><label>管理员 API Key</label><input id="cfg_api_key" value="" type="password" placeholder="{view['api_key_placeholder']}"></div>
        <div><label>默认分组 ID</label><select id="cfg_group_ids" data-current="{view['group_ids']}"><option value="{view['group_ids']}">{view['group_ids_label']}</option></select></div>
        <div><label>Sub2API 代理 ID</label><select id="cfg_proxy_id" data-current="{view['proxy_id']}"><option value="{view['proxy_id']}">{view['proxy_id_label']}</option></select></div>
        <div><label>出站代理</label><input id="cfg_outbound_proxy" value="{view['outbound_proxy']}" placeholder="http://127.0.0.1:18083"></div>
        <div><label>校验并发</label><input id="cfg_validate_concurrency_config" value="{view['validate_concurrency']}"></div>
        <div><label>导入并发</label><div class="oauth-state">5（固定）</div></div>
        <div><label>Web 端口</label><input id="cfg_web_port" value="{view['port']}"></div>
        <div><label>Web Host</label><input id="cfg_web_host" value="{view['web_host']}"></div>
        <div><label>公网回调地址</label><input id="cfg_public_base_url" value="{view['public_base_url']}" placeholder="https://example.com/newtoken"></div>
        <div><label>Web 密码</label><input id="cfg_web_secret" value="" type="password" placeholder="留空不修改"></div>
        <div><label>PushPlus Token</label><input id="cfg_pushplus_token" value="" type="password" placeholder="{view['pushplus_token_placeholder']}"></div>
        <div><label>自动策略</label><select id="cfg_auto_policy_enabled"><option value="true" {view['auto_policy_enabled_true']}>开启</option><option value="false" {view['auto_policy_enabled_false']}>关闭</option></select></div>
        <div><label>额度刷新间隔</label><select id="cfg_auto_policy_interval">{view['auto_policy_interval_options']}</select></div>
        <div><label>启动后执行</label><select id="cfg_auto_policy_run_on_start"><option value="true" {view['auto_policy_run_on_start_true']}>开启</option><option value="false" {view['auto_policy_run_on_start_false']}>关闭</option></select></div>
      </div>
      <div class="toolbar">
        <button onclick="saveConfig()">保存配置</button>
        <button class="secondary" onclick="testRemote()">测试连接</button>
        <span class="pill">API {view['api_key_masked']}</span>
        <span class="pill" id="stat_proxy">代理 {view['outbound_proxy_masked']}</span>
      </div>
    </section>

    <section class="band" id="acc-import">
      <div class="section-head">
        <div>
          <h2>ACC 导入</h2>
          <div class="meta">粘贴 ACC JSON / HAR / Session 后保存，再加载成员或执行后续策略。</div>
        </div>
        <span class="status"></span>
      </div>
      <div>
        <label>ACC JSON / HAR / Session</label>
        <textarea id="acc_payload" spellcheck="false"></textarea>
        <div class="toolbar">
          <button onclick="applyAcc()">保存 ACC</button>
          <button class="secondary" onclick="loadMembers()">加载成员</button>
        </div>
      </div>
    </section>

    <section class="band" id="acc">
      <div class="section-head">
        <div>
          <h2>ACC 策略</h2>
          <div class="meta">按你选择的刷新时间自动刷新 Sub2API 额度。5h / 7天 / 31天任一已知额度低于 {LOW_QUOTA_THRESHOLD_PERCENT:g}% 时，会删除 Sub2API 账号、把席位改为 Codex，并自动走一键建号；新号导入后直接启用。最多 2 个 ChatGPT 席位，母号固定保护。</div>
        </div>
        <span id="acc_status" class="status"></span>
      </div>
      <div id="acc_members"><div class="empty">等待加载成员</div></div>
    </section>

    <section class="band" id="remote">
      <div class="section-head">
        <div>
          <h2>远程账号</h2>
          <div class="meta">扫描 Sub2API 账号状态、同步隐私设置，并按扫描结果清理异常账号。</div>
        </div>
        <span id="remote_status" class="status"></span>
      </div>
      <div class="toolbar action-row">
        <div class="action-group">
          <button data-action="remote_scan" onclick="startTask('remote_scan')">扫描状态</button>
          <button class="secondary" data-action="privacy" onclick="startTask('privacy')">同步隐私</button>
        </div>
        <div class="action-group danger-zone">
          <span class="mini">清理</span>
          <button class="danger" data-action="delete_auth_error" onclick="confirmTask('delete_auth_error', '确定删除扫描结果中的 401/认证失效账号？')">删 401</button>
          <button class="danger" data-action="delete_no_quota" onclick="confirmTask('delete_no_quota', '确定删除扫描结果中的无额度账号？')">删无额度</button>
          <button class="danger" data-action="delete_dead" onclick="confirmTask('delete_dead', '确定删除扫描结果中的全部死号？')">删死号</button>
        </div>
      </div>
      <div id="remote_summary" style="margin-top:12px"><div class="empty">等待扫描</div></div>
    </section>

    <section class="band" id="import">
      <div class="section-head">
        <div>
          <h2>转换与导入</h2>
          <div class="meta">校验本地账号 JSON，缓存转换结果，并上传到 Sub2API。</div>
        </div>
        <span id="convert_status" class="status"></span>
      </div>
      <div class="grid">
        <div><label>Linux 路径</label><input id="convert_input_path" placeholder="/www/wwwroot/accounts"></div>
        <div><label>目标格式</label><select id="convert_output_mode"><option value="{DEFAULT_OUTPUT_MODE}">Sub</option><option value="{CAP_OUTPUT_MODE}">CAP</option></select></div>
      </div>
      <div class="toolbar">
        <button data-action="convert" onclick="startTask('convert')">转换校验</button>
        <button class="ghost" onclick="copyCachedPayload()">复制缓存</button>
        <button data-action="import_cached" onclick="startTask('import_cached')">上传缓存</button>
      </div>
      <div style="margin-top:12px">
        <label>粘贴 JSON 上传</label>
        <textarea id="import_json_text" spellcheck="false"></textarea>
        <div class="toolbar"><button data-action="import_text" onclick="startTask('import_text')">上传粘贴内容</button></div>
      </div>
    </section>

    <section class="band" id="oauth">
      <div class="section-head">
        <div>
          <h2>OAuth 一步建号</h2>
          <div class="meta">授权完成后自动创建并导入 Sub2API。公网回调地址必须能从 OpenAI 访问到本 WebUI。盲人一键模式会直接走服务器自动链，并自动生成随机账号名和随机登录邮箱（邮箱后缀来自 OIDC）。</div>
        </div>
        <span id="oauth_status" class="status"></span>
      </div>
      <div class="grid">
        <div><label>账号名 / 登录邮箱</label><input id="oauth_account_name" placeholder="手动模式可填，盲人一键模式会自动生成"></div>
        <div><label>公网回调地址</label><input id="oauth_public_base_url" value="{view['public_base_url']}" placeholder="https://example.com/newtoken"></div>
        <div><label>远程代理 ID</label><select id="oauth_proxy_id" data-current="{view['oauth_proxy_id']}"><option value="{view['oauth_proxy_id']}">{view['oauth_proxy_id_label']}</option></select></div>
        <div><label>备用代理 URL</label><input id="oauth_proxy_url" value="{view['oauth_proxy_url']}"></div>
        <div><label>分组 ID</label><select id="oauth_group_ids" data-current="{view['oauth_group_ids']}"><option value="{view['oauth_group_ids']}">{view['oauth_group_ids_label']}</option></select></div>
        <div><label>分组名</label><select id="oauth_group_name" data-current="{view['oauth_group_name']}"><option value="{view['oauth_group_name']}">{view['oauth_group_name_label']}</option></select></div>
        <div><label>账号并发</label><input id="oauth_concurrency" value="{view['oauth_concurrency']}"></div>
      </div>
      <div class="toolbar">
        <button id="oauth_start_btn" onclick="startOauth()">开始授权建号</button>
        <button class="secondary" data-action="oauth_blind_import" onclick="startBlindOauthImport()">一键注册登录导入 Sub2API</button>
        <button class="secondary" onclick="loadRemoteResources()">刷新分组/代理</button>
        <button class="ghost" id="oauth_reset_btn" onclick="resetOauth()" style="display:none">重置</button>
      </div>
      <div class="grid two" style="margin-top:12px">
        <div><label>授权链接</label><input id="oauth_auth_url" readonly></div>
        <div><label>状态</label><div class="oauth-state" id="oauth_state_text">等待开始</div></div>
      </div>
      <div style="margin-top:12px">
        <label>手动兜底：回调链接或 Code</label>
        <div class="row">
          <input id="oauth_auth_input" placeholder="粘贴完整回调链接或 code" style="flex:1">
          <button class="secondary" onclick="manualCompleteOauth()">使用手动 Code 完成</button>
        </div>
      </div>
    </section>

    <section class="band" id="tasks">
      <div class="section-head">
        <div>
          <h2>任务</h2>
          <div class="meta">后台任务队列最多并发 {MAX_WEB_TASK_WORKERS}</div>
        </div>
        <span id="task_status" class="status"></span>
      </div>
      <div id="task_log"><div class="empty">暂无任务</div></div>
    </section>

    <section class="band" id="policy-events">
      <div class="section-head">
        <div>
          <h2>更换记录</h2>
          <div class="meta">保留最近 300 条席位更换、401 清理、永久禁用和策略错误记录。</div>
        </div>
        <button class="ghost" onclick="loadPolicyEvents()">刷新</button>
      </div>
      <div id="policy_event_log"><div class="empty">暂无更换记录</div></div>
    </section>
  </main>
</div>
<script>{WEBUI_JS}</script>
</body>
</html>"""


def build_index_view(values: dict[str, str], state: WebState) -> dict[str, str]:
    """Prepare escaped values for the page template."""

    config = redact_config(values)
    oauth_defaults = load_openai_oauth_defaults(str(state.env_path))
    return {
        "api_key_masked": html_escape(config.get("SUB2API_ADMIN_API_KEY_MASKED", "-") or "-"),
        "api_key_placeholder": html_escape(
            "已保存，输入新值替换" if values.get("SUB2API_ADMIN_API_KEY") else ""
        ),
        "pushplus_token_placeholder": html_escape(
            "已保存，输入新值替换" if values.get("PUSHPLUS_TOKEN") else "输入 PushPlus Token"
        ),
        "auto_policy_enabled_true": (
            "selected" if str(values.get("SUB2API_AUTO_POLICY_ENABLED", "true")).lower() != "false" else ""
        ),
        "auto_policy_enabled_false": (
            "selected" if str(values.get("SUB2API_AUTO_POLICY_ENABLED", "true")).lower() == "false" else ""
        ),
        "auto_policy_interval": html_escape(values.get("SUB2API_AUTO_POLICY_INTERVAL_SECONDS", "30")),
        "auto_policy_interval_options": build_auto_policy_interval_options(
            values.get("SUB2API_AUTO_POLICY_INTERVAL_SECONDS", "30")
        ),
        "auto_policy_run_on_start_true": (
            "selected" if str(values.get("SUB2API_AUTO_POLICY_RUN_ON_START", "true")).lower() != "false" else ""
        ),
        "auto_policy_run_on_start_false": (
            "selected" if str(values.get("SUB2API_AUTO_POLICY_RUN_ON_START", "true")).lower() == "false" else ""
        ),
        "acc_backend_email_template": html_escape(
            values.get(
                "ACC_BACKEND_EMAIL_TEMPLATE",
                "sm{index:03d}@example.com",
            )
        ),
        "acc_backend_email_start": html_escape(
            values.get("ACC_BACKEND_EMAIL_START_INDEX", "1")
        ),
        "csrf": html_escape(state.csrf_token),
        "group_ids": html_escape(values.get("SUB2API_GROUP_IDS", "")),
        "group_ids_label": html_escape(build_current_value_label(values.get("SUB2API_GROUP_IDS", ""), "不绑定分组")),
        "import_concurrency": "5",
        "oauth_concurrency": html_escape(oauth_defaults.get("concurrency", "10")),
        "oauth_group_ids": html_escape(oauth_defaults.get("group_ids", "")),
        "oauth_group_ids_label": html_escape(build_current_value_label(oauth_defaults.get("group_ids", ""), "不绑定分组")),
        "oauth_group_name": html_escape(oauth_defaults.get("group_name", "cc")),
        "oauth_group_name_label": html_escape(build_current_value_label(oauth_defaults.get("group_name", "cc"), "cc")),
        "oauth_proxy_id": html_escape(oauth_defaults.get("proxy_id", "")),
        "oauth_proxy_id_label": html_escape(build_current_value_label(oauth_defaults.get("proxy_id", ""), "留空自动使用账号配置")),
        "oauth_proxy_url": html_escape(oauth_defaults.get("proxy_url", "")),
        "outbound_proxy": html_escape(values.get("SUB2API_OUTBOUND_PROXY_URL", "")),
        "outbound_proxy_masked": html_escape(
            config.get("SUB2API_OUTBOUND_PROXY_URL_MASKED", "-") or "-"
        ),
        "port": html_escape(values.get("SUB2API_WEB_PORT") or str(WEB_DEFAULT_PORT)),
        "proxy_id": html_escape(values.get("SUB2API_PROXY_ID", "")),
        "proxy_id_label": html_escape(build_current_value_label(values.get("SUB2API_PROXY_ID", ""), "留空自动使用账号配置")),
        "proxy_status": build_proxy_status(values.get("SUB2API_OUTBOUND_PROXY_URL", "")),
        "public_base_url": html_escape(values.get("SUB2API_WEB_PUBLIC_BASE_URL", "")),
        "remote_base": html_escape(values.get("SUB2API_BASE_URL", "")),
        "validate_concurrency": html_escape(values.get("SUB2API_VALIDATE_CONCURRENCY", "24")),
        "web_host": html_escape(values.get("SUB2API_WEB_HOST") or WEB_DEFAULT_HOST),
    }


def build_proxy_status(proxy_url: str) -> str:
    proxy_url = str(proxy_url or "").strip()
    if not proxy_url:
        return "未配置"
    try:
        parse_socks5_proxy_url(proxy_url)
    except Exception as exc:  # noqa: BLE001
        return f"配置错误：{exc}"
    return f"已配置 {mask_proxy_url(proxy_url)}"


def build_current_value_label(value: str, empty_label: str) -> str:
    text = str(value or "").strip()
    return text or empty_label


def build_auto_policy_interval_options(current_value: str) -> str:
    selected = str(current_value or "10").strip() or "10"
    options = [
        ("3", "3 秒"),
        ("5", "5 秒"),
        ("10", "10 秒"),
        ("20", "20 秒"),
    ]
    values = {value for value, _label in options}
    if selected not in values:
        options.append((selected, f"当前 {selected} 秒"))
    rendered = []
    for value, label in options:
        is_selected = " selected" if value == selected else ""
        rendered.append(f'<option value="{html_escape(value)}"{is_selected}>{html_escape(label)}</option>')
    return "".join(rendered)
