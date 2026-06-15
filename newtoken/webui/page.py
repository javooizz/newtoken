"""HTML template rendering for the WebUI."""

from __future__ import annotations

from newtoken.common.http_client import mask_proxy_url, parse_socks5_proxy_url
from newtoken.sub2api.converter_core import CAP_OUTPUT_MODE, DEFAULT_OUTPUT_MODE
from newtoken.webui.assets import WEBUI_CSS, WEBUI_JS
from newtoken.webui.config import (
    LOW_QUOTA_THRESHOLD_PERCENT,
    WEB_DEFAULT_HOST,
    WEB_DEFAULT_PORT,
    WebState,
    get_setup_missing_fields,
    is_setup_complete,
)
from newtoken.webui.tasks import MAX_WEB_TASK_WORKERS
from newtoken.webui.utils import html_escape, redact_config


def build_index_html(values: dict[str, str], state: WebState) -> str:
    view = build_index_view(values, state)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sub2API 控制台</title>
  <style>{WEBUI_CSS}</style>
</head>
<body>
<div class="app">
  <aside>
    <div class="brand">Sub2API 控制台</div>
    <div class="sub">端口 {view['port']}<br>SOCKS5: {html_escape(view['proxy_status'])}<br>安装: {view['setup_status']}</div>
    <nav>
      <a href="#setup">安装配置</a>
      <a href="#overview">总览</a>
      <a href="#maintenance">自动维护</a>
      <a href="#acc">ACC 策略</a>
      <a href="#remote">远程账号</a>
      <a href="#import">导入</a>
      <a href="#tasks">任务</a>
    </nav>
  </aside>
  <main>
    <input id="csrf" type="hidden" value="{view['csrf']}">
    <div class="banner {view['setup_banner_class']}" id="setup">
      <div>
        <h1>{view['setup_title']}</h1>
        <div class="meta">{view['setup_description']}</div>
        <div class="meta">{view['setup_missing_text']}</div>
      </div>
      <div class="row">
        <span class="pill {view['setup_pill_class']}">{view['setup_pill_text']}</span>
      </div>
    </div>

    <section class="band">
      <div class="section-head">
        <div><h2>安装配置</h2><div class="meta">填完并保存后，系统才会进入控制台状态</div></div>
        <span id="setup_status" class="status"></span>
      </div>
      <div class="config-stack">
        <div class="config-group">
          <h3>Sub2API</h3>
          <div class="grid">
            <div><label>Sub2API 地址</label><input id="cfg_base_url" value="{view['remote_base']}" placeholder="https://你的 Sub2API"></div>
            <div><label>管理员 API Key</label><input id="cfg_api_key" value="" type="password" placeholder="{view['api_key_placeholder']}"></div>
            <div><label>默认分组 ID</label><input id="cfg_group_ids" value="{view['group_ids']}" placeholder="1,2"></div>
            <div><label>Sub2API 代理 ID</label><input id="cfg_proxy_id" value="{view['proxy_id']}" placeholder="留空自动使用账号配置"></div>
            <div><label>SOCKS5 出站代理</label><input id="cfg_outbound_proxy" value="{view['outbound_proxy']}" placeholder="socks5://127.0.0.1:1080"></div>
            <div><label>导入并发</label><input id="cfg_import_concurrency" value="{view['import_concurrency']}"></div>
            <div><label>校验并发</label><input id="cfg_validate_concurrency" value="{view['validate_concurrency']}"></div>
          </div>
        </div>

        <div class="config-group">
          <h3>母号 ACC</h3>
          <div class="grid">
            <div><label>母号邮箱</label><input id="cfg_mother_email" value="{view['mother_email']}" placeholder="母号登录邮箱"></div>
            <div><label>当前 ACC</label><input value="{view['acc_saved_status']}" readonly></div>
          </div>
          <div class="field-wide">
            <label>母号 ACC 内容</label>
            <textarea id="cfg_acc_payload" placeholder="直接粘贴 ACC JSON / HAR / Session / token，保存时会自动解析"></textarea>
          </div>
        </div>

        <div class="config-group">
          <h3>OIDC 自动注册</h3>
          <div class="grid">
            <div><label>OIDC API 地址</label><input id="cfg_oidc_api_url" value="{view['oidc_api_url']}" placeholder="https://oidc.example.com"></div>
            <div><label>OIDC API Key</label><input id="cfg_oidc_api_key" value="" type="password" placeholder="{view['oidc_api_key_placeholder']}"></div>
            <div><label>自动注册域名</label><input id="cfg_auto_register_domain" value="{view['auto_register_domain']}" placeholder="@team.edu.sixoner.com"></div>
            <div><label>自动注册数</label><input id="cfg_auto_register_count" value="{view['auto_register_count']}"></div>
            <div><label>注册阈值</label><input id="cfg_auto_register_threshold" value="{view['auto_register_threshold']}"></div>
            <div><label>自动注册</label><select id="cfg_auto_register_enabled"><option value="true" {view['auto_register_enabled_true']}>开启</option><option value="false" {view['auto_register_enabled_false']}>关闭</option></select></div>
          </div>
        </div>

        <div class="config-group">
          <h3>Web 与调度</h3>
          <div class="grid">
            <div><label>Web 端口</label><input id="cfg_web_port" value="{view['port']}"></div>
            <div><label>Web Host</label><input id="cfg_web_host" value="{view['web_host']}"></div>
            <div><label>公网地址</label><input id="cfg_public_base_url" value="{view['public_base_url']}" placeholder="https://你的域名 或 http://IP:端口"></div>
            <div><label>Web 密码</label><input id="cfg_web_secret" value="" type="password" placeholder="留空不修改"></div>
            <div><label>自动策略</label><select id="cfg_auto_policy_enabled"><option value="true" {view['auto_policy_enabled_true']}>开启</option><option value="false" {view['auto_policy_enabled_false']}>关闭</option></select></div>
            <div><label>策略间隔秒</label><input id="cfg_auto_policy_interval" value="{view['auto_policy_interval']}"></div>
            <div><label>启动后执行</label><select id="cfg_auto_policy_run_on_start"><option value="true" {view['auto_policy_run_on_start_true']}>开启</option><option value="false" {view['auto_policy_run_on_start_false']}>关闭</option></select></div>
          </div>
        </div>
      </div>
      <div class="toolbar">
        <button onclick="saveConfig()">保存并进入控制台</button>
        <button class="secondary" onclick="testRemote()">测试 Sub2API</button>
        <button class="secondary" onclick="testOidc()">测试 OIDC</button>
        <span class="pill">API {view['api_key_masked']}</span>
        <span class="pill" id="stat_proxy">代理 {view['outbound_proxy_masked']}</span>
      </div>
    </section>

    <div id="shell" class="shell {view['console_class']}">
      <div class="topbar" id="overview">
        <div>
          <h1>运行总览</h1>
          <div class="meta mono">{html_escape(str(state.env_path))}</div>
        </div>
        <div class="row"><span class="pill" id="scheduler_status">自动维护</span></div>
      </div>
      <div class="stats">
        <div class="stat"><span class="meta">ChatGPT 席位</span><b id="stat_chatgpt">--/2</b><span class="mini">硬限制 2</span></div>
        <div class="stat"><span class="meta">低额度账号</span><b id="stat_low">--</b><span class="mini">阈值 {LOW_QUOTA_THRESHOLD_PERCENT:g}%</span></div>
        <div class="stat"><span class="meta">远程账号</span><b id="stat_remote">--</b><span class="mini">Sub2API OAuth</span></div>
        <div class="stat"><span class="meta">异常账号</span><b id="stat_dead">--</b><span class="mini">死号 / 无额度</span></div>
      </div>

      <section class="band" id="maintenance">
        <div class="section-head">
          <div><h2>自动维护</h2><div class="meta">席位校正、远程扫描、自动补号、导入 OIDC、后台定时运行</div></div>
          <span id="maintenance_status" class="status"></span>
        </div>
        <div class="toolbar">
          <button class="warn" data-action="auto_maintenance" onclick="startTask('auto_maintenance')">立即运行自动维护</button>
          <button class="secondary" data-action="low_quota_policy" onclick="startTask('low_quota_policy')">仅执行席位策略</button>
        </div>
        <div class="grid two" style="margin-top:12px">
          <div class="panel">
            <div class="meta">自动维护状态</div>
            <div id="maintenance_summary" class="mono">等待执行</div>
          </div>
          <div class="panel">
            <div class="meta">说明</div>
            <div class="mono">系统安装完成后会自动运行；不需要手动刷新页面触发。</div>
          </div>
        </div>
      </section>

      <section class="band" id="acc">
        <div class="section-head">
          <div><h2>ACC 策略</h2><div class="meta">服务端自动执行；Codex 不回 ChatGPT，ChatGPT 总数收敛到 2 以内</div></div>
          <span id="acc_status" class="status"></span>
        </div>
        <div class="split">
          <div>
            <label>ACC JSON / HAR / Session</label>
            <textarea id="acc_payload"></textarea>
            <div class="toolbar">
              <button onclick="applyAcc()">保存 ACC</button>
              <button class="secondary" onclick="loadMembers()">加载成员</button>
              <button class="warn" data-action="low_quota_policy" onclick="startTask('low_quota_policy')">立即运行策略</button>
            </div>
          </div>
          <div id="acc_members"><div class="empty">等待加载成员</div></div>
        </div>
      </section>

      <section class="band" id="remote">
        <div class="section-head">
          <div><h2>远程账号</h2><div class="meta">状态扫描、隐私同步和异常清理</div></div>
          <span id="remote_status" class="status"></span>
        </div>
        <div class="toolbar">
          <button data-action="remote_scan" onclick="startTask('remote_scan')">扫描状态</button>
          <button class="secondary" data-action="privacy" onclick="startTask('privacy')">同步隐私</button>
          <button class="danger" data-action="delete_auth_error" onclick="confirmTask('delete_auth_error', '删除所有 401/认证失效账号？')">删 401</button>
          <button class="danger" data-action="delete_no_quota" onclick="confirmTask('delete_no_quota', '删除所有无额度账号？')">删无额度</button>
          <button class="danger" data-action="delete_dead" onclick="confirmTask('delete_dead', '删除全部死号？')">删死号</button>
        </div>
        <div id="remote_summary" style="margin-top:12px"><div class="empty">等待扫描</div></div>
      </section>

      <section class="band" id="import">
        <div class="section-head">
          <div><h2>转换与导入</h2><div class="meta">本地账号校验、缓存 JSON、上传 Sub2API</div></div>
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
          <textarea id="import_json_text"></textarea>
          <div class="toolbar"><button data-action="import_text" onclick="startTask('import_text')">上传粘贴内容</button></div>
        </div>
      </section>

      <section class="band" id="tasks">
        <div class="section-head">
          <div><h2>任务</h2><div class="meta">后台任务队列最多并发 {MAX_WEB_TASK_WORKERS}</div></div>
          <span id="task_status" class="status"></span>
        </div>
        <div id="task_log"><div class="empty">暂无任务</div></div>
      </section>
    </div>
  </main>
