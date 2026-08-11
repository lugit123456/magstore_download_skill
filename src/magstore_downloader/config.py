from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from .models import (
    AppConfig,
    BrowserConfig,
    Credentials,
    CredentialsConfig,
    DownloadConfig,
    FeishuConfig,
    LoggingConfig,
    MagazineConfig,
    RetryConfig,
    ScheduleConfig,
    SchedulerConfig,
    SiteConfig,
)


class ConfigError(ValueError):
    """Raised when local configuration is missing or invalid."""


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).expanduser().resolve()
    if not config_path.exists():
        raise ConfigError(f"配置文件不存在: {config_path}")

    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ConfigError("配置文件顶层必须是 YAML object")

    base = config_path.parent
    site_data = _dict(data, "site")
    browser_data = _dict(data, "browser", required=False)
    credentials_data = _dict(data, "credentials")
    scheduler_data = _dict(data, "scheduler", required=False)
    download_data = _dict(data, "download", required=False)
    logging_data = _dict(data, "logging", required=False)
    retry_data = _dict(data, "retry", required=False)
    notifications_data = _dict(data, "notifications", required=False)
    feishu_data = _dict(notifications_data, "feishu", required=False)

    magazines_raw = data.get("magazines")
    if not isinstance(magazines_raw, list) or not magazines_raw:
        raise ConfigError("magazines 必须是非空 list")

    magazines = tuple(_parse_magazine(item) for item in magazines_raw)
    ids = [mag.id for mag in magazines]
    if len(ids) != len(set(ids)):
        raise ConfigError("magazines.id 不能重复")

    return AppConfig(
        config_path=config_path,
        site=SiteConfig(
            base_url=_required_str(site_data, "base_url").rstrip("/"),
            login_path=str(site_data.get("login_path", "/login")),
            home_path=str(site_data.get("home_path", "/")),
        ),
        browser=BrowserConfig(
            headless_env=str(browser_data.get("headless_env", "MAGSTORE_HEADLESS")),
            channel=str(browser_data.get("channel", "chromium")),
            navigation_timeout_ms=_int(browser_data, "navigation_timeout_ms", 30_000),
            action_timeout_ms=_int(browser_data, "action_timeout_ms", 15_000),
            download_timeout_ms=_int(browser_data, "download_timeout_ms", 120_000),
            storage_state_path=_resolve_path(base, browser_data.get("storage_state_path", "./state/browser-state.json")),
        ),
        credentials=CredentialsConfig(
            username_env=str(credentials_data.get("username_env", "MAGSTORE_USERNAME")),
            password_env=str(credentials_data.get("password_env", "MAGSTORE_PASSWORD")),
        ),
        scheduler=SchedulerConfig(
            timezone=str(scheduler_data.get("timezone", "Asia/Shanghai")),
            run_time=str(scheduler_data.get("run_time", "07:00")),
        ),
        download=DownloadConfig(
            base_dir=_resolve_path(base, download_data.get("base_dir", "./downloads")),
            filename_conflict=_choice(download_data.get("filename_conflict", "skip"), {"skip", "overwrite", "append"}, "download.filename_conflict"),
            allowed_extensions=tuple(str(ext).lower() for ext in download_data.get("allowed_extensions", [".pdf"])),
            duplicate_check_uncertain=_choice(download_data.get("duplicate_check_uncertain", "skip"), {"skip"}, "download.duplicate_check_uncertain"),
            redownload_if_file_missing=bool(download_data.get("redownload_if_file_missing", False)),
        ),
        logging=LoggingConfig(
            level=str(logging_data.get("level", "INFO")),
            file=_resolve_path(base, logging_data.get("file", "./logs/magstore.log")),
            max_bytes=_int(logging_data, "max_bytes", 10_485_760),
            backup_count=_int(logging_data, "backup_count", 10),
            screenshot_dir=_resolve_path(base, logging_data.get("screenshot_dir", "./artifacts/screenshots")),
        ),
        retry=RetryConfig(
            login_attempts=_int(retry_data, "login_attempts", 2),
            search_attempts=_int(retry_data, "search_attempts", 2),
            download_attempts=_int(retry_data, "download_attempts", 2),
            backoff_seconds=float(retry_data.get("backoff_seconds", 5)),
        ),
        feishu=FeishuConfig(
            enabled=bool(feishu_data.get("enabled", False)),
            webhook_env=str(feishu_data.get("webhook_env", "FEISHU_WEBHOOK_URL")),
            timeout_seconds=float(feishu_data.get("timeout_seconds", 10)),
            notify_on_check_failure=bool(feishu_data.get("notify_on_check_failure", True)),
        ),
        magazines=magazines,
    )


