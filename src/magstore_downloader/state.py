from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .models import AttemptKind, IssueInfo, MagazineRunResult


FINAL_REUSE_WINDOW = timedelta(hours=12)


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

    def prepare_attempt(self, magazine_id: str, attempt: AttemptKind, now: datetime) -> None:
        if attempt == "regular":
            return
        item = self.magazine(magazine_id)
        cycle = item.get("retry_cycle")
        should_start = attempt == "first" or not isinstance(cycle, dict)
        if isinstance(cycle, dict) and cycle.get("finalized_at"):
            finalized_at = _parse_datetime(cycle.get("finalized_at"))
            if finalized_at is not None and finalized_at.tzinfo is None:
                finalized_at = finalized_at.replace(tzinfo=now.tzinfo)
            elapsed = now - finalized_at if finalized_at is not None else None
            recently_finalized = elapsed is not None and timedelta(0) <= elapsed <= FINAL_REUSE_WINDOW
            should_start = attempt != "final" or not recently_finalized
        if should_start:
            item["retry_cycle"] = {
                "cycle_id": now.isoformat(),
                "started_at": now.isoformat(),
                "baseline_issue_id": item.get("last_downloaded_issue_id"),
                "baseline_issue_title": item.get("last_downloaded_issue_title"),
                "baseline_issue_date": item.get("last_downloaded_issue_date"),
                "baseline_issue_key": _last_downloaded_key(magazine_id, item),
                "downloaded_in_cycle": False,
                "attempts": [],
            }

    def record_attempt_result(
        self,
        magazine_id: str,
        attempt: AttemptKind,
        result: MagazineRunResult,
        now: datetime,
    ) -> None:
        if attempt == "regular":
            return
        cycle = self.magazine(magazine_id).get("retry_cycle")
        if not isinstance(cycle, dict):
            return
        issue_key = make_unique_key(result.issue) if result.issue else None
        cycle.setdefault("attempts", []).append(
            {
                "kind": attempt,
                "checked_at": now.isoformat(),
                "status": result.status,
                "message": result.message,
                "issue_key": issue_key,
                "issue_title": result.issue.best_title if result.issue else None,
                "issue_date": _date_to_str(result.issue.issue_date) if result.issue else None,
            }
        )
        cycle["last_attempt_at"] = now.isoformat()
        cycle["last_status"] = result.status
        cycle["last_message"] = result.message
        cycle["last_issue_key"] = issue_key
        cycle["last_issue_title"] = result.issue.best_title if result.issue else None
        cycle["last_issue_date"] = _date_to_str(result.issue.issue_date) if result.issue else None
        if result.status == "downloaded" or result.message in {"local-file-title", "file-exists-skip"}:
            cycle["downloaded_in_cycle"] = True
            cycle["downloaded_issue_key"] = issue_key
            cycle["downloaded_at"] = now.isoformat()

    def classify_final_result(self, magazine_id: str) -> str:
        cycle = self.magazine(magazine_id).get("retry_cycle")
        if not isinstance(cycle, dict):
            return "check_failed"
        if cycle.get("downloaded_in_cycle"):
            return "updated"
        baseline_key = cycle.get("baseline_issue_key")
        last_issue_key = cycle.get("last_issue_key")
        if baseline_key and last_issue_key == baseline_key and cycle.get("last_status") == "skipped":
            return "not_updated"
        return "check_failed"

    def finalize_cycle(self, magazine_id: str, now: datetime, notified: bool = False) -> None:
        cycle = self.magazine(magazine_id).get("retry_cycle")
        if not isinstance(cycle, dict):
            return
        cycle["finalized_at"] = now.isoformat()
        if notified:
            cycle["notification_sent_at"] = now.isoformat()

    def cycle_notification_sent(self, magazine_id: str) -> bool:
        cycle = self.magazine(magazine_id).get("retry_cycle")
        return isinstance(cycle, dict) and bool(cycle.get("notification_sent_at"))


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


def _last_downloaded_key(magazine_id: str, item: dict[str, Any]) -> str | None:
    issue_id = item.get("last_downloaded_issue_id")
    if issue_id:
        return f"issue:{issue_id}"
    issue_date = item.get("last_downloaded_issue_date")
    if issue_date:
        return f"magazine-date:{magazine_id}:{issue_date}"
    title = item.get("last_downloaded_issue_title")
    if title:
        from .matching import normalize_title

        return f"title:{normalize_title(title)}"
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
