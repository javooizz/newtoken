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

import json
import time
from typing import Any

from newtoken.acc import seat_client as seat_core
from newtoken.common.logging_setup import get_logger, log_run_context
from newtoken.webui.acc import change_acc_user_seat, enforce_acc_low_quota_policy
from newtoken.webui.policy_runner import run_observed_policy
from newtoken.webui.config import WebState
from newtoken.webui.oidc_client import oidc_generate_cards
from newtoken.webui.register import register_batch
from newtoken.sub2api.converter_core import build_export_account, build_export_result
from newtoken.sub2api.remote import (
    fetch_remote_account_list,
    import_to_sub2api_codex_session,
    scan_remote_accounts,
)

logger = get_logger("webui.auto")

AUTO_CARD_DAYS = 30


def _read_auto_register_config(config: dict[str, str]) -> dict[str, Any]:
    threshold = 1
    count = 3
    enabled = True
    if str(config.get("SUB2API_AUTO_REGISTER_ENABLED", "true")).strip().lower() in {
        "0",
        "false",
        "no",
        "off",
    }:
        enabled = False
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
    return {"enabled": enabled, "threshold": threshold, "count": count}


def _auto_phase(label: str, start: float) -> dict[str, Any]:
    return {"phase": label, "elapsed": round(time.time() - start, 2)}


