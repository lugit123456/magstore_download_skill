---
name: magstore-downloader
description: 使用 Playwright 自动下载 MagStore 杂志。用于配置、运行、调试或维护 MagStore Auto Downloader，包括 MagStore 登录、搜索路由处理、最新期刊匹配、重复下载保护、本地 YAML/JSON 状态、下载目录和 launchd 定时任务。
---

# MagStore Downloader

使用本 skill 帮助用户操作或维护本仓库中的 MagStore Auto Downloader。

## 常用命令

本地安装：

```bash
python3 -m pip install -e .
python3 -m playwright install chromium
```

运行所有到期杂志：

```bash
python3 -m magstore_downloader --config ./config.yaml
```

强制检查所有启用的杂志：

```bash
python3 -m magstore_downloader --config ./config.yaml --force
```

只运行一本杂志：

```bash
python3 -m magstore_downloader --config ./config.yaml --magazine wsj --force
```

打开浏览器进行可视化调试：

```bash
python3 -m magstore_downloader --config ./config.yaml --headed --dry-run
```

## 配置规则

账号密码放在 `.env` 中：

```dotenv
MAGSTORE_USERNAME=your_username
MAGSTORE_PASSWORD=your_password
MAGSTORE_HEADLESS=true
```

所有杂志都配置在 `magazines` 下。注意 `schedule.type` 必须缩进到 `schedule` 下面：

```yaml
magazines:
  - id: "wsj"
    enabled: true
    magazine_name: "The Wall Street Journal"
    search_term: "Wall Street Journal"
    match_mode: "prefix"
    schedule:
      type: "daily"
    download_subdir: "the-wall-street-journal"

  - id: "economist"
    enabled: true
    magazine_name: "The Economist"
    search_term: "The Economist"
    match_mode: "prefix"
    schedule:
      type: "weekly"
      weekdays: [6]
    download_subdir: "economist"
```

`weekdays` 使用 ISO 星期编号：`1` 表示周一，`7` 表示周日。对于周五晚上更新的周刊，优先配置 `weekdays: [6]`，让程序周六检查。

通过 `download.base_dir` 设置下载根目录；每本杂志会保存到自己的 `download_subdir` 子目录。

## 运行注意事项

- 下载器使用 `/search/<double-encoded-search-term>` 搜索路由，不依赖搜索输入框事件。
- 只有进入 issue 详情页并完成重复检查后，才会点击下载按钮。
- `--force` 只忽略检查频率，不会绕过重复下载保护。
- `--redownload` 明确允许重新下载当前匹配 issue。
- `--dry-run` 不会点击下载按钮，也不会更新 `state.json`。
- 运行时文件应保持忽略：`.env`、`state.json`、`state/`、`logs/`、`artifacts/`、`downloads/`、`.venv/`。

## 调试检查清单

如果某本杂志没有被处理：

1. 确认命令中没有指定其他 `--magazine`。
2. 检查 `schedule` 下的 YAML 缩进是否正确。
3. 检查 `state.json` 中的 `next_check_at`；手动检查时使用 `--force`。
4. 使用 `--headed --dry-run` 运行，查看候选结果日志。
5. 如果站点标题和配置不同，调整 `magazine_name`、`search_term` 或 `match_mode`。