</div>
<script>{WEBUI_JS}</script>
</body>
</html>"""


def build_index_view(values: dict[str, str], state: WebState) -> dict[str, str]:
    config = redact_config(values)
    missing = get_setup_missing_fields(values)
    setup_complete = is_setup_complete(values)
    console_class = "visible" if setup_complete else "hidden"
    setup_title = "安装已完成" if setup_complete else "先完成安装配置"
    setup_description = (
        "系统已进入控制台模式，后台自动维护会继续运行。"
        if setup_complete
        else "请先把 Sub2API、母号 ACC、OIDC、SOCKS5 配好，再保存。"
    )
    setup_pill_text = "已安装" if setup_complete else "未安装"
    setup_pill_class = "ok" if setup_complete else "bad"
    setup_banner_class = "ok" if setup_complete else "bad"
    setup_status = "已安装" if setup_complete else "未安装"
    setup_missing_text = "" if setup_complete else f"待补齐：{'，'.join(missing) if missing else '保存安装状态'}"
    has_acc_token = bool(values.get("OPENAI_ACCESS_TOKEN") or values.get("OPENAI_SESSION_TOKEN"))
    has_acc_id = bool(values.get("OPENAI_ACCOUNT_ID"))
    acc_saved_status = "已保存" if has_acc_token and has_acc_id else "未保存，请粘贴 ACC 内容"
    return {
        "api_key_masked": html_escape(config.get("SUB2API_ADMIN_API_KEY_MASKED", "-") or "-"),
        "api_key_placeholder": html_escape("已保存，输入新值替换" if values.get("SUB2API_ADMIN_API_KEY") else ""),
        "acc_base_url": html_escape(values.get("OPENAI_BASE_URL", "")),
        "acc_saved_status": html_escape(acc_saved_status),
        "auto_policy_enabled_true": "selected" if str(values.get("SUB2API_AUTO_POLICY_ENABLED", "true")).lower() != "false" else "",
        "auto_policy_enabled_false": "selected" if str(values.get("SUB2API_AUTO_POLICY_ENABLED", "true")).lower() == "false" else "",
        "auto_policy_interval": html_escape(values.get("SUB2API_AUTO_POLICY_INTERVAL_SECONDS", "300")),
        "auto_policy_run_on_start_true": "selected" if str(values.get("SUB2API_AUTO_POLICY_RUN_ON_START", "true")).lower() != "false" else "",
        "auto_policy_run_on_start_false": "selected" if str(values.get("SUB2API_AUTO_POLICY_RUN_ON_START", "true")).lower() == "false" else "",
        "auto_register_count": html_escape(values.get("SUB2API_AUTO_REGISTER_COUNT", "3")),
        "auto_register_domain": html_escape(values.get("SUB2API_AUTO_REGISTER_DOMAIN", "")),
        "auto_register_enabled_true": "selected" if str(values.get("SUB2API_AUTO_REGISTER_ENABLED", "true")).lower() != "false" else "",
        "auto_register_enabled_false": "selected" if str(values.get("SUB2API_AUTO_REGISTER_ENABLED", "true")).lower() == "false" else "",
        "auto_register_threshold": html_escape(values.get("SUB2API_AUTO_REGISTER_THRESHOLD", "1")),
        "client_build_number": html_escape(values.get("OPENAI_CLIENT_BUILD_NUMBER", "")),
        "client_version": html_escape(values.get("OPENAI_CLIENT_VERSION", "")),
        "console_class": console_class,
        "csrf": html_escape(state.csrf_token),
        "group_ids": html_escape(values.get("SUB2API_GROUP_IDS", "")),
        "import_concurrency": html_escape(values.get("SUB2API_IMPORT_CONCURRENCY", "50")),
        "mother_email": html_escape(values.get("ACC_MOTHER_ACCOUNT_EMAIL", "")),
        "oidc_api_key_placeholder": html_escape("已保存，输入新值替换" if values.get("SUB2API_OIDC_API_KEY") else ""),
        "oidc_api_url": html_escape(values.get("SUB2API_OIDC_API_URL", "")),
        "outbound_proxy": html_escape(values.get("SUB2API_OUTBOUND_PROXY_URL", "")),
        "outbound_proxy_masked": html_escape(config.get("SUB2API_OUTBOUND_PROXY_URL_MASKED", "-") or "-"),
        "port": html_escape(values.get("SUB2API_WEB_PORT") or WEB_DEFAULT_PORT),
        "proxy_id": html_escape(values.get("SUB2API_PROXY_ID", "")),
        "proxy_status": build_proxy_status(values.get("SUB2API_OUTBOUND_PROXY_URL", "")),
        "public_base_url": html_escape(values.get("SUB2API_WEB_PUBLIC_BASE_URL", "")),
        "remote_base": html_escape(values.get("SUB2API_BASE_URL", "")),
        "setup_banner_class": setup_banner_class,
        "setup_complete": "true" if setup_complete else "false",
        "setup_description": setup_description,
        "setup_missing": html_escape("，".join(missing) if missing else ""),
        "setup_missing_text": html_escape(setup_missing_text),
        "setup_pill_class": setup_pill_class,
        "setup_pill_text": setup_pill_text,
        "setup_status": setup_status,
        "setup_status_text": setup_status,
        "setup_title": setup_title,
        "setup_visibility": "hidden" if setup_complete else "visible",
        "setup_missing_count": str(len(missing)),
        "stat_count_hint": str(len(missing)),
        "validate_concurrency": html_escape(values.get("SUB2API_VALIDATE_CONCURRENCY", "24")),
        "web_host": html_escape(values.get("SUB2API_WEB_HOST") or WEB_DEFAULT_HOST),
        "setup_status_badge": setup_status,
        "setup_status_class": setup_banner_class,
        "setup_status_label": setup_status,
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
