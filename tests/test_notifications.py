from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from magstore_downloader.config import load_config
from magstore_downloader.models import IssueInfo, MagazineRunResult, RunSummary
from magstore_downloader.notifications import NotificationError, build_final_check_report, send_feishu_report
from magstore_downloader.state import StateStore


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return b'{"code": 0, "msg": "success"}'


class InvalidResponse(FakeResponse):
    def read(self) -> bytes:
        return b"[]"


class NotificationsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.state = StateStore(Path(self.temp_dir.name) / "state.json")
        self.config = load_config(Path(__file__).parents[1] / "config.yaml")
        self.now = datetime(2026, 8, 12, 9, tzinfo=ZoneInfo("Asia/Shanghai"))

    def test_builds_not_updated_report(self) -> None:
        magazine = self.state.magazine("wsj")
        magazine["last_downloaded_issue_id"] = "old"
        magazine["last_downloaded_issue_title"] = "Old issue"
        issue = IssueInfo("wsj", "Old issue", "Old issue", "https://example.test/issue/old", "old", None)
        self.state.prepare_attempt("wsj", "first", self.now)
        result = MagazineRunResult("wsj", "skipped", "last-downloaded-issue-id", issue=issue)
        self.state.record_attempt_result("wsj", "final", result, self.now)
        summary = RunSummary(planned=1)
        summary.add(result)

        report = build_final_check_report(self.config, self.state, summary, self.now)

        self.assertEqual(["wsj"], [item.magazine_id for item in report.not_updated])
        self.assertFalse(report.check_failed)

    def test_sends_expected_feishu_payload_without_real_network(self) -> None:
        magazine = self.state.magazine("wsj")
        magazine["last_downloaded_issue_id"] = "old"
        magazine["last_downloaded_issue_title"] = "Old issue"
        issue = IssueInfo("wsj", "Old issue", "Old issue", "https://example.test/issue/old", "old", None)
        self.state.prepare_attempt("wsj", "first", self.now)
        result = MagazineRunResult("wsj", "skipped", "last-downloaded-issue-id", issue=issue)
        self.state.record_attempt_result("wsj", "final", result, self.now)
        summary = RunSummary(planned=1)
        summary.add(result)
        report = build_final_check_report(self.config, self.state, summary, self.now)

        with patch.dict(os.environ, {self.config.feishu.webhook_env: "https://example.test/webhook"}), patch(
            "magstore_downloader.notifications.urlopen", return_value=FakeResponse()
        ) as mocked_urlopen:
            send_feishu_report(self.config, report)

        request = mocked_urlopen.call_args.args[0]
        payload = request.data.decode("utf-8")
        self.assertIn("截至最后一次抓取仍未更新", payload)
        self.assertIn("The Wall Street Journal", payload)

    def test_rejects_unexpected_feishu_response(self) -> None:
        report = build_final_check_report(self.config, self.state, RunSummary(), self.now)
        with patch.dict(os.environ, {self.config.feishu.webhook_env: "https://example.test/webhook"}), patch(
            "magstore_downloader.notifications.urlopen", return_value=InvalidResponse()
        ):
            with self.assertRaises(NotificationError):
                send_feishu_report(self.config, report)


if __name__ == "__main__":
    unittest.main()
