"""Full auto-maintenance pipeline for the WebUI scheduler.

Rotation cycle:
  ChatGPT seats → check quota → low-quota (Codex → offline) →
  count pool → if below threshold → register new accounts →
  import to Sub2API → generate OIDC cards

All steps are independent; each reports its own status.  The scheduler calls
run_auto_maintenance(state) periodically.

Requires: curl_cffi for registration (pip install curl_cffi)
"""

from __future__ import annotations

import time
from typing import Any

from newtoken.webui.acc import enforce_acc_low_quota_policy
from newtoken.webui.config import WebState
from newtoken.webui.oidc_client import oidc_generate_cards
from newtoken.webui.register import register_batch
from newtoken.sub2api.remote import (
    import_to_sub2api_codex_session,
    scan_remote_accounts,
)

AUTO_CARD_DAYS = 30


def _read_auto_register_config(config: dict[str, str]) -> dict[str, Any]:
    threshold = 1
    count = 3
    try:
        _t = int(str(config.get("SUB2API_AUTO_REGISTER_THRESHOLD") or "").strip())
        if _t >= 0:
            threshold = _t
    except (ValueError, TypeError):
        pass
    try:
        _c = int(str(config.get("SUB2API_AUTO_REGISTER_COUNT") or "").strip())
        if _c >= 1:
            count = _c
    except (ValueError, TypeError):
        pass
    return {"threshold": threshold, "count": count}


def _auto_phase(label: str, start: float) -> dict[str, Any]:
    return {"phase": label, "elapsed": round(time.time() - start, 2)}


def run_auto_maintenance(state: WebState) -> dict[str, Any]:
    start = time.time()
    report: dict[str, Any] = {
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start)),
        "phases": [],
        "errors": [],
    }

    config = state.load_config()
    auto_cfg = _read_auto_register_config(config)
    email_domain = str(config.get("SUB2API_AUTO_REGISTER_DOMAIN") or config.get("CHATGPT_RANDOM_EMAIL_DOMAIN") or "").strip()
    if not email_domain:
        report["errors"].append("SUB2API_AUTO_REGISTER_DOMAIN / CHATGPT_RANDOM_EMAIL_DOMAIN not configured")
        return report

    proxy_url = str(config.get("SUB2API_OUTBOUND_PROXY_URL") or "").strip()

    # ---- Phase 1: low-quota policy ----------------------------------------
    try:
        policy_result = enforce_acc_low_quota_policy(state)
        report["phases"].append({**_auto_phase("seat_policy", start), "result": policy_result})
    except Exception as exc:
        report["phases"].append({**_auto_phase("seat_policy", start), "error": str(exc)})
        report["errors"].append(f"seat_policy: {exc}")

    # ---- Phase 2: scan remote pool ----------------------------------------
    try:
        remote_config = state.build_remote_config()
        scan = scan_remote_accounts(remote_config)
        state.last_remote_scan = scan
        report["phases"].append({**_auto_phase("remote_scan", start), "result": {
            "total": scan.get("total", 0), "alive": scan.get("alive", 0),
            "dead": scan.get("dead", 0), "no_quota": scan.get("no_quota", 0),
        }})
    except Exception as exc:
        report["phases"].append({**_auto_phase("remote_scan", start), "error": str(exc)})
        report["errors"].append(f"remote_scan: {exc}")
        return report

    # ---- Phase 3: check if pool needs replenishment -----------------------
    alive = int(scan.get("alive", 0) or 0)
    quota_ok = alive - int(scan.get("no_quota", 0) or 0)
    report["pool_status"] = {"alive": alive, "quota_ok": quota_ok, "threshold": auto_cfg["threshold"]}

    if quota_ok >= auto_cfg["threshold"]:
        report["phases"].append({**_auto_phase("replenish", start), "skipped": True,
                                  "reason": f"quota_ok={quota_ok} >= threshold={auto_cfg['threshold']}"})
        report["elapsed"] = round(time.time() - start, 2)
        return report

    # ---- Phase 4: register new accounts -----------------------------------
    register_count = max(1, auto_cfg["count"] - quota_ok)
    try:
        register_results = register_batch(register_count, email_domain=email_domain, proxy_url=proxy_url, max_workers=1)
        ok_results = [r for r in register_results if r.ok]
        fail_results = [r for r in register_results if not r.ok]
        report["phases"].append({**_auto_phase("register", start), "result": {
            "requested": register_count, "ok": len(ok_results), "fail": len(fail_results),
            "emails": [r.email for r in ok_results],
            "errors": [{"email": r.email, "error": r.error} for r in fail_results],
        }})

        if not ok_results:
            report["errors"].append("registration: 0 accounts registered successfully")
            report["elapsed"] = round(time.time() - start, 2)
            return report

    except Exception as exc:
        report["phases"].append({**_auto_phase("register", start), "error": str(exc)})
        report["errors"].append(f"register: {exc}")
        report["elapsed"] = round(time.time() - start, 2)
        return report

    # ---- Phase 5: import to Sub2API ---------------------------------------
    try:
        import_payloads = [r.token_json for r in ok_results if r.token_json]
        imported = 0
        for payload in import_payloads:
            try:
                import_to_sub2api_codex_session(remote_config, payload)
                imported += 1
            except Exception as exc:
                report["phases"].append({**_auto_phase("import", start), "error": str(exc), "payload_preview": payload[:120]})
        report["phases"].append({**_auto_phase("import", start), "result": {"imported": imported, "total": len(import_payloads)}})
    except Exception as exc:
        report["phases"].append({**_auto_phase("import", start), "error": str(exc)})
        report["errors"].append(f"import: {exc}")

    # ---- Phase 6: generate OIDC cards -------------------------------------
    try:
        cards_needed = max(1, len(ok_results))
        cards_result = oidc_generate_cards(cards_needed, AUTO_CARD_DAYS, "auto_maintenance", config=config)
        if cards_result.get("ok"):
            cards_list = cards_result.get("cards") or []
            report["phases"].append({**_auto_phase("oidc_cards", start), "result": {
                "generated": len(cards_list), "batch_no": cards_result.get("batch_no", ""),
            }})
        else:
            report["phases"].append({**_auto_phase("oidc_cards", start), "skipped": True,
                                      "reason": cards_result.get("error", "unknown")})
    except Exception as exc:
        report["phases"].append({**_auto_phase("oidc_cards", start), "error": str(exc)})
        report["errors"].append(f"oidc_cards: {exc}")

    report["elapsed"] = round(time.time() - start, 2)
    return report
