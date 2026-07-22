from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import ConfigError, ensure_runtime_dirs, load_config, load_credentials
from .logging_utils import extra, setup_logging
from .playwright_runner import MagStoreRunner
from .state import StateStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MagStore 自动下载工具")
    parser.add_argument("--config", default="./config.yaml", help="配置文件路径")
    parser.add_argument("--state", default="./state.json", help="状态文件路径")
    parser.add_argument("--magazine", help="只处理指定 magazine id")
    parser.add_argument("--force", action="store_true", help="忽略检查频率，但仍保留下载去重保护")
    parser.add_argument("--redownload", action="store_true", help="明确允许重复下载当前匹配 issue")
    parser.add_argument("--headed", action="store_true", help="显示浏览器窗口")
    parser.add_argument("--dry-run", action="store_true", help="执行登录、搜索和匹配，但不点击下载且不更新 state")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        ensure_runtime_dirs(config)
        logger, run_id = setup_logging(
            config.logging.level,
            config.logging.file,
            config.logging.max_bytes,
            config.logging.backup_count,
        )
        logger.info("启动任务 run_id=%s", run_id, extra=extra(phase="init"))
        credentials = load_credentials(config)
        state_path = _resolve_state_path(config.config_dir, args.state)
        state = StateStore(state_path)
        runner = MagStoreRunner(
            config=config,
            credentials=credentials,
            state=state,
            logger=logger,
            headed=args.headed,
            dry_run=args.dry_run,
            redownload=args.redownload,
        )
        summary = runner.run(selected_magazine=args.magazine, force=args.force)
        logger.info(
            "执行汇总 planned=%s downloaded=%s skipped=%s failed=%s",
            summary.planned,
            summary.downloaded,
            summary.skipped,
            summary.failed,
            extra=extra(phase="summary"),
        )
        return 1 if summary.failed else 0
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"执行失败: {exc}", file=sys.stderr)
        return 1


def _resolve_state_path(config_dir: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = config_dir / path
    return path.resolve()

