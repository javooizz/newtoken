"""Inline CSS and browser-side JavaScript for the dependency-light WebUI."""

from __future__ import annotations


WEBUI_CSS = """
:root {
  --bg: #eef2f6;
  --surface: #ffffff;
  --surface-2: #f8fafc;
  --line: #d7dee8;
  --text: #17202f;
  --muted: #647083;
  --brand: #0f766e;
  --brand-2: #115e59;
  --blue: #22577a;
  --warn: #9a3412;
  --danger: #b42318;
  --ok: #087443;
  --shadow: 0 8px 22px rgba(22, 31, 45, .05);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; font-family: system-ui, -apple-system, Segoe UI, sans-serif; background: var(--bg); color: var(--text); }
button, input, textarea, select { font: inherit; }
button { border: 0; border-radius: 6px; background: var(--brand); color: white; padding: 8px 12px; cursor: pointer; min-height: 36px; white-space: nowrap; }
button:hover { background: var(--brand-2); }
button.secondary { background: var(--blue); }
button.warn { background: var(--warn); }
button.danger { background: var(--danger); }
button.ghost { background: transparent; color: var(--text); border: 1px solid var(--line); }
button:disabled { opacity: .58; cursor: wait; }
input, textarea, select { width: 100%; border: 1px solid var(--line); border-radius: 6px; background: white; color: var(--text); padding: 9px 10px; outline: none; }
input:focus, textarea:focus, select:focus { border-color: var(--brand); box-shadow: 0 0 0 3px rgba(15, 118, 110, .12); }
textarea { min-height: 132px; resize: vertical; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 13px; line-height: 1.45; }
label { display: block; color: var(--muted); font-size: 12px; margin-bottom: 5px; }
.app { min-height: 100vh; display: grid; grid-template-columns: 236px minmax(0, 1fr); }
aside { position: sticky; top: 0; height: 100vh; padding: 18px; background: #162334; color: white; }
.brand { font-size: 18px; font-weight: 750; margin-bottom: 4px; }
.sub { color: #cbd5e1; font-size: 12px; line-height: 1.5; overflow-wrap: anywhere; }
nav { display: grid; gap: 6px; margin-top: 22px; }
nav a { color: #e5edf6; text-decoration: none; padding: 9px 10px; border-radius: 6px; font-size: 14px; }
nav a:hover { background: rgba(255, 255, 255, .1); }
main { min-width: 0; padding: 22px; }
.topbar { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
h1 { font-size: 24px; margin: 0 0 4px; letter-spacing: 0; }
h2 { font-size: 17px; margin: 0; letter-spacing: 0; }
.meta { color: var(--muted); font-size: 13px; }
.status { color: var(--muted); font-size: 13px; min-height: 20px; }
.ok { color: var(--ok); }
.bad { color: var(--danger); }
.band { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 16px; margin-bottom: 14px; box-shadow: var(--shadow); }
.section-head { display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; margin-bottom: 12px; }
.grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-bottom: 14px; }
.stat { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 12px; min-height: 82px; }
.stat b { display: block; font-size: 24px; line-height: 1.1; margin-top: 7px; }
.row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 12px; }
.action-row { justify-content: space-between; align-items: stretch; }
.action-group { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.danger-zone { border: 1px solid #f3c5bd; background: #fff7f5; border-radius: 8px; padding: 8px; }
.danger-zone .mini { color: var(--danger); font-weight: 700; padding: 0 4px; }
.split { display: grid; grid-template-columns: minmax(0, 1fr) minmax(320px, .65fr); gap: 14px; }
.table-wrap { overflow: auto; max-height: 460px; border: 1px solid var(--line); border-radius: 8px; background: white; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { border-bottom: 1px solid var(--line); padding: 8px 9px; text-align: left; vertical-align: top; }
th { position: sticky; top: 0; background: var(--surface-2); color: var(--muted); z-index: 1; font-weight: 700; }
tr:last-child td { border-bottom: 0; }
.pill { display: inline-flex; align-items: center; gap: 5px; border: 1px solid var(--line); border-radius: 999px; padding: 3px 8px; background: var(--surface-2); color: var(--muted); font-size: 12px; }
.pill.ok { background: #ecfdf5; border-color: var(--ok); color: var(--ok); }
.pill.bad { background: #fef3f2; border-color: var(--danger); color: var(--danger); }
.pill.warn-pill { background: #fff7ed; border-color: #fb923c; color: #9a3412; }
.oauth-state { white-space: normal; min-height: 36px; display: inline-flex; align-items: center; padding: 6px 10px; border-radius: 999px; font-size: 12px; border: 1px solid var(--line); background: var(--surface-2); color: var(--muted); }
.oauth-state.ok { background: #ecfdf5; border-color: var(--ok); color: var(--ok); }
.oauth-state.bad { background: #fef3f2; border-color: var(--danger); color: var(--danger); }
.mono { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; overflow-wrap: anywhere; }
.mini { font-size: 12px; color: var(--muted); }
.task-list { display: grid; gap: 8px; }
.task { border: 1px solid var(--line); border-radius: 8px; background: white; padding: 10px; display: grid; grid-template-columns: 1fr auto; gap: 8px; }
.task strong { font-size: 13px; }
.task small { color: var(--muted); }
.task-logs { margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--line); display: grid; gap: 4px; }
.task-log-line { font-size: 12px; color: var(--muted); white-space: normal; word-break: break-word; }
.empty { color: var(--muted); padding: 14px; border: 1px dashed var(--line); border-radius: 8px; background: var(--surface-2); }
@media (max-width: 1280px) {
  .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 1080px) {
  .app { grid-template-columns: 1fr; }
  aside { position: static; height: auto; }
  nav { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .grid, .grid.two, .stats, .split { grid-template-columns: 1fr; }
  main { padding: 14px; }
}
"""


