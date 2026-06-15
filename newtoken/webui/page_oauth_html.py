"""OAuth section HTML template snippet."""

from __future__ import annotations

OAUTH_SECTION_HTML = """    <section class="band" id="oauth">
      <div class="section-head">
        <div><h2>OAuth 一步建号</h2><div class="meta">开始授权后完成登录，系统自动导入 Sub2API</div></div>
        <span id="oauth_status" class="status"></span>
      </div>
      <div class="grid">
        <div><label>账号名</label><input id="oauth_account_name"></div>
        <div><label>公网回调地址</label><input id="oauth_public_base_url" value="{view['public_base_url']}" placeholder="http://服务器IP:28463"></div>
        <div><label>远程代理 ID</label><input id="oauth_proxy_id" value="{view['oauth_proxy_id']}"></div>
        <div><label>备用代理 URL</label><input id="oauth_proxy_url" value="{view['oauth_proxy_url']}"></div>
        <div><label>分组 ID</label><input id="oauth_group_ids" value="{view['oauth_group_ids']}"></div>
        <div><label>分组名</label><input id="oauth_group_name" value="{view['oauth_group_name']}"></div>
        <div><label>账号并发</label><input id="oauth_concurrency" value="{view['oauth_concurrency']}"></div>
      </div>
      <div class="toolbar">
        <button id="oauth_start_btn" onclick="startOauth()">开始授权建号</button>
        <button class="ghost" id="oauth_reset_btn" onclick="resetOauth()" style="display:none">重置</button>
      </div>
      <div class="grid two" style="margin-top:12px">
        <div><label>授权链接</label><input id="oauth_auth_url" readonly></div>
        <div><label>状态</label><div class="oauth-state" id="oauth_state_text">等待开始</div></div>
      </div>
      <div style="margin-top:12px">
        <label>手动兜底：回调链接或 Code（回调不可达时使用）</label>
        <div class="row">
          <input id="oauth_auth_input" placeholder="粘贴完整回调链接或 code" style="flex:1">
          <button class="secondary" onclick="manualCompleteOauth()">使用手动 Code 完成</button>
        </div>
      </div>
    </section>"""
