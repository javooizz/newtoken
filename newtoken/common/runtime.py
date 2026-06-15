"""运行时路径助手，统一兼容源码模式和 PyInstaller 打包模式。"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen_app() -> bool:
    """判断当前是否运行在打包后的可执行程序中。"""

    return bool(getattr(sys, "frozen", False))


def get_executable_dir() -> Path:
    """返回当前可执行文件所在目录。"""

    return Path(sys.executable).resolve().parent


def get_app_dir(module_file: str | Path, parent_levels: int = 0) -> Path:
    """返回当前模块对应的应用目录。

    源码模式下统一返回项目根目录，避免包内模块把 .env 写到子目录；
    打包模式下统一返回 exe 所在目录，确保 .env / 缓存都落在发行目录旁边。
    """

    if is_frozen_app():
        return get_executable_dir()
    app_dir = find_source_root(module_file)
    for _ in range(max(0, int(parent_levels))):
        app_dir = app_dir.parent
    return app_dir


def find_source_root(module_file: str | Path) -> Path:
    """源码模式下找到项目根目录。

    代码迁入 ``newtoken/`` 包后，模块文件路径一般是
    ``项目根/newtoken/<area>/<module>.py``。此时配置、缓存和发行文件仍
    应落在项目根，不能落到 ``newtoken/<area>`` 子目录。
    """

    path = Path(module_file).resolve()
    for parent in path.parents:
        if parent.name == "newtoken" and (parent / "__init__.py").exists():
            return parent.parent
    return path.parent


def resolve_app_file(
    module_file: str | Path,
    filename: str,
    *,
    parent_levels: int = 0,
) -> Path:
    """在应用目录下解析目标文件路径。"""

    return get_app_dir(module_file, parent_levels=parent_levels) / filename


def ensure_on_sys_path(path: str | Path) -> None:
    """把目标目录放进 sys.path，避免重复追加。"""

    normalized = str(Path(path).resolve())
    if normalized not in sys.path:
        sys.path.insert(0, normalized)


def chdir_to_app_dir(module_file: str | Path, parent_levels: int = 0) -> Path:
    """把当前工作目录切到应用目录，便于 GUI 双击启动时读写相邻文件。"""

    app_dir = get_app_dir(module_file, parent_levels=parent_levels)
    os.chdir(app_dir)
    return app_dir
