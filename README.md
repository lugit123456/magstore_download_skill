# MagStore Auto Downloader

这是一个基于 Python + Playwright 的 MagStore 自动下载工具，用于下载各杂志最新一期，并通过本地状态文件避免重复下载。

## 安装

```bash
python3 -m pip install -e .
python3 -m playwright install chromium
```

从示例文件创建 `.env`：

```bash
cp .env.example .env
```

然后填写账号配置：

```dotenv
MAGSTORE_USERNAME=your_username
MAGSTORE_PASSWORD=your_password
MAGSTORE_HEADLESS=true
```

## 配置

编辑 `config.yaml`。

设置下载根目录：

```yaml
download:
  base_dir: "/Users/you/Downloads/Magazines"
```

在 `magazines` 下配置多本杂志：

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

`weekdays` 使用 ISO 星期编号：`1` 表示周一，`7` 表示周日。对于周五晚上更新的杂志，建议配置为周六检查，即 `weekdays: [6]`。

## 运行

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

调试模式，不实际下载：

```bash
python3 -m magstore_downloader --config ./config.yaml --headed --dry-run
```

`--dry-run` 会完成登录、搜索、匹配和进入详情页，但不会点击下载按钮，也不会更新 `state.json`。

## 定时运行

可以使用 `launchd/com.magstore.downloader.plist.template` 作为 macOS `launchd` 模板。建议让系统每天启动一次程序；每本杂志是否真正检查，由它自己的 `schedule` 独立决定。

## 状态与安全

- 下载文件保存到 `download.base_dir` 加每本杂志的 `download_subdir`。
- `state.json` 会记录已下载 issue ID，用于避免重复下载。
- `--force` 只忽略检查频率，仍然保留重复下载保护。
- `--redownload` 会明确允许重新下载当前匹配 issue。
- `.env`、`state.json`、`logs/`、`artifacts/`、`downloads/`、`.venv/` 已加入 `.gitignore`，不应提交到 GitHub。