WEBUI_JS = """
const csrf = document.getElementById('csrf').value;
const basePath = (document.body.dataset.basePath || '').replace(/[/]$/, '');
const polling = new Set();
const actionStatus = {
  remote_scan: 'remote_status',
  oauth_blind_import: 'oauth_status',
  privacy: 'remote_status',
  delete_no_quota: 'remote_status',
  delete_auth_error: 'remote_status',
  delete_dead: 'remote_status',
  low_quota_policy: 'acc_status',
  convert: 'convert_status',
  import_cached: 'convert_status',
  import_text: 'convert_status'
};
const actionNames = {
  remote_scan: '远程扫描',
  oauth_blind_import: '一键注册登录导入',
  privacy: '同步隐私',
  delete_no_quota: '删无额度',
  delete_auth_error: '删 401',
  delete_dead: '删死号',
  low_quota_policy: '席位策略',
  convert: '转换校验',
  import_cached: '上传缓存',
  import_text: '上传粘贴内容'
};
let blindOauthSeatBlocked = false;
let blindOauthTaskBlocked = false;

function byId(id) { return document.getElementById(id); }
function formValue(id) { const el = byId(id); return el ? el.value.trim() : ''; }
function withBase(path) {
  if (!basePath || !path.startsWith('/')) return path;
  return basePath + path;
}
function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s]));
}
function setText(id, text, bad=false) {
  const el = byId(id);
  if (!el) return;
  el.textContent = text || '';
  el.className = bad ? 'status bad' : 'status ok';
}
function setStat(id, value) {
  const el = byId(id);
  if (el) el.textContent = value ?? '--';
}
function setBusy(action, busy) {
  document.querySelectorAll(`[data-action="${action}"]`).forEach(button => {
    button.disabled = Boolean(busy);
  });
  if (action === 'oauth_blind_import') {
    blindOauthTaskBlocked = Boolean(busy);
    updateBlindOauthButton();
  }
}
function updateBlindOauthButton() {
  const button = document.querySelector('[data-action="oauth_blind_import"]');
  if (!button) return;
  const disabled = blindOauthSeatBlocked || blindOauthTaskBlocked;
  button.disabled = disabled;
  if (blindOauthSeatBlocked) {
    button.title = '当前 ChatGPT 席位已满 2/2，禁止一键建号';
  } else if (blindOauthTaskBlocked) {
    button.title = '当前已有建号任务正在运行';
  } else {
    button.title = '';
  }
}
function replaceSelectOptions(id, options, currentValue) {
  const el = byId(id);
  if (!el) return;
  const selectedValue = String(currentValue ?? el.dataset.current ?? el.value ?? '');
  el.innerHTML = '';
  let matched = false;
  (options || []).forEach(item => {
    const option = document.createElement('option');
    option.value = String(item.value ?? '');
    option.textContent = String(item.label ?? item.value ?? '');
    if (option.value === selectedValue) {
      option.selected = true;
      matched = true;
    }
    el.appendChild(option);
  });
  if (!matched && selectedValue) {
    const option = document.createElement('option');
    option.value = selectedValue;
    option.textContent = `当前：${selectedValue}`;
    option.selected = true;
    el.appendChild(option);
  }
  el.dataset.current = el.value;
}
function syncOauthProxyName(proxyOptions, selectedProxyId='') {
  return;
}
async function api(path, body={}) {
  const res = await fetch(withBase(path), {
    method: 'POST',
    headers: {'Content-Type':'application/json', 'X-CSRF-Token': csrf},
    body: JSON.stringify(body)
  });
  const data = await res.json();
  if (!res.ok || data.ok === false) throw new Error(data.error || res.statusText);
  return data;
}

async function saveConfig() {
  try {
    const config = {
      SUB2API_BASE_URL: formValue('cfg_base_url'),
      SUB2API_GROUP_IDS: formValue('cfg_group_ids'),
      SUB2API_PROXY_ID: formValue('cfg_proxy_id'),
      SUB2API_OUTBOUND_PROXY_URL: formValue('cfg_outbound_proxy'),
      SUB2API_VALIDATE_CONCURRENCY: formValue('cfg_validate_concurrency_config'),
      SUB2API_WEB_PORT: formValue('cfg_web_port'),
      SUB2API_WEB_HOST: formValue('cfg_web_host'),
      SUB2API_WEB_PUBLIC_BASE_URL: formValue('cfg_public_base_url'),
      SUB2API_AUTO_POLICY_ENABLED: formValue('cfg_auto_policy_enabled'),
      SUB2API_AUTO_POLICY_INTERVAL_SECONDS: formValue('cfg_auto_policy_interval'),
      SUB2API_AUTO_POLICY_RUN_ON_START: formValue('cfg_auto_policy_run_on_start'),
      ACC_BACKEND_EMAIL_TEMPLATE: formValue('cfg_acc_backend_email_template'),
      ACC_BACKEND_EMAIL_START_INDEX: formValue('cfg_acc_backend_email_start')
    };
    const adminApiKey = formValue('cfg_api_key');
    if (adminApiKey) config.SUB2API_ADMIN_API_KEY = adminApiKey;
    const webSecret = formValue('cfg_web_secret');
    if (webSecret) config.SUB2API_WEB_SECRET = webSecret;
    const pushplusToken = formValue('cfg_pushplus_token');
    if (pushplusToken) config.PUSHPLUS_TOKEN = pushplusToken;
    await api('/api/config/save', config);
    setText('config_status', '配置已保存');
    setStat('stat_proxy', formValue('cfg_outbound_proxy') ? '代理 已配置' : '代理 未配置');
  } catch(e) {
    setText('config_status', e.message, true);
  }
}

async function testRemote() {
  try {
    const data = await api('/api/remote/test', {});
    setText('config_status', 'Sub2API 连接成功');
    setStat('stat_remote', data.result.account_total ?? 'OK');
    loadRemoteResources(true);
  } catch(e) {
    setText('config_status', e.message, true);
  }
}

async function loadRemoteResources(silent=false) {
  try {
    const data = await api('/api/remote/resources', {
      base_url: formValue('cfg_base_url'),
      admin_api_key: formValue('cfg_api_key')
    });
    const result = data.result || {};
    const groups = result.groups || [];
    const proxies = result.proxies || [];
    replaceSelectOptions('cfg_group_ids', groups, byId('cfg_group_ids')?.dataset.current || formValue('cfg_group_ids'));
    replaceSelectOptions('cfg_proxy_id', proxies, byId('cfg_proxy_id')?.dataset.current || formValue('cfg_proxy_id'));
    replaceSelectOptions('oauth_group_ids', groups, byId('oauth_group_ids')?.dataset.current || formValue('oauth_group_ids'));
    replaceSelectOptions('oauth_proxy_id', proxies, byId('oauth_proxy_id')?.dataset.current || formValue('oauth_proxy_id'));
    syncOauthProxyName(proxies, byId('oauth_proxy_id')?.value || '');
    if (!silent) setText('config_status', '分组和代理已刷新');
  } catch(e) {
    if (!silent) setText('config_status', e.message, true);
  }
}

async function startTask(action) {
  const importJson = byId('import_json_text');
  const statusId = actionStatus[action] || 'task_status';
  try {
    setBusy(action, true);
    setText(statusId, `${actionNames[action] || action} 已提交`);
    const data = await api('/api/tasks/start', {
      action,
      input_path: formValue('convert_input_path'),
      output_mode: formValue('convert_output_mode'),
      payload_text: importJson ? importJson.value : '',
      account_name: formValue('oauth_account_name'),
      public_base_url: formValue('oauth_public_base_url'),
      proxy_id: formValue('oauth_proxy_id'),
      proxy_url: formValue('oauth_proxy_url'),
      group_ids: formValue('oauth_group_ids'),
      concurrency: formValue('oauth_concurrency')
    });
    const taskId = data.task_id || (data.result && data.result.task_id);
    if (!taskId) throw new Error('任务接口没有返回 task_id');
    pollTask(taskId, action);
    loadTasks();
  } catch(e) {
    setBusy(action, false);
    setText(statusId, e.message, true);
  }
}

async function pollTask(id, action='') {
  if (polling.has(id)) return;
  polling.add(id);
  while (true) {
    const res = await fetch(withBase('/api/tasks/get?id=' + encodeURIComponent(id)));
    const task = await res.json();
    if (task.status !== 'running' && task.status !== 'queued') {
      polling.delete(id);
      setBusy(action || task.label, false);
      renderTaskResult(task);
      loadTasks();
      return;
    }
    await new Promise(r => setTimeout(r, 900));
  }
}

function renderTaskResult(task) {
  const statusId = actionStatus[task.label] || 'task_status';
  if (task.status === 'error') {
    if (task.label === 'oauth_blind_import') {
      byId('oauth_state_text').textContent = '一键导入失败';
      byId('oauth_state_text').className = 'oauth-state bad';
    }
    setText(statusId, `${actionNames[task.label] || task.label} 失败：${task.error}`, true);
    return;
  }
  const result = task.result || {};
  if (task.label === 'remote_scan') renderRemoteSummary(result);
  if (task.label === 'oauth_blind_import') {
    const accountId = result.account_id || '--';
    byId('oauth_state_text').textContent = '一键导入完成 #' + accountId;
    byId('oauth_state_text').className = 'oauth-state ok';
    setText('oauth_status', '一键导入完成 #' + accountId + (result.account_email ? ' / ' + result.account_email : ''));
  }
  if (task.label === 'convert') {
    setText('convert_status', `转换完成：可用 ${result.usable_count}/${result.total_candidates}，并发 ${result.validate_concurrency}`);
  }
  if (task.label.startsWith('delete')) {
    setText('remote_status', `${actionNames[task.label]} 完成`);
    startTask('remote_scan');
  }
  if (task.label === 'privacy') setText('remote_status', '隐私同步完成');
  if (task.label.startsWith('import')) setText('convert_status', '导入完成');
  if (task.label === 'low_quota_policy') {
    renderMembers(result.members || []);
    const changed = (result.changed_members || []).length;
    const replaced = (result.blind_import_results || []).filter(item => item.success).length;
    const capped = (result.limit_changed_members || []).length;
    const protectedMother = (result.protected_mother_members || []).length;
    setText('acc_status', `策略完成：低额度 ${result.low_quota_count ?? 0}，改 Codex ${changed + capped + protectedMother}，自动补新号 ${replaced}，ChatGPT ${result.chatgpt_count ?? '--'}/${result.chatgpt_limit ?? 2}`);
    setStat('stat_chatgpt', `${result.chatgpt_count ?? '--'}/${result.chatgpt_limit ?? 2}`);
    setStat('stat_low', result.low_quota_count ?? 0);
    loadPolicyEvents();
  }
}

function confirmTask(action, message) {
  if (confirm(message)) startTask(action);
}

function renderRemoteSummary(r) {
  setText('remote_status', `远程 ${r.total_count} | 活 ${r.alive_count} | 死 ${r.dead_count} | 无额度 ${r.no_quota_count} | 均额 ${r.average_remaining_quota}%`);
  setStat('stat_remote', r.total_count ?? 0);
  const rows = (r.dead_items || []).concat(r.no_quota_items || []).slice(0, 120).map(item =>
    `<tr><td class="mono">${esc(item.account_id)}</td><td>${esc(item.name)}</td><td>${esc(item.email)}</td><td>${esc(item.status)}</td><td>${esc(item.reason)}</td></tr>`
  ).join('');
  byId('remote_summary').innerHTML = rows
    ? `<div class="table-wrap"><table><thead><tr><th>ID</th><th>账号</th><th>邮箱</th><th>状态</th><th>原因</th></tr></thead><tbody>${rows}</tbody></table></div>`
    : '<div class="empty">没有需要展示的异常账号</div>';
}

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
function startBlindOauthImport() {
  byId('oauth_state_text').textContent = '服务器自动执行中';
  byId('oauth_state_text').className = 'oauth-state';
  setText('oauth_status', '正在自动注册、登录并导入 Sub2API');
  startTask('oauth_blind_import');
}
function startOauthPolling() {
  if (oauthPollTimer) return;
  oauthPollTimer = setInterval(pollOauthStatus, 2000);
}
function stopOauthPolling() {
  if (oauthPollTimer) {
    clearInterval(oauthPollTimer);
    oauthPollTimer = null;
  }
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
      stateEl.textContent = '等待开始';
      stateEl.className = 'oauth-state';
      startBtn.disabled = false;
      startBtn.textContent = '开始授权建号';
      resetBtn.style.display = 'none';
      break;
    case 'waiting_callback':
      stateEl.textContent = '已生成授权链接，请在新窗口完成登录授权';
      stateEl.className = 'oauth-state';
      startBtn.disabled = true;
      startBtn.textContent = '等待授权中...';
      resetBtn.style.display = '';
      break;
    case 'creating_account':
      stateEl.textContent = '已收到回调，正在创建 Sub2API 账号';
      stateEl.className = 'oauth-state';
      startBtn.disabled = true;
      startBtn.textContent = '创建账号中...';
      resetBtn.style.display = '';
      break;
    case 'done':
      stateEl.textContent = '建号完成 #' + (result.account_id || '--');
      stateEl.className = 'oauth-state ok';
      startBtn.disabled = false;
      startBtn.textContent = '开始授权建号';
      resetBtn.style.display = '';
      setText('oauth_status', '建号完成 #' + (result.account_id || '--'));
      break;
    case 'error':
      stateEl.textContent = '错误：' + (result.error || '未知');
      stateEl.className = 'oauth-state bad';
      startBtn.disabled = false;
      startBtn.textContent = '开始授权建号';
      resetBtn.style.display = '';
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
  } catch(e) {
    setText('oauth_status', e.message, true);
  }
}

async function copyCachedPayload() {
  const res = await fetch(withBase('/api/conversion/payload'));
  const data = await res.json();
  await navigator.clipboard.writeText(data.payload || '');
  setText('convert_status', '缓存 JSON 已复制');
}

async function applyAcc() {
  try {
    const data = await api('/api/acc/apply', {payload: byId('acc_payload').value});
    setText('acc_status', 'ACC 已保存 account_id=' + data.result.account_id);
  } catch(e) {
    setText('acc_status', e.message, true);
  }
}
async function loadMembers() {
  try {
    const data = await api('/api/acc/members', {});
    renderMembers(data.result.items || []);
    const usageError = data.result.usage_error || '';
    setText('acc_status', usageError ? `已加载成员 ${data.result.total}，但额度刷新失败：${usageError}` : '已加载成员 ' + data.result.total, Boolean(usageError));
  } catch(e) {
    setText('acc_status', e.message, true);
  }
}
function seatName(seatType) {
  const text = String(seatType || '');
  if (text === 'usage_based') return 'Codex';
  if (text === 'default' || text === 'null') return 'ChatGPT';
  return text || '--';
}
const ACC_MOTHER_USER_ID = 'user-s48XGo8NpCt5xv9XoI3b0w4z';
function renderMembers(items) {
  const chatgptItems = (items || []).filter(u => ['default', 'null'].includes(String(u.seat_type || '')));
  const chatgptCount = chatgptItems.length;
  blindOauthSeatBlocked = chatgptCount >= 2;
  updateBlindOauthButton();
  setStat('stat_chatgpt', `${chatgptCount}/2`);
  const rows = chatgptItems.map(u => {
    const seat = seatName(u.seat_type);
    const isCodex = seat === 'Codex';
    const isMother = String(u.id || '') === ACC_MOTHER_USER_ID;
    const badges = isMother ? '<span class="pill warn-pill">母号</span> <span class="pill">受保护</span>' : '';
    const actionLabel = isMother && isCodex ? '已保护' : '改 Codex';
    return `<tr><td class="mono">${esc(u.id)}</td><td>${esc(u.email)} ${badges}</td><td><span class="pill">${esc(seat)}</span></td><td>${esc(u.quota_current || '--')}</td><td>${esc(u.quota_5h || '--')}</td><td>${esc(u.quota_5h_eta || '--')}</td><td>${esc(u.quota_7d || '--')}</td><td>${esc(u.quota_7d_eta || '--')}</td><td>${esc(u.quota_31d || '--')}</td><td>${esc(u.quota_31d_eta || '--')}</td><td>${esc(u.quota_updated_at || '--')}</td><td><button class="secondary seat-action" ${isCodex ? 'disabled' : ''} data-user-id="${esc(u.id)}" data-email="${esc(u.email)}">${actionLabel}</button></td></tr>`;
  }).join('');
  byId('acc_members').innerHTML = rows
    ? `<div class="table-wrap"><table><thead><tr><th>User ID</th><th>邮箱</th><th>席位</th><th>当前额度</th><th>5h额度</th><th>5h预计用完</th><th>7天额度</th><th>7天预计用完</th><th>31天额度</th><th>31天预计用完</th><th>更新时间</th><th>操作</th></tr></thead><tbody>${rows}</tbody></table></div>`
    : '<div class="empty">暂无 ChatGPT 席位成员</div>';
  document.querySelectorAll('.seat-action').forEach(button => {
    button.addEventListener('click', () => seat(button.dataset.userId || '', button.dataset.email || '', 'usage_based'));
  });
}
async function seat(user_id, email, seat_type) {
  try {
    const data = await api('/api/acc/seat', {user_id, email, seat_type});
    renderMembers(data.result.members || []);
    setText('acc_status', '席位已更新');
  } catch(e) {
    setText('acc_status', e.message, true);
  }
}

function formatTaskTime(task) {
  const started = Number(task.started_at || task.created_at || 0) * 1000;
  const finished = Number(task.finished_at || 0) * 1000;
  if (!started) return '--';
  if (!finished) return '运行中';
  return Math.max(0, Math.round((finished - started) / 1000)) + 's';
}
function formatSchedulerTime(ts) {
  const value = Number(ts || 0);
  if (!value) return '--';
  const seconds = Math.max(0, Math.round(value - Date.now() / 1000));
  if (seconds <= 0) return '即将执行';
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}min`;
  return `${Math.round(seconds / 3600)}h`;
}
function renderSchedulerStatus(scheduler) {
  const status = scheduler || {};
  const el = byId('scheduler_status');
  if (!el) return;
  if (status.enabled === false) {
    el.textContent = '自动策略：关闭';
    return;
  }
  const suffix = status.skipped_reason
    ? ` | ${status.skipped_reason}`
    : ` | 下次 ${formatSchedulerTime(status.next_run_at)}`;
  el.textContent = `自动策略：${status.interval_seconds || '--'}s${suffix}`;
}
function renderBlindOauthTask(task) {
  const container = byId('oauth_blind_log');
  if (!container) return;
  if (!task) {
    container.innerHTML = '<div class="empty">等待一键导入任务开始</div>';
    return;
  }
  const logs = (task.logs || []).map(line => `<div class="task-log-line">${esc(line)}</div>`).join('');
  const summary = Object.entries(task.result_summary || {}).map(([k, v]) => `${k}:${v}`).join(' ');
  container.innerHTML = `<div class="task"><div><strong>${esc(actionNames[task.label] || task.label)}</strong><br><small>${esc(summary || task.error || task.id)}</small>${logs ? `<div class="task-logs">${logs}</div>` : ''}</div><div><span class="pill">${esc(task.status)}</span><br><small>${formatTaskTime(task)}</small></div></div>`;
}
async function loadTasks() {
  const res = await fetch(withBase('/api/tasks/list'));
  const data = await res.json();
  renderSchedulerStatus(data.scheduler || {});
  const tasks = data.tasks || [];
  blindOauthTaskBlocked = tasks.some(task => task.label === 'oauth_blind_import' && ['queued', 'running'].includes(task.status));
  updateBlindOauthButton();
  const blindTask = tasks.find(task => task.label === 'oauth_blind_import') || null;
  renderBlindOauthTask(blindTask);
  const normalTasks = tasks.filter(task => task.label !== 'oauth_blind_import');
  if (!normalTasks.length) {
    byId('task_log').innerHTML = '<div class="empty">暂无任务</div>';
    return;
  }
  byId('task_log').innerHTML = '<div class="task-list">' + normalTasks.slice(0, 12).map(task => {
    const summary = Object.entries(task.result_summary || {}).map(([k, v]) => `${k}:${v}`).join(' ');
    const logs = (task.logs || []).map(line => `<div class="task-log-line">${esc(line)}</div>`).join('');
    return `<div class="task"><div><strong>${esc(actionNames[task.label] || task.label)}</strong><br><small>${esc(summary || task.error || task.id)}</small>${logs ? `<div class="task-logs">${logs}</div>` : ''}</div><div><span class="pill">${esc(task.status)}</span><br><small>${formatTaskTime(task)}</small></div></div>`;
  }).join('') + '</div>';
}
function formatEventTime(ts) {
  const value = Number(ts || 0);
  if (!value) return '--';
  return new Date(value * 1000).toLocaleString();
}
function policyActionName(action) {
  return ({
    demote_codex: '降为 Codex',
    promote_chatgpt: '补为 ChatGPT',
    invite_member: '添加成员',
    delete_invalidated: '清理 401',
    policy_error: '策略错误',
    pushplus_error: '推送失败',
    acc_credentials_recovered: 'ACC 恢复'
  })[action] || action || '--';
}
async function loadPolicyEvents() {
  try {
    const data = await api('/api/policy/events', {limit: 100});
    const items = data.result.items || [];
    const rows = items.map(item =>
      `<tr><td>${esc(formatEventTime(item.created_at))}</td><td>${esc(policyActionName(item.action))}</td><td>${esc(item.email || '--')}</td><td class="mono">${esc(item.account_id ?? '--')}</td><td>${esc(item.reason || '--')}</td><td><span class="pill">${esc(item.result || '--')}</span></td></tr>`
    ).join('');
    byId('policy_event_log').innerHTML = rows
      ? `<div class="table-wrap"><table><thead><tr><th>时间</th><th>动作</th><th>账号</th><th>Sub2API ID</th><th>原因</th><th>结果</th></tr></thead><tbody>${rows}</tbody></table></div>`
      : '<div class="empty">暂无更换记录</div>';
  } catch(e) {
    byId('policy_event_log').innerHTML = `<div class="empty">加载失败：${esc(e.message)}</div>`;
  }
}
async function bootstrapDashboard() {
  loadRemoteResources(true);
  try {
    await loadMembers();
  } catch (e) {}
  try {
    await startTask('remote_scan');
  } catch (e) {}
}
loadTasks();
loadPolicyEvents();
bootstrapDashboard();
setInterval(loadTasks, 6000);
setInterval(loadPolicyEvents, 15000);
"""
