"""GitHub 版本检查与 exe 自更新支持。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib import error

from sub2api_runtime import is_frozen_app
from sub2api_http_client import download_file as proxied_download_file
from sub2api_http_client import http_request_text

DEFAULT_GITHUB_REPO = "DZenner/newtoken"
DEFAULT_EXE_ASSET_NAME = "Sub2API独立工具.exe"
QQ_GROUP_LABEL = "QQ群：860119326"
QQ_GROUP_URL = "https://qm.qq.com/q/DODnT1Kges"
GITHUB_PROJECT_LABEL = "GitHub"
GITHUB_PROJECT_URL = "https://github.com/DZenner/newtoken"
GITHUB_API_BASE = "https://api.github.com/repos"
_UPDATE_COMPARE_GRACE_SECONDS = 60


@dataclass(frozen=True)
class GitHubReleaseAsset:
    """GitHub Release 资产。"""

    name: str
    download_url: str
    content_type: str
    size: int


@dataclass(frozen=True)
class GitHubRemoteVersion:
    """GitHub 远端版本信息。"""

    source: str
    label: str
    html_url: str
    published_at: str
    published_at_display: str
    assets: tuple[GitHubReleaseAsset, ...]


@dataclass(frozen=True)
class GitHubUpdateCheckResult:
    """当前程序与 GitHub 最新版本的比对结果。"""

    repo: str
    source: str
    current_path: str
    current_version_label: str
    current_modified_at: str
    current_modified_at_display: str
    latest_version_label: str
    latest_published_at: str
    latest_published_at_display: str
    latest_url: str
    update_available: bool
    can_auto_update: bool
    preferred_asset_name: str
    preferred_asset_url: str
    reason: str


def resolve_github_repo(explicit_repo: str = "") -> str:
    """返回用于检查更新的 GitHub 仓库标识。"""

    repo = str(explicit_repo or os.environ.get("SUB2API_GITHUB_REPO") or "").strip()
    return repo or DEFAULT_GITHUB_REPO


def _build_request_headers() -> dict[str, str]:
    """构造 GitHub API 请求头。"""

    return {
        "Accept": "application/vnd.github+json",
        "User-Agent": "Sub2API-Standalone-Updater",
    }


def _http_get_json(url: str, timeout: int = 15) -> dict[str, Any] | list[Any]:
    """执行 HTTP GET 并解析 JSON。"""

    status_code, reason, raw_body, _headers = http_request_text(
        url,
        headers=_build_request_headers(),
        timeout=timeout,
    )
    if status_code == 404:
        raise error.HTTPError(url, 404, reason, {}, None)
    if status_code < 200 or status_code >= 300:
        raise RuntimeError(f"GitHub 请求失败 HTTP {status_code} {reason}: {raw_body[:500]}")
    return json.loads(raw_body)


def parse_iso_datetime(raw_value: str) -> datetime | None:
    """解析 GitHub 常见 ISO 时间。"""

    text = str(raw_value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_datetime_for_display(raw_value: str) -> str:
    """把 ISO 时间格式化成更适合界面展示的文本。"""

    parsed = parse_iso_datetime(raw_value)
    if parsed is None:
        return "--"
    local_dt = parsed.astimezone()
    return local_dt.strftime("%Y-%m-%d %H:%M:%S")


def format_timestamp_for_display(timestamp: float | int | None) -> str:
    """把文件修改时间格式化成界面文本。"""

    if timestamp is None:
        return "--"
    try:
        local_dt = datetime.fromtimestamp(float(timestamp)).astimezone()
    except (TypeError, ValueError, OSError):
        return "--"
    return local_dt.strftime("%Y-%m-%d %H:%M:%S")


def _parse_release_assets(raw_assets: list[dict[str, Any]] | None) -> tuple[GitHubReleaseAsset, ...]:
    """把 GitHub Release 资产列表转换成 dataclass。"""

    assets: list[GitHubReleaseAsset] = []
    for item in raw_assets or []:
        assets.append(
            GitHubReleaseAsset(
                name=str(item.get("name") or "").strip(),
                download_url=str(item.get("browser_download_url") or "").strip(),
                content_type=str(item.get("content_type") or "").strip(),
                size=int(item.get("size") or 0),
            )
        )
    return tuple(assets)


def fetch_latest_release(repo: str, timeout: int = 15) -> GitHubRemoteVersion | None:
    """拉取 GitHub 最新 Release；没有 Release 时返回 None。"""

    api_url = f"{GITHUB_API_BASE}/{resolve_github_repo(repo)}/releases/latest"
    try:
        payload = _http_get_json(api_url, timeout=timeout)
    except error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    if not isinstance(payload, dict):
        raise ValueError("GitHub Release 返回格式异常")
    return GitHubRemoteVersion(
        source="release",
        label=str(payload.get("tag_name") or payload.get("name") or "latest").strip(),
        html_url=str(payload.get("html_url") or "").strip(),
        published_at=str(payload.get("published_at") or payload.get("created_at") or "").strip(),
        published_at_display=format_datetime_for_display(
            str(payload.get("published_at") or payload.get("created_at") or "").strip()
        ),
        assets=_parse_release_assets(payload.get("assets")),
    )


def fetch_latest_commit(repo: str, timeout: int = 15) -> GitHubRemoteVersion:
    """拉取 GitHub 默认分支最新提交。"""

    api_url = f"{GITHUB_API_BASE}/{resolve_github_repo(repo)}/commits?per_page=1"
    payload = _http_get_json(api_url, timeout=timeout)
    if not isinstance(payload, list) or not payload:
        raise ValueError("GitHub 提交列表为空")
    latest = payload[0]
    commit_info = latest.get("commit") or {}
    author_info = commit_info.get("author") or {}
    commit_sha = str(latest.get("sha") or "").strip()
    short_sha = commit_sha[:7] if commit_sha else "unknown"
    published_at = str(author_info.get("date") or "").strip()
    return GitHubRemoteVersion(
        source="commit",
        label=short_sha,
        html_url=str(latest.get("html_url") or "").strip(),
        published_at=published_at,
        published_at_display=format_datetime_for_display(published_at),
        assets=(),
    )


def get_latest_remote_version(repo: str, timeout: int = 15) -> GitHubRemoteVersion:
    """优先读取 Release，不存在时回退到最新提交。"""

    release = fetch_latest_release(repo, timeout=timeout)
    if release is not None:
        return release
    return fetch_latest_commit(repo, timeout=timeout)


def get_current_app_path(module_file: str | Path) -> Path:
    """返回当前运行主体文件路径。"""

    if is_frozen_app():
        return Path(sys.executable).resolve()
    return Path(module_file).resolve()


def try_get_git_head_label(project_dir: Path) -> str:
    """尽量读取源码仓库当前 HEAD 短 SHA。"""

    try:
        completed = subprocess.run(
            ["git", "-C", str(project_dir), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            check=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.strip()


def build_current_version_label(app_path: Path) -> str:
    """构造本地版本展示文本。"""

    if not is_frozen_app():
        git_label = try_get_git_head_label(app_path.parent)
        if git_label:
            return f"源码 {git_label}"
        return f"源码 {app_path.name}"
    return f"本地 {app_path.name}"


def find_preferred_release_asset(
    assets: tuple[GitHubReleaseAsset, ...],
    current_file_name: str,
) -> GitHubReleaseAsset | None:
    """挑选最适合当前程序的一份 Release 资产。"""

    preferred_names = [
        str(current_file_name or "").strip(),
        DEFAULT_EXE_ASSET_NAME,
    ]
    normalized_assets = [asset for asset in assets if asset.name and asset.download_url]
    for preferred_name in preferred_names:
        if not preferred_name:
            continue
        for asset in normalized_assets:
            if asset.name == preferred_name:
                return asset
    for asset in normalized_assets:
        if asset.name.lower().endswith(".exe"):
            return asset
    for asset in normalized_assets:
        lowered = asset.name.lower()
        if lowered.endswith(".zip") or lowered.endswith(".7z"):
            return asset
    return normalized_assets[0] if normalized_assets else None


def build_github_update_check_result(
    module_file: str | Path,
    repo: str = "",
    timeout: int = 15,
) -> GitHubUpdateCheckResult:
    """生成当前程序与 GitHub 最新版本的比对结果。"""

    effective_repo = resolve_github_repo(repo)
    latest = get_latest_remote_version(effective_repo, timeout=timeout)
    app_path = get_current_app_path(module_file)
    current_stat = app_path.stat()
    current_mtime = datetime.fromtimestamp(current_stat.st_mtime, tz=timezone.utc)
    latest_dt = parse_iso_datetime(latest.published_at)
    update_available = False
    if latest_dt is not None:
        update_available = latest_dt > (
            current_mtime + timedelta(seconds=_UPDATE_COMPARE_GRACE_SECONDS)
        )
    preferred_asset = find_preferred_release_asset(latest.assets, app_path.name)
    can_auto_update = bool(
        latest.source == "release"
        and preferred_asset is not None
        and preferred_asset.name.lower().endswith(".exe")
        and is_frozen_app()
        and app_path.suffix.lower() == ".exe"
    )
    if latest.source == "release":
        reason = "已从 GitHub Release 检查最新版本"
    else:
        reason = "仓库暂无 Release，已回退到最新提交检查"
    return GitHubUpdateCheckResult(
        repo=effective_repo,
        source=latest.source,
        current_path=str(app_path),
        current_version_label=build_current_version_label(app_path),
        current_modified_at=current_mtime.isoformat(),
        current_modified_at_display=format_timestamp_for_display(current_stat.st_mtime),
        latest_version_label=latest.label or "latest",
        latest_published_at=latest.published_at,
        latest_published_at_display=latest.published_at_display,
        latest_url=latest.html_url,
        update_available=update_available,
        can_auto_update=can_auto_update,
        preferred_asset_name=preferred_asset.name if preferred_asset else "",
        preferred_asset_url=preferred_asset.download_url if preferred_asset else "",
        reason=reason,
    )


def build_update_download_path(current_exe_path: str | Path) -> Path:
    """返回更新包临时下载路径。"""

    current_path = Path(current_exe_path)
    return current_path.with_name(f"{current_path.name}.download")


def build_update_script_path(current_exe_path: str | Path) -> Path:
    """返回更新替换脚本路径。"""

    current_path = Path(current_exe_path)
    return current_path.with_name(f"{current_path.stem}_更新.cmd")


def download_file(url: str, target_path: str | Path, timeout: int = 120) -> Path:
    """把远端文件下载到本地。"""

    return proxied_download_file(url, target_path, timeout=timeout)


def build_windows_replace_script_text(
    current_exe_path: str | Path,
    downloaded_path: str | Path,
    process_id: int,
) -> str:
    """生成 Windows 更新替换脚本文本。"""

    current_exe = Path(current_exe_path)
    downloaded = Path(downloaded_path)
    return "\n".join(
        [
            "@echo off",
            "setlocal enableextensions",
            f"set \"TARGET_EXE={current_exe}\"",
            f"set \"DOWNLOADED_EXE={downloaded}\"",
            ":wait_loop",
            f'tasklist /FI "PID eq {int(process_id)}" | find "{int(process_id)}" >nul',
            "if not errorlevel 1 (",
            "  timeout /t 1 /nobreak >nul",
            "  goto wait_loop",
            ")",
            "if not exist \"%DOWNLOADED_EXE%\" goto end",
            "move /Y \"%DOWNLOADED_EXE%\" \"%TARGET_EXE%\" >nul",
            "start \"\" \"%TARGET_EXE%\"",
            ":end",
            "del \"%~f0\"",
            "",
        ]
    )


def schedule_exe_update(
    current_exe_path: str | Path,
    downloaded_path: str | Path,
    process_id: int,
) -> Path:
    """写入并启动 exe 替换脚本。"""

    script_path = build_update_script_path(current_exe_path)
    script_text = build_windows_replace_script_text(
        current_exe_path=current_exe_path,
        downloaded_path=downloaded_path,
        process_id=process_id,
    )
    script_path.write_text(script_text, encoding="utf-8")
    os.startfile(str(script_path))
    return script_path


def prepare_github_update(
    module_file: str | Path,
    repo: str = "",
    timeout: int = 15,
) -> dict[str, Any]:
    """准备 GitHub 更新任务，必要时直接下载更新包。"""

    check_result = build_github_update_check_result(
        module_file=module_file,
        repo=repo,
        timeout=timeout,
    )
    result: dict[str, Any] = {
        "status": "up_to_date",
        "check": asdict(check_result),
        "downloaded_path": "",
        "script_path": "",
    }
    if not check_result.update_available:
        return result
    if not check_result.can_auto_update:
        result["status"] = "open_browser"
        return result

    current_exe_path = Path(check_result.current_path)
    download_path = build_update_download_path(current_exe_path)
    if download_path.exists():
        download_path.unlink()
    download_file(check_result.preferred_asset_url, download_path, timeout=120)
    script_path = schedule_exe_update(
        current_exe_path=current_exe_path,
        downloaded_path=download_path,
        process_id=os.getpid(),
    )
    result["status"] = "scheduled"
    result["downloaded_path"] = str(download_path)
    result["script_path"] = str(script_path)
    return result
