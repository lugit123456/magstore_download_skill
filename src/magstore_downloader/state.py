from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .models import IssueInfo


class StateStore:
    def __init__(self, path: Path):
        self.path = path
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "magazines": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"state.json 不是有效 JSON: {self.path}") from exc
        if not isinstance(data, dict):
            raise ValueError("state.json 顶层必须是 object")
        data.setdefault("version", 1)
        data.setdefault("magazines", {})
        return data

    def magazine(self, magazine_id: str) -> dict[str, Any]:
        magazines = self.data.setdefault("magazines", {})
        return magazines.setdefault(magazine_id, {"downloaded": []})

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    def mark_checked(self, magazine_id: str, issue: IssueInfo | None, now: datetime, next_check_at: datetime | None) -> None:
        item = self.magazine(magazine_id)
        item["last_run_at"] = now.isoformat()
        item["last_checked_at"] = now.isoformat()
        item["next_check_at"] = next_check_at.isoformat() if next_check_at else None
        if issue:
            item["last_seen_issue_id"] = issue.issue_id
            item["last_seen_issue_title"] = issue.best_title
            item["last_seen_issue_date"] = _date_to_str(issue.issue_date)
            item["last_seen_issue_url"] = issue.issue_url

    def record_download(self, magazine_id: str, issue: IssueInfo, file_path: Path, now: datetime) -> None:
        item = self.magazine(magazine_id)
        unique_key = make_unique_key(issue)
        record = {
            "unique_key": unique_key,
            "issue_id": issue.issue_id,
            "title": issue.best_title,
            "issue_date": _date_to_str(issue.issue_date),
            "issue_url": issue.issue_url,
            "file_path": str(file_path),
            "downloaded_at": now.isoformat(),
        }
        downloaded = item.setdefault("downloaded", [])
        if not any(existing.get("unique_key") == unique_key for existing in downloaded):
            downloaded.append(record)
        item["last_success_at"] = now.isoformat()
        item["last_downloaded_issue_id"] = issue.issue_id
        item["last_downloaded_issue_title"] = issue.best_title
        item["last_downloaded_issue_date"] = _date_to_str(issue.issue_date)
        item["last_file_path"] = str(file_path)


def make_unique_key(issue: IssueInfo) -> str:
    if issue.issue_id:
        return f"issue:{issue.issue_id}"
    if issue.issue_date:
        return f"magazine-date:{issue.magazine_id}:{issue.issue_date.isoformat()}"
    if issue.best_title:
        from .matching import normalize_title

        return f"title:{normalize_title(issue.best_title)}"
    return f"url:{issue.issue_url}"


def _date_to_str(value: date | None) -> str | None:
    return value.isoformat() if value else None

