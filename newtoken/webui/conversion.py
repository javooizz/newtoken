"""Account conversion and Sub2API import actions for the WebUI."""

from __future__ import annotations

import concurrent.futures
import json
from typing import Any

from newtoken.sub2api.converter_core import (
    CAP_OUTPUT_MODE,
    MAX_CONCURRENT_CHECKS,
    build_cap_result,
    build_export_result,
    calculate_average_remaining_quota,
    collect_account_candidates,
    resolve_input_sources,
    validate_account_candidate,
)
from newtoken.sub2api.remote import import_to_sub2api_codex_session
from newtoken.webui.config import WebState
from newtoken.webui.utils import parse_positive_int


def run_conversion(input_path: str, output_mode: str, state: WebState) -> dict[str, Any]:
    values = state.load_config()
    input_sources = resolve_input_sources(input_path)
    candidates, skipped_duplicates = collect_account_candidates(input_sources)
    counts = {"auth_error": 0, "quota_error": 0, "other_error": 0}
    usable_results = []
    validate_concurrency = parse_positive_int(
        values.get("SUB2API_VALIDATE_CONCURRENCY"),
        default=min(MAX_CONCURRENT_CHECKS, 24),
        maximum=MAX_CONCURRENT_CHECKS,
    )

    if candidates:
        worker_count = min(validate_concurrency, len(candidates))
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = [
                executor.submit(validate_account_candidate, candidate)
                for candidate in candidates
            ]
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result.status == "ok":
                    usable_results.append(result)
                elif result.status in counts:
                    counts[result.status] += 1
                else:
                    counts["other_error"] += 1

    usable_accounts = [
        result.account
        for result in sorted(usable_results, key=lambda item: item.order)
        if result.account is not None
    ]
    payload = (
        build_cap_result(usable_accounts)
        if output_mode == CAP_OUTPUT_MODE
        else build_export_result(usable_accounts)
    )
    payload_text = json.dumps(payload, ensure_ascii=False, indent=2)
    summary = {
        "source_count": len(input_sources),
        "total_candidates": len(candidates),
        "skipped_duplicates": skipped_duplicates,
        "usable_count": len(usable_accounts),
        "average_remaining_quota": calculate_average_remaining_quota(usable_results),
        "auth_error_count": counts["auth_error"],
        "quota_error_count": counts["quota_error"],
        "other_error_count": counts["other_error"],
        "output_mode": output_mode,
        "validate_concurrency": validate_concurrency,
    }
    state.last_conversion_payload = payload_text
    state.last_conversion_summary = summary
    return summary


def import_cached_conversion(state: WebState, payload_text: str | None = None) -> dict[str, Any]:
    payload = payload_text if payload_text is not None else state.last_conversion_payload
    if not payload:
        raise RuntimeError("没有可导入的缓存结果，请先转换或粘贴 JSON")
    return import_to_sub2api_codex_session(state.build_remote_config(), payload)
