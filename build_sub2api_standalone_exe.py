"""构建 Sub2API 独立工具 exe 的脚本。"""

from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "Sub2API独立工具"
PROJECT_DIR = Path(__file__).resolve().parent
ENTRY_SCRIPT = PROJECT_DIR / "sub2api_standalone_tool.py"
DIST_ROOT = PROJECT_DIR / "dist"
PYINSTALLER_WORK_ROOT = PROJECT_DIR / "build" / "pyinstaller"
SPEC_ROOT = PYINSTALLER_WORK_ROOT / "spec"
WORK_ROOT = PYINSTALLER_WORK_ROOT / "work"
DEFAULT_RELEASE_NOTE_NAME = "首次使用说明.txt"


def resolve_python_executable(explicit_python: str = "") -> str:
    """返回用于打包的 Python 可执行文件路径。"""

    if explicit_python.strip():
        return explicit_python.strip()
    return sys.executable


def emit_console_line(text: str) -> None:
    """以当前控制台可接受的形式输出文本，避免编码报错中断构建。"""

    stream = sys.stdout
    encoding = getattr(stream, "encoding", None) or "utf-8"
    if not isinstance(stream, io.TextIOBase):
        stream.write(f"{text}\n")
        return
    safe_text = text.encode(encoding, errors="backslashreplace").decode(encoding)
    stream.write(f"{safe_text}\n")
    stream.flush()


def build_pyinstaller_command(
    python_executable: str,
    *,
    onefile: bool,
) -> list[str]:
    """组装 PyInstaller 命令。"""

    command = [
        python_executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        APP_NAME,
        "--distpath",
        str(DIST_ROOT),
        "--workpath",
        str(WORK_ROOT),
        "--specpath",
        str(SPEC_ROOT),
        "--paths",
        str(PROJECT_DIR),
    ]
    command.append("--onefile" if onefile else "--onedir")
    command.append(str(ENTRY_SCRIPT))
    return command


def resolve_release_dir(*, onefile: bool) -> Path:
    """返回发行目录。"""

    return DIST_ROOT if onefile else DIST_ROOT / APP_NAME


def build_release_note(*, onefile: bool) -> str:
    """生成放到发行目录里的说明文本。"""

    exe_name = f"{APP_NAME}.exe"
    package_shape = "单文件 exe" if onefile else "目录版 exe"
    return (
        f"{APP_NAME} 已构建完成。\n"
        f"当前输出类型：{package_shape}\n\n"
        "使用方法：\n"
        f"1. 双击 {exe_name} 直接启动。\n"
        "2. 如果当前目录还没有 .env，程序会在首次启动时自动生成。\n"
        "3. 首次配置向导填一次服务器地址和管理员 Key，后面就能直接使用。\n"
        "4. 首次运行后，缓存文件会自动写在 exe 同目录。\n\n"
        "说明：\n"
        "- 这个 exe 已内置 Python 运行时，不再依赖 bat / 本机 Python 环境。\n"
        "- .env.example 只是给你对照字段，不再是运行前必需文件。\n"
    )


def copy_release_support_files(*, onefile: bool) -> list[Path]:
    """把示例配置和说明复制到发行目录。"""

    release_dir = resolve_release_dir(onefile=onefile)
    release_dir.mkdir(parents=True, exist_ok=True)

    copied_files: list[Path] = []
    env_example_path = PROJECT_DIR / ".env.example"
    if env_example_path.exists():
        target_env_example_path = release_dir / ".env.example"
        shutil.copy2(env_example_path, target_env_example_path)
        copied_files.append(target_env_example_path)

    note_path = release_dir / DEFAULT_RELEASE_NOTE_NAME
    note_path.write_text(build_release_note(onefile=onefile), encoding="utf-8")
    copied_files.append(note_path)
    return copied_files


def run_build(*, python_executable: str, onefile: bool, dry_run: bool) -> int:
    """执行 PyInstaller 构建。"""

    command = build_pyinstaller_command(
        python_executable=python_executable,
        onefile=onefile,
    )
    if dry_run:
        emit_console_line(" ".join(command))
        return 0

    subprocess.run(command, check=True, cwd=PROJECT_DIR)
    copied_files = copy_release_support_files(onefile=onefile)
    emit_console_line(f"[BUILD] 输出目录：{resolve_release_dir(onefile=onefile)}")
    for copied_file in copied_files:
        emit_console_line(f"[BUILD] 已写入：{copied_file}")
    return 0


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""

    parser = argparse.ArgumentParser(description="构建 Sub2API 独立工具 exe")
    parser.add_argument(
        "--python",
        default="",
        help="指定用于打包的 Python 可执行文件路径，默认使用当前解释器",
    )
    parser.add_argument(
        "--onefile",
        action="store_true",
        help="输出单文件 exe；默认输出更稳的目录版",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印打包命令，不实际执行",
    )
    return parser.parse_args()


def main() -> int:
    """脚本入口。"""

    args = parse_args()
    python_executable = resolve_python_executable(args.python)
    return run_build(
        python_executable=python_executable,
        onefile=bool(args.onefile),
        dry_run=bool(args.dry_run),
    )


if __name__ == "__main__":
    raise SystemExit(main())
