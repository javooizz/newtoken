"""Inline CSS for the dependency-light WebUI."""

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
  --shadow: 0 16px 34px rgba(22, 31, 45, .08);
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
.stat { background: var(--surface); border: 1px solid var(--line); border-radius: 8px; padding: 12px; min-height: 82px; }
.stat b { display: block; font-size: 24px; line-height: 1.1; margin-top: 7px; }
.row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 12px; }
.split { display: grid; grid-template-columns: minmax(0, 1fr) minmax(320px, .65fr); gap: 14px; }
.table-wrap { overflow: auto; max-height: 460px; border: 1px solid var(--line); border-radius: 8px; background: white; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { border-bottom: 1px solid var(--line); padding: 8px 9px; text-align: left; vertical-align: top; }
th { position: sticky; top: 0; background: var(--surface-2); color: var(--muted); z-index: 1; font-weight: 700; }
tr:last-child td { border-bottom: 0; }
.pill { display: inline-flex; align-items: center; gap: 5px; border: 1px solid var(--line); border-radius: 999px; padding: 3px 8px; background: var(--surface-2); color: var(--muted); font-size: 12px; }
.pill.ok { background: #ecfdf5; border-color: var(--ok); color: var(--ok); }
.pill.bad { background: #fef3f2; border-color: var(--danger); color: var(--danger); }
.oauth-state { white-space: normal; min-height: 36px; display: inline-flex; align-items: center; padding: 6px 10px; border-radius: 999px; font-size: 12px; border: 1px solid var(--line); background: var(--surface-2); color: var(--muted); }
.oauth-state.ok { background: #ecfdf5; border-color: var(--ok); color: var(--ok); }
.oauth-state.bad { background: #fef3f2; border-color: var(--danger); color: var(--danger); }
.mono { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; overflow-wrap: anywhere; }
.mini { font-size: 12px; color: var(--muted); }
.compact { max-width: 160px; }
.task-list { display: grid; gap: 8px; }
.task { border: 1px solid var(--line); border-radius: 8px; background: white; padding: 10px; display: grid; grid-template-columns: 1fr auto; gap: 8px; }
.task strong { font-size: 13px; }
.task small { color: var(--muted); }
.empty { color: var(--muted); padding: 14px; border: 1px dashed var(--line); border-radius: 8px; background: var(--surface-2); }
.fold { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
@media (max-width: 1280px) {
  .grid, .fold { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 1080px) {
  .app { grid-template-columns: 1fr; }
  aside { position: static; height: auto; }
  nav { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .grid, .grid.two, .stats, .split, .fold { grid-template-columns: 1fr; }
  main { padding: 14px; }
}
"""
