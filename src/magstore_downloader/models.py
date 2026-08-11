from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal


MatchMode = Literal["exact", "prefix", "contains", "regex"]
ScheduleType = Literal["daily", "weekly", "monthly", "interval", "manual"]
FilenameConflict = Literal["skip", "overwrite", "append"]
UncertainPolicy = Literal["skip"]
AttemptKind = Literal["regular", "first", "retry", "final"]


@dataclass(frozen=True)
class SiteConfig:
    base_url: str
    login_path: str = "/login"
    home_path: str = "/"


@dataclass(frozen=True)
class BrowserConfig:
    headless_env: str = "MAGSTORE_HEADLESS"
    channel: str = "chromium"
    navigation_timeout_ms: int = 30_000
    action_timeout_ms: int = 15_000
    download_timeout_ms: int = 120_000
    storage_state_path: Path = Path("./state/browser-state.json")


@dataclass(frozen=True)
class CredentialsConfig:
    username_env: str = "MAGSTORE_USERNAME"
    password_env: str = "MAGSTORE_PASSWORD"


@dataclass(frozen=True)
class SchedulerConfig:
    timezone: str = "Asia/Shanghai"
    run_time: str = "07:00"


@dataclass(frozen=True)
class DownloadConfig:
    base_dir: Path = Path("./downloads")
    filename_conflict: FilenameConflict = "skip"
    allowed_extensions: tuple[str, ...] = (".pdf",)
    duplicate_check_uncertain: UncertainPolicy = "skip"
    redownload_if_file_missing: bool = False


@dataclass(frozen=True)
class LoggingConfig:
    level: str = "INFO"
    file: Path = Path("./logs/magstore.log")
    max_bytes: int = 10_485_760
    backup_count: int = 10
    screenshot_dir: Path = Path("./artifacts/screenshots")


@dataclass(frozen=True)
class RetryConfig:
    login_attempts: int = 2
    search_attempts: int = 2
    download_attempts: int = 2
    backoff_seconds: float = 5.0


@dataclass(frozen=True)
class FeishuConfig:
    enabled: bool = False
    webhook_env: str = "FEISHU_WEBHOOK_URL"
    timeout_seconds: float = 10.0
    notify_on_check_failure: bool = True


@dataclass(frozen=True)
class ScheduleConfig:
    type: ScheduleType
    weekdays: tuple[int, ...] = ()
    days: tuple[int, ...] = ()
    interval_days: int | None = None


@dataclass(frozen=True)
class MagazineConfig:
    id: str
    enabled: bool
    magazine_name: str
    search_term: str
    match_mode: MatchMode
    schedule: ScheduleConfig
    download_subdir: str
    regex: str | None = None


@dataclass(frozen=True)
class AppConfig:
    config_path: Path
    site: SiteConfig
    browser: BrowserConfig
    credentials: CredentialsConfig
    scheduler: SchedulerConfig
    download: DownloadConfig
    logging: LoggingConfig
    retry: RetryConfig
    feishu: FeishuConfig
    magazines: tuple[MagazineConfig, ...]

    @property
    def config_dir(self) -> Path:
        return self.config_path.parent


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str


@dataclass(frozen=True)
class IssueInfo:
    magazine_id: str
    search_title: str | None
    detail_title: str | None
    issue_url: str
    issue_id: str | None
    issue_date: date | None

    @property
    def best_title(self) -> str | None:
        return self.detail_title or self.search_title


@dataclass(frozen=True)
class DuplicateResult:
    duplicate: bool
    uncertain: bool
    reason: str
    matched_record: dict[str, Any] | None = None
    backfill_file_path: Path | None = None


@dataclass
class MagazineRunResult:
    magazine_id: str
    status: str
    message: str
    downloaded_path: Path | None = None
    issue: IssueInfo | None = None


@dataclass
class RunSummary:
    planned: int = 0
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    results: list[MagazineRunResult] = field(default_factory=list)

    def add(self, result: MagazineRunResult) -> None:
        self.results.append(result)
        if result.status == "downloaded":
            self.downloaded += 1
        elif result.status == "failed":
            self.failed += 1
        else:
            self.skipped += 1
