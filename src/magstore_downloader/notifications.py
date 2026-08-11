from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from urllib.request import Request, urlopen

from .models import AppConfig, RunSummary
from .state import StateStore


@dataclass(frozen=True)
class FinalCheckItem:
    magazine_id: str
    magazine_name: str
    issue_title: str | None
    issue_date: str | None
    reason: str


@dataclass
class FinalCheckReport:
    checked_at: datetime
    not_updated: list[FinalCheckItem] = field(default_factory=list)
    check_failed: list[FinalCheckItem] = field(default_factory=list)

    @property
    def magazine_ids(self) -> set[str]:
        return {item.magazine_id for item in self.not_updated + self.check_failed}

    @property
    def has_alerts(self) -> bool:
        return bool(self.not_updated or self.check_failed)


class NotificationError(RuntimeError):
    pass


def build_final_check_report(
    config: AppConfig,
    state: StateStore,
    summary: RunSummary,
    checked_at: datetime,
) -> FinalCheckReport:
    report = FinalCheckReport(checked_at=checked_at)
    magazine_names = {magazine.id: magazine.magazine_name for magazine in config.magazines}
    for result in summary.results:
        if state.cycle_notification_sent(result.magazine_id):
            continue
        classification = state.classify_final_result(result.magazine_id)
        if classification == "updated":
            continue
        cycle = state.magazine(result.magazine_id).get("retry_cycle") or {}
        item = FinalCheckItem(
            magazine_id=result.magazine_id,
            magazine_name=magazine_names.get(result.magazine_id, result.magazine_id),
            issue_title=cycle.get("last_issue_title"),
            issue_date=cycle.get("last_issue_date"),
            reason=cycle.get("last_message") or result.message,
        )
        if classification == "not_updated":
            report.not_updated.append(item)
        elif config.feishu.notify_on_check_failure:
            report.check_failed.append(item)
    return report


def send_feishu_report(config: AppConfig, report: FinalCheckReport) -> None:
    webhook_url = os.environ.get(config.feishu.webhook_env)
    if not webhook_url:
        raise NotificationError(f"缺少飞书 webhook 环境变量: {config.feishu.webhook_env}")

    payload = {
        "msg_type": "text",
        "content": {"text": _format_report(report)},
    }
    request = Request(
        webhook_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=config.feishu.timeout_seconds) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise NotificationError(f"飞书通知请求失败: {exc}") from exc

    if not _is_success_response(response_data):
        if isinstance(response_data, dict):
            message = response_data.get("msg") or response_data.get("StatusMessage") or "unknown error"
        else:
            message = "unexpected response"
        raise NotificationError(f"飞书通知发送失败: {message}")


def _format_report(report: FinalCheckReport) -> str:
    lines = [
        "MagStore 最终检查",
        f"检查时间：{report.checked_at.strftime('%Y-%m-%d %H:%M:%S %Z')}",
    ]
    if report.not_updated:
        lines.extend(["", "截至最后一次抓取仍未更新："])
        for item in report.not_updated:
            issue = item.issue_title or "未知期刊"
            if item.issue_date:
                issue = f"{issue}（{item.issue_date}）"
            lines.append(f"- {item.magazine_name}：{issue}")
    if report.check_failed:
        lines.extend(["", "最终检查失败，无法确认是否更新："])
        for item in report.check_failed:
            lines.append(f"- {item.magazine_name}：{item.reason}")
    return "\n".join(lines)


def _is_success_response(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return value.get("code") == 0 or value.get("StatusCode") == 0
