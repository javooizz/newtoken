"""OAuth JavaScript for the WebUI."""

from __future__ import annotations

WEBUI_OAUTH_JS = """
let oauthPollTimer = null;
async function startOauth() {
  const startBtn = byId('oauth_start_btn');
  try {
    startBtn.disabled = true;
    startBtn.textContent = '正在启动...';
    const data = await api('/api/oauth/start', {
      account_name: formValue('oauth_account_name'),
      public_base_url: formValue('oauth_public_base_url'),
      proxy_id: formValue('oauth_proxy_id'),
      proxy_url: formValue('oauth_proxy_url'),
      group_ids: formValue('oauth_group_ids'),
      group_name: formValue('oauth_group_name'),
      concurrency: formValue('oauth_concurrency')
    });
    const result = data.result || {};
    if (result.auth_url) {
      byId('oauth_auth_url').value = result.auth_url;
      window.open(result.auth_url, '_blank');
    }
    updateOauthUI(result);
    startOauthPolling();
  } catch(e) {
    startBtn.disabled = false;
    startBtn.textContent = '开始授权建号';
    setText('oauth_status', e.message, true);
  }
}
function startOauthPolling() {
  if (oauthPollTimer) return;
  oauthPollTimer = setInterval(pollOauthStatus, 2000);
}
function stopOauthPolling() {
  if (oauthPollTimer) { clearInterval(oauthPollTimer); oauthPollTimer = null; }
}
async function pollOauthStatus() {
  try {
    const data = await api('/api/oauth/status', {});
    const result = data.result || {};
    updateOauthUI(result);
    if (['done', 'error', 'idle'].includes(result.status)) stopOauthPolling();
  } catch(e) {}
}
function updateOauthUI(result) {
  const status = result.status || 'idle';
  const stateEl = byId('oauth_state_text');
  const startBtn = byId('oauth_start_btn');
  const resetBtn = byId('oauth_reset_btn');
  switch (status) {
    case 'idle':
      stateEl.textContent = '等待开始'; stateEl.className = 'oauth-state';
      startBtn.disabled = false; startBtn.textContent = '开始授权建号'; resetBtn.style.display = 'none';
      break;
    case 'waiting_callback':
      stateEl.textContent = '已生成授权链接，请在新窗口完成登录授权';
      stateEl.className = 'oauth-state'; startBtn.disabled = true; startBtn.textContent = '等待授权中...'; resetBtn.style.display = '';
      break;
    case 'creating_account':
      stateEl.textContent = '已收到回调，正在创建 Sub2API 账号';
      stateEl.className = 'oauth-state'; startBtn.disabled = true; startBtn.textContent = '创建账号中...'; resetBtn.style.display = '';
      break;
    case 'done':
      stateEl.textContent = '建号完成 #' + (result.account_id || '--');
      stateEl.className = 'oauth-state ok'; startBtn.disabled = false; startBtn.textContent = '开始授权建号'; resetBtn.style.display = '';
      setText('oauth_status', '建号完成 #' + (result.account_id || '--'));
      break;
    case 'error':
      stateEl.textContent = '错误：' + (result.error || '未知');
      stateEl.className = 'oauth-state bad'; startBtn.disabled = false; startBtn.textContent = '开始授权建号'; resetBtn.style.display = '';
      setText('oauth_status', result.error || '未知错误', true);
      break;
  }
}
async function resetOauth() {
  stopOauthPolling();
  byId('oauth_auth_url').value = '';
  byId('oauth_state_text').textContent = '等待开始';
  byId('oauth_state_text').className = 'oauth-state';
  byId('oauth_start_btn').disabled = false;
  byId('oauth_start_btn').textContent = '开始授权建号';
  byId('oauth_reset_btn').style.display = 'none';
  setText('oauth_status', '');
}
async function manualCompleteOauth() {
  try {
    const data = await api('/api/oauth/manual-complete', {auth_input: formValue('oauth_auth_input')});
    updateOauthUI(data.result || {});
    startOauthPolling();
  } catch(e) { setText('oauth_status', e.message, true); }
}
"""