def load_credentials(config: AppConfig) -> Credentials:
    load_env_file(config.config_dir / ".env")
    username = os.environ.get(config.credentials.username_env)
    password = os.environ.get(config.credentials.password_env)
    missing = []
    if not username:
        missing.append(config.credentials.username_env)
    if not password:
        missing.append(config.credentials.password_env)
    if missing:
        raise ConfigError(f"缺少账号环境变量: {', '.join(missing)}")
    return Credentials(username=username or "", password=password or "")


def ensure_runtime_dirs(config: AppConfig) -> None:
    config.download.base_dir.mkdir(parents=True, exist_ok=True)
    config.logging.file.parent.mkdir(parents=True, exist_ok=True)
    config.logging.screenshot_dir.mkdir(parents=True, exist_ok=True)
    config.browser.storage_state_path.parent.mkdir(parents=True, exist_ok=True)


def _parse_magazine(data: Any) -> MagazineConfig:
    if not isinstance(data, dict):
        raise ConfigError("magazines 中每一项必须是 object")
    schedule_data = _dict(data, "schedule")
    schedule_type = _choice(schedule_data.get("type"), {"daily", "weekly", "monthly", "interval", "manual"}, "schedule.type")
    schedule = ScheduleConfig(
        type=schedule_type,
        weekdays=tuple(_int_list(schedule_data.get("weekdays", []), "schedule.weekdays")),
        days=tuple(_int_list(schedule_data.get("days", []), "schedule.days")),
        interval_days=schedule_data.get("interval_days"),
    )
    _validate_schedule(schedule)
    match_mode = _choice(data.get("match_mode", "prefix"), {"exact", "prefix", "contains", "regex"}, "magazine.match_mode")
    if match_mode == "regex" and not data.get("regex") and not data.get("magazine_name"):
        raise ConfigError("regex 匹配需要配置 regex 或 magazine_name")
    return MagazineConfig(
        id=_required_str(data, "id"),
        enabled=bool(data.get("enabled", True)),
        magazine_name=_required_str(data, "magazine_name"),
        search_term=str(data.get("search_term") or data.get("magazine_name") or ""),
        match_mode=match_mode,
        schedule=schedule,
        download_subdir=str(data.get("download_subdir") or data.get("id")),
        regex=data.get("regex"),
    )


def _validate_schedule(schedule: ScheduleConfig) -> None:
    if schedule.type == "weekly":
        if not schedule.weekdays or any(day < 1 or day > 7 for day in schedule.weekdays):
            raise ConfigError("weekly schedule.weekdays 必须包含 1-7")
    if schedule.type == "monthly":
        if not schedule.days or any(day < 1 or day > 31 for day in schedule.days):
            raise ConfigError("monthly schedule.days 必须包含 1-31")
    if schedule.type == "interval":
        if not isinstance(schedule.interval_days, int) or schedule.interval_days < 1:
            raise ConfigError("interval schedule.interval_days 必须是正整数")


def _dict(data: dict[str, Any], key: str, required: bool = True) -> dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ConfigError(f"{key} 必须是 object")
    if required and not value:
        raise ConfigError(f"缺少配置段: {key}")
    return value


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"缺少字符串配置: {key}")
    return value.strip()


def _int(data: dict[str, Any], key: str, default: int) -> int:
    value = data.get(key, default)
    if not isinstance(value, int):
        raise ConfigError(f"{key} 必须是整数")
    return value


def _int_list(value: Any, key: str) -> list[int]:
    if not isinstance(value, list):
        raise ConfigError(f"{key} 必须是整数 list")
    if not all(isinstance(item, int) for item in value):
        raise ConfigError(f"{key} 只能包含整数")
    return value


def _choice(value: Any, allowed: set[str], key: str) -> Any:
    if value not in allowed:
        raise ConfigError(f"{key} 必须是: {', '.join(sorted(allowed))}")
    return value


def _resolve_path(base: Path, value: Any) -> Path:
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()
