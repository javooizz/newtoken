"""Inline CSS and browser-side JavaScript for the dependency-light WebUI."""

from __future__ import annotations

WEBUI_CSS = """
:root {
  --bg: #edf2f7;
  --surface: #ffffff;
  --surface-2: #f8fafc;
  --line: #d7dee8;
  --text: #172033;
  --muted: #647083;
  --brand: #145c62;
  --brand-2: #0f4f54;
  --blue: #22577a;
  --warn: #9a3412;
  --danger: #b42318;
  --ok: #087443;
  --shadow: 0 14px 30px rgba(22, 31, 45, .08);
}
* { box-sizing: border-box; }
html { scroll-behavior: smooth; }
body { margin: 0; font-family: system-ui, -apple-system, Segoe UI, sans-serif; background: var(--bg); color: var(--text); }
button, input, textarea, select { font: inherit; }
button { border: 0; border-radius: 6px; background: var(--brand); color: white; padding: 9px 12px; cursor: pointer; min-height: 36px; }
button:hover { background: var(--brand-2); }
button.secondary { background: var(--blue); }
button.warn { background: var(--warn); }
button.danger { background: var(--danger); }
button.ghost { background: transparent; color: var(--text); border: 1px solid var(--line); }
button:disabled { opacity: .58; cursor: wait; }
input, textarea, select { width: 100%; border: 1px solid var(--line); border-radius: 6px; background: white; color: var(--text); padding: 9px 10px; outline: none; }
input:focus, textarea:focus, select:focus { border-color: var(--brand); box-shadow: 0 0 0 3px rgba(20, 92, 98, .12); }
textarea { min-height: 126px; resize: vertical; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 13px; line-height: 1.45; }
label { display: block; color: var(--muted); font-size: 12px; margin-bottom: 5px; }
.app { min-height: 100vh; display: grid; grid-template-columns: 236px minmax(0, 1fr); }
aside { position: sticky; top: 0; height: 100vh; padding: 18px; background: #162334; color: white; }
.brand { font-size: 18px; font-weight: 750; margin-bottom: 4px; }
.sub { color: #cbd5e1; font-size: 12px; line-height: 1.5; overflow-wrap: anywhere; }
nav { display: grid; gap: 6px; margin-top: 22px; }
nav a { color: #e5edf6; text-decoration: none; padding: 9px 10px; border-radius: 6px; font-size: 14px; }
nav a:hover { background: rgba(255, 255, 255, .1); }
main { min-width: 0; padding: 22px; }
.topbar { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin: 14px 0 16px; }
h1 { font-size: 24px; margin: 0 0 4px; }
h2 { font-size: 17px; margin: 0; }
h3 { font-size: 14px; margin: 0 0 10px; }
.meta { color: var(--muted); font-size: 13px; }
.status { color: var(--muted); font-size: 13px; min-height: 20px; }
.ok { color: var(--ok); }
.bad { color: var(--danger); }
.band { background: var(--surface); border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); padding: 16px; margin-bottom: 14px; box-shadow: var(--shadow); }
.section-head { display: flex; justify-content: space-between; gap: 12px; align-items: center; margin-bottom: 12px; }
.grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-bottom: 14px; }
.stat, .panel { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 12px; min-height: 82px; }
.stat b { display: block; font-size: 24px; line-height: 1.1; margin-top: 7px; }
.row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 12px; }
.split { display: grid; grid-template-columns: minmax(0, 1fr) minmax(320px, .65fr); gap: 14px; }
.config-stack { display: grid; gap: 14px; }
.config-group { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: var(--surface-2); }
.field-wide { margin-top: 12px; }
.table-wrap { overflow: auto; max-height: 460px; border: 1px solid var(--line); border-radius: 8px; background: white; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { border-bottom: 1px solid var(--line); padding: 8px 9px; text-align: left; vertical-align: top; }
th { position: sticky; top: 0; background: var(--surface-2); color: var(--muted); z-index: 1; font-weight: 700; }
tr:last-child td { border-bottom: 0; }
.pill { display: inline-flex; align-items: center; gap: 5px; border: 1px solid var(--line); border-radius: 999px; padding: 3px 8px; background: var(--surface-2); color: var(--muted); font-size: 12px; }
.pill.ok { background: #ecfdf5; border-color: var(--ok); color: var(--ok); }
.pill.bad { background: #fef3f2; border-color: var(--danger); color: var(--danger); }
.mono { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; overflow-wrap: anywhere; }
.mini { font-size: 12px; color: var(--muted); }
.task-list { display: grid; gap: 8px; }
.task { border: 1px solid var(--line); border-radius: 8px; background: white; padding: 10px; display: grid; grid-template-columns: 1fr auto; gap: 8px; }
.task strong { font-size: 13px; }
.task small { color: var(--muted); }
.empty { color: var(--muted); padding: 14px; border: 1px dashed var(--line); border-radius: 8px; background: var(--surface-2); }
.banner { display: flex; justify-content: space-between; gap: 12px; align-items: center; padding: 14px 16px; border: 1px solid var(--line); border-radius: 8px; margin-bottom: 14px; background: white; box-shadow: var(--shadow); }
.banner.ok { border-color: rgba(8,116,67,.25); }
.banner.bad { border-color: rgba(180,35,24,.28); }
.shell.hidden { opacity: .45; pointer-events: none; filter: grayscale(.08); }
@media (max-width: 1280px) {
  .grid, .grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
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
let polling = new Set();
const actionStatus = {
  remote_scan: 'remote_status',
  privacy: 'remote_status',
  delete_no_quota: 'remote_status',
  delete_auth_error: 'remote_status',
  delete_dead: 'remote_status',
  low_quota_policy: 'acc_status',
  auto_maintenance: 'maintenance_status',
  convert: 'convert_status',
  import_cached: 'convert_status',
  import_text: 'convert_status'
};
const actionNames = {
  remote_scan: '远程扫描',
  privacy: '隐私同步',
  delete_no_quota: '删除无额度',
  delete_auth_error: '删除 401',
  delete_dead: '删除死号',
  low_quota_policy: '席位策略',
  auto_maintenance: '自动维护',
  convert: '转换校验',
  import_cached: '缓存导入',
  import_text: '粘贴导入'
};
function byId(id) { return document.getElementById(id); }
function formValue(id) { const el = byId(id); return el ? el.value.trim() : ''; }
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
}
async function api(path, body={}) {
  const res = await fetch(path, {
    method: 'POST',
    headers: {'Content-Type':'application/json', 'X-CSRF-Token': csrf},
    body: JSON.stringify(body)
  });
  const data = await res.json();
  if (!res.ok || data.ok === false) throw new Error(data.error || res.statusText);
  return data;
}
function buildConfigPayload() {
  const config = {
    SUB2API_BASE_URL: formValue('cfg_base_url'),
    SUB2API_GROUP_IDS: formValue('cfg_group_ids'),
    SUB2API_PROXY_ID: formValue('cfg_proxy_id'),
    SUB2API_OUTBOUND_PROXY_URL: formValue('cfg_outbound_proxy'),
    SUB2API_IMPORT_CONCURRENCY: formValue('cfg_import_concurrency'),
    SUB2API_VALIDATE_CONCURRENCY: formValue('cfg_validate_concurrency'),
    SUB2API_WEB_PORT: formValue('cfg_web_port'),
    SUB2API_WEB_HOST: formValue('cfg_web_host'),
    SUB2API_WEB_PUBLIC_BASE_URL: formValue('cfg_public_base_url'),
    SUB2API_AUTO_POLICY_ENABLED: formValue('cfg_auto_policy_enabled'),
    SUB2API_AUTO_POLICY_INTERVAL_SECONDS: formValue('cfg_auto_policy_interval'),
    SUB2API_AUTO_POLICY_RUN_ON_START: formValue('cfg_auto_policy_run_on_start'),
    ACC_MOTHER_ACCOUNT_EMAIL: formValue('cfg_mother_email'),
    SUB2API_OIDC_API_URL: formValue('cfg_oidc_api_url'),
    SUB2API_AUTO_REGISTER_ENABLED: formValue('cfg_auto_register_enabled'),
    SUB2API_AUTO_REGISTER_COUNT: formValue('cfg_auto_register_count'),
    SUB2API_AUTO_REGISTER_THRESHOLD: formValue('cfg_auto_register_threshold'),
    SUB2API_AUTO_REGISTER_DOMAIN: formValue('cfg_auto_register_domain')
  };
  const adminApiKey = formValue('cfg_api_key');
  if (adminApiKey) config.SUB2API_ADMIN_API_KEY = adminApiKey;
  const webSecret = formValue('cfg_web_secret');
  if (webSecret) config.SUB2API_WEB_SECRET = webSecret;
  const accPayload = formValue('cfg_acc_payload');
  if (accPayload) config.ACC_PAYLOAD = accPayload;
  const oidcApiKey = formValue('cfg_oidc_api_key');
  if (oidcApiKey) config.SUB2API_OIDC_API_KEY = oidcApiKey;
  config.SUB2API_SETUP_DONE = 'true';
  return config;
}
async function saveConfig() {
  try {
    await api('/api/config/save', buildConfigPayload());
    setText('setup_status', '安装配置已保存');
    setText('config_status', '配置已保存');
    if (byId('shell')) byId('shell').className = 'shell visible';
    window.location.reload();
  } catch(e) {
    setText('setup_status', e.message, true);
    setText('config_status', e.message, true);
  }
}
async function testRemote() {
  try {
    const data = await api('/api/remote/test', {});
    setText('setup_status', 'Sub2API 连接成功');
    setStat('stat_remote', data.result.account_total ?? 'OK');
  } catch(e) { setText('setup_status', e.message, true); }
}
async function testOidc() {
  try {
    const data = await api('/api/oidc/test', {});
    const result = data.result || {};
    const failed = result.ok === false;
    setText('setup_status', failed ? (result.error || 'OIDC 未就绪') : 'OIDC 连接成功', failed);
  } catch(e) { setText('setup_status', e.message, true); }
}
async function startTask(action) {
  const body = {
    action,
    input_path: formValue('convert_input_path'),
    output_mode: formValue('convert_output_mode'),
    payload_text: byId('import_json_text').value
  };
  const statusId = actionStatus[action] || 'task_status';
  try {
    setBusy(action, true);
    setText(statusId, `${actionNames[action] || action} 已提交`);
    const data = await api('/api/tasks/start', body);
    pollTask(data.task_id, action);
    loadTasks();
  } catch(e) {
    setBusy(action, false);
    setText(statusId, e.message, true);
  }
}
function confirmTask(action, message) { if (confirm(message)) startTask(action); }
async function pollTask(id, action='') {
  if (polling.has(id)) return;
  polling.add(id);
  while (true) {
    const res = await fetch('/api/tasks/get?id=' + encodeURIComponent(id));
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
    setText(statusId, `${actionNames[task.label] || task.label} 失败：${task.error}`, true);
    return;
  }
  const result = task.result || {};
  if (task.label === 'remote_scan') renderRemoteSummary(result);
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
    const capped = (result.limit_changed_members || []).length;
    setText('acc_status', `策略完成：低额度 ${result.low_quota_count}，改 Codex ${changed + capped}，ChatGPT ${result.chatgpt_count}/${result.chatgpt_limit}`);
    setStat('stat_chatgpt', `${result.chatgpt_count}/${result.chatgpt_limit}`);
    setStat('stat_low', result.low_quota_count ?? 0);
  }
  if (task.label === 'auto_maintenance') {
    const phases = Array.isArray(result.phases) ? result.phases : [];
    const summary = phases.map(p => `${p.phase || '--'}:${p.skipped ? 'skip' : p.error ? 'err' : 'ok'}`).join(' | ');
    byId('maintenance_summary').textContent = summary || '自动维护完成';
    setText('maintenance_status', result.errors && result.errors.length ? '自动维护有错误' : '自动维护完成', Array.isArray(result.errors) && result.errors.length > 0);
  }
}
function renderRemoteSummary(r) {
  setText('remote_status', `远程 ${r.total_count} | 活 ${r.alive_count} | 死 ${r.dead_count} | 无额度 ${r.no_quota_count} | 均额 ${r.average_remaining_quota}%`);
  setStat('stat_remote', r.total_count ?? 0);
  setStat('stat_dead', r.dead_count ?? 0);
  const rows = (r.dead_items || []).concat(r.no_quota_items || []).slice(0, 120).map(item =>
    `<tr><td class="mono">${esc(item.account_id)}</td><td>${esc(item.name)}</td><td>${esc(item.email)}</td><td>${esc(item.status)}</td><td>${esc(item.reason)}</td></tr>`
  ).join('');
  byId('remote_summary').innerHTML = rows
    ? `<div class="table-wrap"><table><thead><tr><th>ID</th><th>账号</th><th>邮箱</th><th>状态</th><th>原因</th></tr></thead><tbody>${rows}</tbody></table></div>`
    : '<div class="empty">没有需要展示的异常账号</div>';
}
function esc(v) { return String(v ?? '').replace(/[&<>"']/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s])); }
async function copyCachedPayload() {
  const res = await fetch('/api/conversion/payload');
  const data = await res.json();
  await navigator.clipboard.writeText(data.payload || '');
  setText('convert_status', '缓存 JSON 已复制');
}
async function applyAcc() {
  try {
    const data = await api('/api/acc/apply', {payload: byId('acc_payload').value});
    setText('acc_status', 'ACC 已保存 account_id=' + data.result.account_id);
  } catch(e) { setText('acc_status', e.message, true); }
}
async function loadMembers() {
  try {
    const data = await api('/api/acc/members', {});
    renderMembers(data.result.items || []);
    setText('acc_status', '已加载成员 ' + data.result.total);
  } catch(e) { setText('acc_status', e.message, true); }
}
function seatName(seatType) {
  const text = String(seatType || '');
  if (text === 'usage_based') return 'Codex';
  if (text === 'default' || text === 'null') return 'ChatGPT';
  return text || '--';
}
function renderMembers(items) {
  const chatgptCount = items.filter(u => ['default', 'null'].includes(String(u.seat_type || ''))).length;
  setStat('stat_chatgpt', `${chatgptCount}/2`);
  const rows = items.map(u => {
    const seat = seatName(u.seat_type);
    const isCodex = seat === 'Codex';
    return `<tr><td class="mono">${esc(u.id)}</td><td>${esc(u.email)}</td><td><span class="pill">${esc(seat)}</span></td><td><button class="secondary seat-action" ${isCodex ? 'disabled' : ''} data-user-id="${esc(u.id)}">改 Codex</button></td></tr>`;
  }).join('');
  byId('acc_members').innerHTML = rows
    ? `<div class="table-wrap"><table><thead><tr><th>User ID</th><th>邮箱</th><th>席位</th><th>操作</th></tr></thead><tbody>${rows}</tbody></table></div>`
    : '<div class="empty">暂无成员数据</div>';
  document.querySelectorAll('.seat-action').forEach(button => {
    button.addEventListener('click', () => seat(button.dataset.userId || '', '', 'usage_based'));
  });
}
async function seat(user_id, email, seat_type) {
  try {
    const data = await api('/api/acc/seat', {user_id, email, seat_type});
    renderMembers(data.result.members || []);
    setText('acc_status', '席位已更新');
  } catch(e) { setText('acc_status', e.message, true); }
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
    el.textContent = '自动维护：关闭';
    return;
  }
  const suffix = status.skipped_reason
    ? ` | ${status.skipped_reason}`
    : ` | 下次 ${formatSchedulerTime(status.next_run_at)}`;
  el.textContent = `自动维护：${status.interval_seconds || '--'}s${suffix}`;
}
async function loadTasks() {
  const res = await fetch('/api/tasks/list');
  const data = await res.json();
  renderSchedulerStatus(data.scheduler || {});
  const tasks = data.tasks || [];
  if (!tasks.length) {
    byId('task_log').innerHTML = '<div class="empty">暂无任务</div>';
    return;
  }
  byId('task_log').innerHTML = '<div class="task-list">' + tasks.slice(0, 12).map(task => {
    const summary = Object.entries(task.result_summary || {}).map(([k, v]) => `${k}:${v}`).join(' ');
    return `<div class="task"><div><strong>${esc(actionNames[task.label] || task.label)}</strong><br><small>${esc(summary || task.error || task.id)}</small></div><div><span class="pill">${esc(task.status)}</span><br><small>${formatTaskTime(task)}</small></div></div>`;
  }).join('') + '</div>';
}
loadTasks();
setInterval(loadTasks, 6000);
"""
