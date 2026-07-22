from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, TypeVar
from urllib.parse import quote, urljoin

from .dedupe import check_duplicate
from .filenames import ensure_allowed_extension, resolve_conflict_path, sanitize_filename
from .logging_utils import extra
from .matching import extract_issue_date, extract_issue_id, title_matches
from .models import AppConfig, Credentials, IssueInfo, MagazineConfig, MagazineRunResult, RunSummary
from .schedule import compute_next_check, is_magazine_due, now_in_timezone
from .selectors import (
    DOWNLOAD_BUTTON_TEXT,
    ISSUE_HEADER_SELECTOR,
    LOGIN_BUTTON_TEXT,
    LOGIN_PASSWORD_PLACEHOLDER,
    LOGIN_USERNAME_PLACEHOLDER,
    RESULT_ITEM_SELECTOR,
    RESULT_TITLE_SELECTOR,
    SEARCH_PLACEHOLDER,
)
from .state import StateStore


T = TypeVar("T")


class MagStoreRunner:
    def __init__(
        self,
        config: AppConfig,
        credentials: Credentials,
        state: StateStore,
        logger,
        headed: bool = False,
        dry_run: bool = False,
        redownload: bool = False,
    ):
        self.config = config
        self.credentials = credentials
        self.state = state
        self.logger = logger
        self.headed = headed
        self.dry_run = dry_run
        self.redownload = redownload

    def run(self, selected_magazine: str | None = None, force: bool = False) -> RunSummary:
        magazines = self._select_due_magazines(selected_magazine, force)
        summary = RunSummary(planned=len(magazines))
        if not magazines:
            self.logger.info("没有到期的杂志任务", extra=extra(phase="schedule"))
            return summary

        try:
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("缺少 Playwright，请先执行: pip install -e . && playwright install chromium") from exc

        with sync_playwright() as p:
            browser = self._launch_browser(p)
            context_kwargs = {"accept_downloads": True}
            if self.config.browser.storage_state_path.exists():
                context_kwargs["storage_state"] = str(self.config.browser.storage_state_path)
            context = browser.new_context(**context_kwargs)
            context.set_default_navigation_timeout(self.config.browser.navigation_timeout_ms)
            context.set_default_timeout(self.config.browser.action_timeout_ms)
            page = context.new_page()
            try:
                self._ensure_logged_in(page, PlaywrightTimeoutError)
                context.storage_state(path=str(self.config.browser.storage_state_path))
                for magazine in magazines:
                    result = self._run_magazine(page, magazine, PlaywrightTimeoutError)
                    summary.add(result)
                    if not self.dry_run:
                        self.state.save()
            finally:
                self.logger.info("关闭浏览器", extra=extra(phase="browser"))
                context.close()
                browser.close()
        return summary

    def _select_due_magazines(self, selected_magazine: str | None, force: bool) -> list[MagazineConfig]:
        magazines = []
        now = now_in_timezone(self.config.scheduler)
        known_ids = {mag.id for mag in self.config.magazines}
        if selected_magazine and selected_magazine not in known_ids:
            raise ValueError(f"配置中不存在杂志: {selected_magazine}")

        for magazine in self.config.magazines:
            if selected_magazine and magazine.id != selected_magazine:
                continue
            due, reason = is_magazine_due(
                magazine,
                self.state.magazine(magazine.id),
                now,
                force=force,
                explicitly_selected=selected_magazine == magazine.id,
            )
            self.logger.info(
                "任务判断: %s",
                reason,
                extra=extra(magazine.id, "schedule"),
            )
            if due:
                magazines.append(magazine)
        return magazines

    def _launch_browser(self, playwright):
        headless = self._headless()
        self.logger.info("启动 Chromium headless=%s", headless, extra=extra(phase="browser"))
        channel = self.config.browser.channel
        if channel and channel != "chromium":
            return playwright.chromium.launch(channel=channel, headless=headless)
        return playwright.chromium.launch(headless=headless)

    def _headless(self) -> bool:
        if self.headed:
            return False
        value = os.environ.get(self.config.browser.headless_env, "true").strip().lower()
        return value not in {"0", "false", "no", "off"}

    def _ensure_logged_in(self, page, timeout_error_type) -> None:
        home_url = urljoin(self.config.site.base_url + "/", self.config.site.home_path.lstrip("/"))
        navigation_aborted = self._goto(page, home_url, phase="login")
        if not navigation_aborted and not self._is_login_page(page) and self._search_box_visible(page):
            self.logger.info("已处于登录状态", extra=extra(phase="login"))
            return
        if navigation_aborted or self._is_login_page(page):
            self._clear_login_state(page, "-", "login")
        self._with_retry(lambda: self._login(page), self.config.retry.login_attempts, "login", timeout_error_type)

    def _search_box_visible(self, page) -> bool:
        try:
            page.get_by_placeholder(SEARCH_PLACEHOLDER).wait_for(timeout=3_000)
            return True
        except Exception:
            return False

    def _login(self, page) -> None:
        login_url = urljoin(self.config.site.base_url + "/", self.config.site.login_path.lstrip("/"))
        self.logger.info("打开登录页", extra=extra(phase="login"))
        self._goto(page, login_url, phase="login")
        page.get_by_placeholder(LOGIN_USERNAME_PLACEHOLDER).fill(self.credentials.username)
        page.get_by_placeholder(LOGIN_PASSWORD_PLACEHOLDER).fill(self.credentials.password)
        page.get_by_role("button", name=LOGIN_BUTTON_TEXT, exact=True).click()
        page.get_by_placeholder(SEARCH_PLACEHOLDER).wait_for(timeout=self.config.browser.navigation_timeout_ms)
        self.logger.info("登录成功", extra=extra(phase="login"))

    def _ensure_search_ready(self, page, magazine_id: str, timeout_error_type) -> None:
        home_url = urljoin(self.config.site.base_url + "/", self.config.site.home_path.lstrip("/"))
        navigation_aborted = self._goto(page, home_url, magazine_id, "search")
        if not navigation_aborted and not self._is_login_page(page) and self._search_box_visible(page):
            return

        self.logger.warning(
            "首页不可搜索，清除登录态并重新登录",
            extra=extra(magazine_id, "login"),
        )
        self._clear_login_state(page, magazine_id, "login")
        self._with_retry(lambda: self._login(page), self.config.retry.login_attempts, "login", timeout_error_type, magazine_id)
        page.context.storage_state(path=str(self.config.browser.storage_state_path))

    def _run_magazine(self, page, magazine: MagazineConfig, timeout_error_type) -> MagazineRunResult:
        try:
            return self._with_retry(
                lambda: self._run_magazine_once(page, magazine, timeout_error_type),
                self.config.retry.search_attempts,
                f"search:{magazine.id}",
                timeout_error_type,
                magazine.id,
            )
        except Exception as exc:
            self._screenshot(page, magazine.id, "failed")
            self.logger.exception("杂志任务失败: %s", exc, extra=extra(magazine.id, "failed"))
            return MagazineRunResult(magazine.id, "failed", str(exc))

    def _run_magazine_once(self, page, magazine: MagazineConfig, timeout_error_type) -> MagazineRunResult:
        now = now_in_timezone(self.config.scheduler)
        self.logger.info("开始搜索: %s", magazine.search_term, extra=extra(magazine.id, "search"))
        self._ensure_search_ready(page, magazine.id, timeout_error_type)
        search_url = _build_search_url(self.config.site.base_url, magazine.search_term)
        self.logger.info("打开搜索页: %s", search_url, extra=extra(magazine.id, "search"))
        self._goto(page, search_url, magazine.id, "search")
        if self._is_login_page(page):
            self.logger.warning("搜索页跳转到登录页，重新登录后重试搜索", extra=extra(magazine.id, "login"))
            self._clear_login_state(page, magazine.id, "login")
            self._with_retry(lambda: self._login(page), self.config.retry.login_attempts, "login", timeout_error_type, magazine.id)
            self._goto(page, search_url, magazine.id, "search")
        page.wait_for_url("**/search/**", timeout=self.config.browser.navigation_timeout_ms)

        result_items = page.locator(RESULT_ITEM_SELECTOR)
        if not self._wait_for_result_items(result_items):
            return self._checked_skip(magazine, None, now, "no-search-results")
        selected_title = None
        selected_index = None
        count = result_items.count()
        self.logger.info("搜索结果候选数量: %s", count, extra=extra(magazine.id, "search"))
        for index in range(count):
            item = result_items.nth(index)
            title = self._result_title(item)
            if index < 10:
                self.logger.info(
                    "候选结果 %s: %s",
                    index + 1,
                    title or "<empty>",
                    extra=extra(magazine.id, "search"),
                )
            if title_matches(title, magazine):
                selected_title = title
                selected_index = index
                break
        if selected_index is None:
            return self._checked_skip(magazine, None, now, "no-matching-result")

        self.logger.info("选中搜索结果: %s", selected_title, extra=extra(magazine.id, "search"))
        selected_item = result_items.nth(selected_index)
        selected_item.scroll_into_view_if_needed()
        selected_item.click()
        page.wait_for_url("**/issue/**", timeout=self.config.browser.navigation_timeout_ms)
        page.locator(ISSUE_HEADER_SELECTOR).wait_for(timeout=self.config.browser.action_timeout_ms)

        detail_title = _compact_text(page.locator(ISSUE_HEADER_SELECTOR).first.inner_text())
        issue = IssueInfo(
            magazine_id=magazine.id,
            search_title=selected_title,
            detail_title=detail_title,
            issue_url=page.url,
            issue_id=extract_issue_id(page.url),
            issue_date=extract_issue_date(detail_title or selected_title),
        )
        self.logger.info(
            "详情页 issue_id=%s title=%s date=%s",
            issue.issue_id,
            issue.best_title,
            issue.issue_date,
            extra=extra(magazine.id, "dedupe"),
        )

        magazine_dir = self.config.download.base_dir / magazine.download_subdir
        duplicate = check_duplicate(
            issue,
            magazine,
            self.state.magazine(magazine.id),
            magazine_dir,
            redownload=self.redownload,
            redownload_if_file_missing=self.config.download.redownload_if_file_missing,
        )
        if duplicate.uncertain:
            self._screenshot(page, magazine.id, duplicate.reason)
            return self._checked_skip(magazine, issue, now, duplicate.reason)
        if duplicate.duplicate:
            if duplicate.backfill_file_path and not self.dry_run:
                self.state.record_download(magazine.id, issue, duplicate.backfill_file_path, now)
            return self._checked_skip(magazine, issue, now, duplicate.reason)

        if self.dry_run:
            self.logger.info("dry-run: 不点击下载按钮且不更新 state", extra=extra(magazine.id, "download"))
            return MagazineRunResult(magazine.id, "skipped", "dry-run", issue=issue)

        downloaded_path = self._with_retry(
            lambda: self._download_issue(page, magazine, issue),
            self.config.retry.download_attempts,
            f"download:{magazine.id}",
            Exception,
            magazine.id,
        )
        next_check_at = compute_next_check(magazine.schedule, self.config.scheduler, now)
        self.state.mark_checked(magazine.id, issue, now, next_check_at)
        self.state.record_download(magazine.id, issue, downloaded_path, now)
        self.logger.info("下载成功: %s", downloaded_path, extra=extra(magazine.id, "download"))
        return MagazineRunResult(magazine.id, "downloaded", "downloaded", downloaded_path, issue)

    def _checked_skip(
        self,
        magazine: MagazineConfig,
        issue: IssueInfo | None,
        now: datetime,
        reason: str,
    ) -> MagazineRunResult:
        if not self.dry_run:
            next_check_at = compute_next_check(magazine.schedule, self.config.scheduler, now)
            self.state.mark_checked(magazine.id, issue, now, next_check_at)
        self.logger.warning("跳过: %s", reason, extra=extra(magazine.id, "skip"))
        return MagazineRunResult(magazine.id, "skipped", reason, issue=issue)

    def _download_issue(self, page, magazine: MagazineConfig, issue: IssueInfo) -> Path:
        magazine_dir = self.config.download.base_dir / magazine.download_subdir
        magazine_dir.mkdir(parents=True, exist_ok=True)
        with page.expect_download(timeout=self.config.browser.download_timeout_ms) as download_info:
            page.get_by_role("button", name=DOWNLOAD_BUTTON_TEXT, exact=True).click()
        download = download_info.value
        suggested = download.suggested_filename or f"{issue.best_title or issue.issue_id or magazine.id}.pdf"
        safe_name = sanitize_filename(ensure_allowed_extension(suggested, self.config.download.allowed_extensions))
        target = resolve_conflict_path(magazine_dir / safe_name, self.config.download.filename_conflict)
        if target is None:
            raise FileExistsError(f"目标文件已存在且 filename_conflict=skip: {magazine_dir / safe_name}")
        download.save_as(str(target))
        if not target.exists() or target.stat().st_size <= 0:
            raise RuntimeError(f"下载文件为空或不存在: {target}")
        return target

    def _goto(self, page, url: str, magazine_id: str = "-", phase: str = "navigation") -> bool:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=self.config.browser.navigation_timeout_ms)
            return False
        except Exception as exc:
            if not _is_navigation_aborted(exc):
                raise
            self.logger.warning(
                "页面导航被前端中断，继续等待可用页面: %s",
                url,
                extra=extra(magazine_id, phase),
            )
            try:
                page.wait_for_load_state("domcontentloaded", timeout=3_000)
            except Exception:
                pass
            return True

    def _is_login_page(self, page) -> bool:
        return _is_login_url(page.url, self.config.site.login_path)

    def _clear_login_state(self, page, magazine_id: str, phase: str) -> None:
        self.logger.warning("清除已保存的浏览器登录态", extra=extra(magazine_id, phase))
        try:
            page.context.clear_cookies()
        except Exception as exc:
            self.logger.warning("清除 cookies 失败: %s", exc, extra=extra(magazine_id, phase))
        try:
            page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")
        except Exception:
            pass
        try:
            self.config.browser.storage_state_path.unlink(missing_ok=True)
        except Exception as exc:
            self.logger.warning("删除 storage_state 失败: %s", exc, extra=extra(magazine_id, phase))

    def _result_title(self, item) -> str:
        title = item.locator(RESULT_TITLE_SELECTOR).first
        if title.count():
            return _clean_result_title(_compact_text(title.inner_text()))
        return _clean_result_title(_compact_text(item.inner_text()))

    def _wait_for_result_items(self, result_items) -> bool:
        try:
            result_items.first.wait_for(timeout=self.config.browser.action_timeout_ms)
            return True
        except Exception:
            return False

    def _with_retry(
        self,
        func: Callable[[], T],
        attempts: int,
        phase: str,
        retry_exception_type,
        magazine_id: str = "-",
    ) -> T:
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return func()
            except retry_exception_type as exc:
                last_error = exc
                self.logger.warning(
                    "第 %s/%s 次尝试失败: %s",
                    attempt,
                    attempts,
                    exc,
                    extra=extra(magazine_id, phase),
                )
                if attempt < attempts:
                    time.sleep(self.config.retry.backoff_seconds * attempt)
        assert last_error is not None
        raise last_error

    def _screenshot(self, page, magazine_id: str, phase: str) -> Path | None:
        try:
            path = self.config.logging.screenshot_dir / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{magazine_id}-{phase}.png"
            page.screenshot(path=str(path), full_page=True)
            self.logger.info("已保存截图: %s", path, extra=extra(magazine_id, "screenshot"))
            return path
        except Exception as exc:
            self.logger.warning("截图失败: %s", exc, extra=extra(magazine_id, "screenshot"))
            return None


def _compact_text(value: str) -> str:
    return " ".join(value.split())


def _clean_result_title(value: str) -> str:
    for marker in (" True PDF", " PDF"):
        if marker in value:
            return value.split(marker, 1)[0].strip()
    return value


def _build_search_url(base_url: str, search_term: str) -> str:
    encoded_once = quote(search_term, safe="")
    encoded_twice = quote(encoded_once, safe="")
    return urljoin(base_url.rstrip("/") + "/", f"search/{encoded_twice}")


def _is_navigation_aborted(exc: Exception) -> bool:
    return "net::ERR_ABORTED" in str(exc)


def _is_login_url(url: str, login_path: str) -> bool:
    return f"/{login_path.strip('/')}" in url
