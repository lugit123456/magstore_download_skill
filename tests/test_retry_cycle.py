from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from magstore_downloader.models import IssueInfo, MagazineRunResult
from magstore_downloader.state import StateStore


TZ = ZoneInfo("Asia/Shanghai")


def issue(issue_id: str, title: str) -> IssueInfo:
    return IssueInfo(
        magazine_id="wsj",
        search_title=title,
        detail_title=title,
        issue_url=f"https://example.test/issue/{issue_id}",
        issue_id=issue_id,
        issue_date=None,
    )


class RetryCycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.state = StateStore(Path(self.temp_dir.name) / "state.json")
        magazine = self.state.magazine("wsj")
        magazine["last_downloaded_issue_id"] = "old"
        magazine["last_downloaded_issue_title"] = "Old issue"

    def test_download_in_earlier_attempt_prevents_final_alert(self) -> None:
        started_at = datetime(2026, 8, 11, 23, tzinfo=TZ)
        new_issue = issue("new", "New issue")
        self.state.prepare_attempt("wsj", "first", started_at)
        self.state.record_attempt_result(
            "wsj",
            "first",
            MagazineRunResult("wsj", "downloaded", "downloaded", issue=new_issue),
            started_at,
        )
        self.state.prepare_attempt("wsj", "final", started_at + timedelta(hours=10))
        self.state.record_attempt_result(
            "wsj",
            "final",
            MagazineRunResult("wsj", "skipped", "last-downloaded-issue-id", issue=new_issue),
            started_at + timedelta(hours=10),
        )

        self.assertEqual("updated", self.state.classify_final_result("wsj"))

    def test_unchanged_issue_is_not_updated_on_final_attempt(self) -> None:
        started_at = datetime(2026, 8, 11, 23, tzinfo=TZ)
        old_issue = issue("old", "Old issue")
        self.state.prepare_attempt("wsj", "first", started_at)
        for kind, offset in (("first", 0), ("retry", 3), ("final", 10)):
            self.state.record_attempt_result(
                "wsj",
                kind,
                MagazineRunResult("wsj", "skipped", "last-downloaded-issue-id", issue=old_issue),
                started_at + timedelta(hours=offset),
            )

        self.assertEqual("not_updated", self.state.classify_final_result("wsj"))

    def test_failure_is_not_misreported_as_not_updated(self) -> None:
        started_at = datetime(2026, 8, 11, 23, tzinfo=TZ)
        self.state.prepare_attempt("wsj", "first", started_at)
        self.state.record_attempt_result(
            "wsj",
            "final",
            MagazineRunResult("wsj", "failed", "login timeout"),
            started_at + timedelta(hours=10),
        )

        self.assertEqual("check_failed", self.state.classify_final_result("wsj"))

    def test_local_file_backfill_counts_as_updated(self) -> None:
        started_at = datetime(2026, 8, 11, 23, tzinfo=TZ)
        new_issue = issue("new", "New issue")
        self.state.prepare_attempt("wsj", "first", started_at)
        self.state.record_attempt_result(
            "wsj",
            "first",
            MagazineRunResult("wsj", "skipped", "local-file-title", issue=new_issue),
            started_at,
        )

        self.assertEqual("updated", self.state.classify_final_result("wsj"))

    def test_repeated_final_reuses_recent_cycle_and_notification_marker(self) -> None:
        started_at = datetime(2026, 8, 11, 23, tzinfo=TZ)
        final_at = started_at + timedelta(hours=10)
        self.state.prepare_attempt("wsj", "first", started_at)
        cycle_id = self.state.magazine("wsj")["retry_cycle"]["cycle_id"]
        self.state.finalize_cycle("wsj", final_at, notified=True)

        self.state.prepare_attempt("wsj", "final", final_at + timedelta(minutes=30))

        cycle = self.state.magazine("wsj")["retry_cycle"]
        self.assertEqual(cycle_id, cycle["cycle_id"])
        self.assertTrue(self.state.cycle_notification_sent("wsj"))


if __name__ == "__main__":
    unittest.main()
