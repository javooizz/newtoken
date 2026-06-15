"""ACC / members JavaScript for the WebUI."""

from __future__ import annotations

WEBUI_ACC_JS = """
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
"""
