import shutil
from pathlib import Path

SUPPORTED_ARCHIVE_SUFFIXES = (
    ".zip",
    ".tar",
    ".tar.gz",
    ".tgz",
    ".tar.bz2",
    ".tbz2",
    ".tar.xz",
    ".txz",
)
UNSUPPORTED_ARCHIVE_SUFFIXES = (".rar", ".7z")


def get_archive_extract_folder_name(file_name):
    """把压缩包文件名转换为默认解压目录名。"""

    lower_name = file_name.lower()
    folder_name = Path(file_name).stem
    for suffix in sorted(SUPPORTED_ARCHIVE_SUFFIXES, key=len, reverse=True):
        if lower_name.endswith(suffix):
            folder_name = file_name[: -len(suffix)]
            break
    folder_name = folder_name.rstrip(" .")
    return folder_name or "archive"


def classify_archive_path(file_path):
    """识别当前文件是否为支持或暂不支持的压缩包。"""

    lower_name = file_path.name.lower()
    for suffix in SUPPORTED_ARCHIVE_SUFFIXES:
        if lower_name.endswith(suffix):
            return "supported"
    for suffix in UNSUPPORTED_ARCHIVE_SUFFIXES:
        if lower_name.endswith(suffix):
            return "unsupported"
    return ""


def extract_archives_in_directory(input_dir):
    """扫描目录中的压缩包并按同名目录去重后解压。"""

    root_dir = Path(input_dir)
    if not root_dir.exists() or not root_dir.is_dir():
        raise ValueError("请选择有效的目录后再执行一键解压")

    supported_archives = []
    unsupported_archives = []
    for file_path in sorted(root_dir.rglob("*")):
        if not file_path.is_file():
            continue
        archive_type = classify_archive_path(file_path)
        if archive_type == "supported":
            supported_archives.append(file_path)
        elif archive_type == "unsupported":
            unsupported_archives.append(file_path)

    results = []
    for archive_path in supported_archives:
        target_dir = archive_path.parent / get_archive_extract_folder_name(
            archive_path.name
        )
        if target_dir.exists():
            results.append(
                {
                    "archive_path": str(archive_path),
                    "target_dir": str(target_dir),
                    "status": "skipped",
                    "message": "已存在同名目录，跳过解压",
                }
            )
            continue
        target_dir.mkdir(parents=True, exist_ok=False)
        try:
            shutil.unpack_archive(str(archive_path), str(target_dir))
        except Exception:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise
        results.append(
            {
                "archive_path": str(archive_path),
                "target_dir": str(target_dir),
                "status": "extracted",
                "message": "解压完成",
            }
        )

    unsupported_items = [
        {
            "archive_path": str(file_path),
            "status": "unsupported",
            "message": "暂不支持该压缩格式，仅支持 zip/tar/tgz/tbz2/txz",
        }
        for file_path in unsupported_archives
    ]
    return {
        "input_dir": str(root_dir),
        "found_count": len(supported_archives),
        "extracted_count": sum(1 for item in results if item["status"] == "extracted"),
        "skipped_count": sum(1 for item in results if item["status"] == "skipped"),
        "unsupported_count": len(unsupported_items),
        "items": results,
        "unsupported_items": unsupported_items,
    }
