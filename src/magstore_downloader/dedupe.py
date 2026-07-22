from __future__ import annotations

from pathlib import Path
from typing import Any

from .matching import normalize_title
from .models import DuplicateResult, IssueInfo, MagazineConfig


def check_duplicate(
    issue: IssueInfo,
    magazine: MagazineConfig,
    magazine_state: dict[str, Any],
    magazine_download_dir: Path,
    redownload: bool = False,
    redownload_if_file_missing: bool = False,
) -> DuplicateResult:
    if redownload:
        return DuplicateResult(False, False, "redownload-requested")

    title_norm = normalize_title(issue.best_title)
    downloaded = magazine_state.get("downloaded") or []

    if issue.issue_id:
        last_id = magazine_state.get("last_downloaded_issue_id")
        if issue.issue_id == last_id:
            file_path = Path(str(magazine_state.get("last_file_path", "")))
            if redownload_if_file_missing and file_path and not file_path.exists():
                return DuplicateResult(False, False, "last-file-missing")
            return DuplicateResult(True, False, "last-downloaded-issue-id")
        for record in downloaded:
            if record.get("issue_id") == issue.issue_id or record.get("unique_key") == f"issue:{issue.issue_id}":
                if _record_file_missing(record) and redownload_if_file_missing:
                    return DuplicateResult(False, False, "history-file-missing", record)
                return DuplicateResult(True, False, "history-issue-id", record)

    if title_norm:
        last_title = normalize_title(magazine_state.get("last_downloaded_issue_title"))
        if title_norm == last_title:
            return DuplicateResult(True, False, "last-downloaded-title")
        for record in downloaded:
            if title_norm == normalize_title(record.get("title")):
                if _record_file_missing(record) and redownload_if_file_missing:
                    return DuplicateResult(False, False, "history-title-file-missing", record)
                return DuplicateResult(True, False, "history-title", record)

    if issue.issue_date:
        date_text = issue.issue_date.isoformat()
        last_date = magazine_state.get("last_downloaded_issue_date")
        if date_text == last_date:
            return DuplicateResult(True, False, "last-downloaded-date")
        for record in downloaded:
            if record.get("issue_date") == date_text:
                if _record_file_missing(record) and redownload_if_file_missing:
                    return DuplicateResult(False, False, "history-date-file-missing", record)
                return DuplicateResult(True, False, "history-date", record)

    if title_norm and magazine_download_dir.exists():
        for path in magazine_download_dir.iterdir():
            if path.is_file() and normalize_title(path.stem) == title_norm:
                return DuplicateResult(True, False, "local-file-title", backfill_file_path=path)

    if not issue.issue_id and not title_norm and not issue.issue_date:
        return DuplicateResult(False, True, "duplicate-check-uncertain")

    return DuplicateResult(False, False, "new-issue")


def _record_file_missing(record: dict[str, Any]) -> bool:
    file_path = record.get("file_path")
    return bool(file_path) and not Path(str(file_path)).exists()

