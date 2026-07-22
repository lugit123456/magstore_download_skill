from __future__ import annotations

import calendar
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .models import MagazineConfig, ScheduleConfig, SchedulerConfig


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def scheduler_timezone(config: SchedulerConfig) -> ZoneInfo:
    return ZoneInfo(config.timezone)


def now_in_timezone(config: SchedulerConfig) -> datetime:
    return datetime.now(tz=scheduler_timezone(config))


def is_magazine_due(
    magazine: MagazineConfig,
    magazine_state: dict,
    now: datetime,
    force: bool = False,
    explicitly_selected: bool = False,
) -> tuple[bool, str]:
    if not magazine.enabled:
        return False, "disabled"
    if force:
        return True, "force"
    if magazine.schedule.type == "manual":
        return (True, "manual-selected") if explicitly_selected else (False, "manual")

    next_check = parse_iso_datetime(magazine_state.get("next_check_at"))
    if next_check is None:
        return True, "never-checked"
    if next_check.tzinfo is None:
        next_check = next_check.replace(tzinfo=now.tzinfo)
    if now >= next_check.astimezone(now.tzinfo):
        return True, "due"
    return False, f"next-check-at {next_check.isoformat()}"


def compute_next_check(schedule: ScheduleConfig, scheduler: SchedulerConfig, now: datetime) -> datetime | None:
    if schedule.type == "manual":
        return None
    run_time = _parse_run_time(scheduler.run_time)
    now = now.astimezone(scheduler_timezone(scheduler))
    if schedule.type == "daily":
        return _next_daily(now, run_time)
    if schedule.type == "weekly":
        return _next_weekly(now, run_time, schedule.weekdays)
    if schedule.type == "monthly":
        return _next_monthly(now, run_time, schedule.days)
    if schedule.type == "interval":
        return (now + timedelta(days=schedule.interval_days or 1)).replace(
            hour=run_time.hour,
            minute=run_time.minute,
            second=0,
            microsecond=0,
        )
    raise ValueError(f"未知 schedule.type: {schedule.type}")


def _parse_run_time(value: str) -> time:
    hour_text, minute_text = value.split(":", 1)
    return time(hour=int(hour_text), minute=int(minute_text))


def _combine(day: datetime, run_time: time) -> datetime:
    return day.replace(hour=run_time.hour, minute=run_time.minute, second=0, microsecond=0)


def _next_daily(now: datetime, run_time: time) -> datetime:
    candidate = _combine(now, run_time)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def _next_weekly(now: datetime, run_time: time, weekdays: tuple[int, ...]) -> datetime:
    for offset in range(0, 14):
        candidate_day = now + timedelta(days=offset)
        if candidate_day.isoweekday() not in weekdays:
            continue
        candidate = _combine(candidate_day, run_time)
        if candidate > now:
            return candidate
    raise RuntimeError("无法计算 weekly next_check_at")


def _next_monthly(now: datetime, run_time: time, days: tuple[int, ...]) -> datetime:
    for month_offset in range(0, 15):
        year = now.year + (now.month - 1 + month_offset) // 12
        month = (now.month - 1 + month_offset) % 12 + 1
        last_day = calendar.monthrange(year, month)[1]
        for day in sorted(days):
            if day > last_day:
                continue
            candidate = now.replace(year=year, month=month, day=day)
            candidate = _combine(candidate, run_time)
            if candidate > now:
                return candidate
    raise RuntimeError("无法计算 monthly next_check_at")