def run_auto_maintenance(state: WebState) -> dict[str, Any]:
    start = time.time()
    run_id = f"auto{time.strftime('%H%M%S')}"
    with log_run_context(run_id):
        logger.info("自动维护开始 run_id=%s", run_id)
        report: dict[str, Any] = {
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start)),
            "phases": [],
            "errors": [],
        }

        config = state.load_config()
        auto_cfg = _read_auto_register_config(config)
        email_domain = str(config.get("SUB2API_AUTO_REGISTER_DOMAIN") or config.get("CHATGPT_RANDOM_EMAIL_DOMAIN") or "").strip()

        proxy_url = str(config.get("SUB2API_OUTBOUND_PROXY_URL") or "").strip()
        mother_email = str(config.get("ACC_MOTHER_ACCOUNT_EMAIL") or "").strip().lower()
        k_limit = seat_core.CHATGPT_SEAT_LIMIT  # ChatGPT 服务号目标数（硬上限）
        n_active = None  # 池内真正 active 的 ChatGPT 服务号数（Phase1 enforce 给出，含额度判断）

        # ---- Phase 1: low-quota policy ----------------------------------------
        # main 策略层：刷额度 / 删 401 / 低额度 ChatGPT→Codex / 同步池 active|inactive。
        # active_chatgpt_remote_ids = ChatGPT 席位且在池 active 且额度足的 runtime id，
        # 其 len() 即"池内真正在服务的 ChatGPT 号数"——补号决策的唯一依据（README 规则6）。
        try:
            policy_result = run_observed_policy(state)
            report["phases"].append({**_auto_phase("seat_policy", start), "result": policy_result})
            _pr = policy_result if isinstance(policy_result, dict) else {}
            n_active = len(_pr.get("active_chatgpt_remote_ids") or [])
            logger.info(
                "phase=seat_policy ok active_chatgpt=%s/%s seats=%s changed=%s",
                n_active, k_limit, _pr.get("chatgpt_count", "-"),
                len(_pr.get("changed_members") or []),
            )
        except Exception as exc:
            logger.exception("phase=seat_policy 失败")
            report["phases"].append({**_auto_phase("seat_policy", start), "error": str(exc)})
            report["errors"].append(f"seat_policy: {exc}")

        # ---- Phase 2: scan remote pool ----------------------------------------
        try:
            remote_config = state.build_remote_config()
            scan = scan_remote_accounts(remote_config)
            state.last_remote_scan = scan
            report["phases"].append({**_auto_phase("remote_scan", start), "result": {
                "total": scan.get("total_count", 0),
                "alive": scan.get("alive_count", 0),
                "dead": scan.get("dead_count", 0),
                "no_quota": scan.get("no_quota_count", 0),
            }})
            logger.info("phase=remote_scan total=%s alive=%s dead=%s no_quota=%s",
                        scan.get("total_count", 0), scan.get("alive_count", 0),
                        scan.get("dead_count", 0), scan.get("no_quota_count", 0))
        except Exception as exc:
            logger.exception("phase=remote_scan 失败")
            report["phases"].append({**_auto_phase("remote_scan", start), "error": str(exc)})
            report["errors"].append(f"remote_scan: {exc}")
            return report

        # ---- Phase 2.5: 清理幽灵 ChatGPT 席位（占席位但不在服务池）-------------
        # README 规则6"先降席位"：占着 ChatGPT 席位却不在 Sub2API group 服务池里的
        # 成员是"幽灵"——白占 K 硬上限、不产生服务。先把它们降为 Codex（符合"永不删
        # member"=改席位类型），给真正能服务的新号腾出席位。幽灵本就不在 active 池，
        # 故此操作不改变 n_active，只是释放被卡住的硬上限。
        ghost_demoted: list[str] = []
        try:
            pool_emails = {
                str(item.get("name") or item.get("email") or "").strip().lower()
                for item in fetch_remote_account_list(remote_config, apply_group_filter=True)
                if isinstance(item, dict)
            }
            pool_emails.discard("")
            client = state.build_seat_client()
            for user in seat_core.list_all_users(client):
                email = str(user.get("email") or "").strip()
                if not email or not seat_core.is_chatgpt_seat_type(user.get("seat_type")):
                    continue
                low = email.lower()
                if low == mother_email or low in pool_emails:
                    continue
                try:
                    change_acc_user_seat(state, str(user.get("id") or ""), email, seat_core.CODEX_SEAT_TYPE)
                    ghost_demoted.append(email)
                except Exception:
                    logger.exception("清幽灵席位失败 email=%s", email)
            report["phases"].append({**_auto_phase("cleanup_ghost", start),
                                      "result": {"demoted": ghost_demoted}})
            if ghost_demoted:
                logger.info("phase=cleanup_ghost demote=%s -> %s", len(ghost_demoted), ghost_demoted)
        except Exception as exc:
            logger.exception("phase=cleanup_ghost 失败")
            report["phases"].append({**_auto_phase("cleanup_ghost", start), "error": str(exc)})
            report["errors"].append(f"cleanup_ghost: {exc}")

        # ---- Phase 3: 补号决策 = 目标 K - 池内 active ChatGPT 服务号 -----------
        if n_active is None:
            # Phase1 enforce 失败兜底：现查 ACC ChatGPT 席位数（无额度信息，保守估）
            try:
                n_active = seat_core.count_chatgpt_seats(
                    seat_core.list_all_users(state.build_seat_client())
                )
            except Exception:
                logger.exception("phase=register 兜底现查 ChatGPT 席位失败，保守按 0")
                n_active = 0
        need = max(0, k_limit - int(n_active or 0))
        report["pool_status"] = {
            "active_chatgpt": n_active, "target": k_limit,
            "ghost_demoted": len(ghost_demoted), "need": need,
        }

        if need <= 0:
            report["phases"].append({**_auto_phase("replenish", start), "skipped": True,
                                      "reason": f"active_chatgpt={n_active} >= target={k_limit}"})
            report["elapsed"] = round(time.time() - start, 2)
            logger.info("池内 active ChatGPT 充足 %s/%s，无需补号", n_active, k_limit)
            return report
        if not auto_cfg["enabled"]:
            report["phases"].append({**_auto_phase("register", start), "skipped": True,
                                      "reason": "SUB2API_AUTO_REGISTER_ENABLED=false"})
            report["elapsed"] = round(time.time() - start, 2)
            logger.info("自动补号已关闭，跳过")
            return report
        if not email_domain:
            report["phases"].append({**_auto_phase("register", start), "error": "SUB2API_AUTO_REGISTER_DOMAIN / CHATGPT_RANDOM_EMAIL_DOMAIN not configured"})
            report["errors"].append("register: SUB2API_AUTO_REGISTER_DOMAIN / CHATGPT_RANDOM_EMAIL_DOMAIN not configured")
            report["elapsed"] = round(time.time() - start, 2)
            logger.warning("phase=register 缺少注册域名配置")
            return report

        # ---- Phase 4: register new ChatGPT 服务号 -----------------------------
        # 已先降幽灵释放席位，register 的号 JIT 以 ChatGPT 入会，入会后席位数 ≤ K，无需护栏。
        register_count = need
        logger.info("开始补号 count=%s（池内 active ChatGPT %s/%s，已清幽灵 %s）",
                    register_count, n_active, k_limit, len(ghost_demoted))
        try:
            register_results = register_batch(
                register_count, email_domain=email_domain, proxy_url=proxy_url,
                oidc_api_url=str(config.get("SUB2API_OIDC_API_URL") or "").strip(),
                oidc_api_key=str(config.get("SUB2API_OIDC_API_KEY") or "").strip(),
                account_id=str(config.get("OPENAI_ACCOUNT_ID") or "").strip(),
                max_workers=1, run_id=run_id,
            )
            ok_results = [r for r in register_results if r.ok]
            fail_results = [r for r in register_results if not r.ok]
            report["phases"].append({**_auto_phase("register", start), "result": {
                "requested": register_count, "ok": len(ok_results), "fail": len(fail_results),
                "emails": [r.email for r in ok_results],
                "errors": [{"email": r.email, "error": r.error} for r in fail_results],
            }})
            logger.info("补号结果 ok=%s fail=%s", len(ok_results), len(fail_results))

            if not ok_results:
                report["errors"].append("registration: 0 accounts registered successfully")
                report["elapsed"] = round(time.time() - start, 2)
                return report

        except Exception as exc:
            logger.exception("phase=register 失败")
            report["phases"].append({**_auto_phase("register", start), "error": str(exc)})
            report["errors"].append(f"register: {exc}")
            report["elapsed"] = round(time.time() - start, 2)
            return report

        # ---- Phase 5: import to Sub2API ---------------------------------------
        # 注册号都是同一母号成员、共享 workspace chatgpt_account_id；codex-session
        # 端点会按它误判重复、只进 1 个。改为把各号 token 转成 sub2api-data，一次性
        # 走 /accounts/data（按各号 user_id/email 去重 + 绑定 group_ids），同母号
        # 多号才能正确入池。
        try:
            accounts_for_import = []
            for r in ok_results:
                if not r.token_json:
                    continue
                try:
                    accounts_for_import.append(build_export_account(json.loads(r.token_json)))
                except Exception as exc:
                    logger.exception("phase=import token 转换失败 email=%s", r.email)
                    report["phases"].append({**_auto_phase("import", start), "error": f"convert {r.email}: {exc}"})
            created = reused = 0
            import_result = None
            if accounts_for_import:
                data_payload = build_export_result(accounts_for_import)
                import_result = import_to_sub2api_codex_session(
                    remote_config, json.dumps(data_payload, ensure_ascii=False)
                )
                if isinstance(import_result, dict):
                    created = int(import_result.get("created", 0) or 0)
                    reused = int(import_result.get("reused", 0) or 0)
                report["phases"].append({**_auto_phase("import", start), "result": {
                    "created": created, "reused": reused, "total": len(accounts_for_import),
                    "strategy": import_result.get("import_strategy") if isinstance(import_result, dict) else "",
                }})
            logger.info("phase=import created=%s reused=%s total=%s", created, reused, len(accounts_for_import))
        except Exception as exc:
            logger.exception("phase=import 失败")
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
                logger.info("phase=oidc_cards generated=%s", len(cards_list))
            else:
                report["phases"].append({**_auto_phase("oidc_cards", start), "skipped": True,
                                          "reason": cards_result.get("error", "unknown")})
                logger.warning("phase=oidc_cards 跳过：%s", cards_result.get("error", "unknown"))
        except Exception as exc:
            logger.exception("phase=oidc_cards 失败")
            report["phases"].append({**_auto_phase("oidc_cards", start), "error": str(exc)})
            report["errors"].append(f"oidc_cards: {exc}")

        report["elapsed"] = round(time.time() - start, 2)
        logger.info("自动维护完成 elapsed=%ss errors=%s", report["elapsed"], len(report["errors"]))
        return report
