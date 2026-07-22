from __future__ import annotations

import re
from pathlib import Path


INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(value: str, default: str = "download") -> str:
    cleaned = INVALID_FILENAME_CHARS.sub("_", value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or default


def ensure_allowed_extension(filename: str, allowed_extensions: tuple[str, ...]) -> str:
    path = Path(filename)
    suffix = path.suffix.lower()
    allowed = tuple(ext.lower() for ext in allowed_extensions)
    if suffix in allowed:
        return filename
    if suffix:
        raise ValueError(f"下载文件扩展名不在允许列表中: {suffix}")
    if len(allowed) == 1:
        return filename + allowed[0]
    raise ValueError("下载文件没有扩展名，且 allowed_extensions 不唯一")


def resolve_conflict_path(target: Path, mode: str) -> Path | None:
    if not target.exists():
        return target
    if mode == "overwrite":
        return target
    if mode == "skip":
        return None
    if mode != "append":
        raise ValueError(f"未知 filename_conflict: {mode}")

    stem = target.stem
    suffix = target.suffix
    for index in range(1, 1000):
        candidate = target.with_name(f"{stem} ({index}){suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"无法生成不冲突的文件名: {target}")

