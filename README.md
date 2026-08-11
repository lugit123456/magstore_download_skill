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
FEISHU_WEBHOOK_URL=your_feishu_bot_webhook
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

一天内多轮抓取时，显式指定轮次：

```bash
# 23:00：开始新一轮
python3 -m magstore_downloader --config ./config.yaml --attempt first

# 02:00：继续重试
python3 -m magstore_downloader --config ./config.yaml --attempt retry

# 09:00：最后检查，并在仍未更新时发送飞书通知
python3 -m magstore_downloader --config ./config.yaml --attempt final
```

`first`、`retry` 和 `final` 会自动忽略 `next_check_at`，但不会绕过下载去重。最后一轮由 `final` 参数明确标识，不依赖实际执行时间。

## 定时运行

`launchd/` 提供三个模板：

- `com.magstore.downloader.plist.template`：23:00，`first`
- `com.magstore.downloader.retry.plist.template`：02:00，`retry`
- `com.magstore.downloader.final.plist.template`：09:00，`final`

需要调整最后检查时间时，只修改 final 模板的 `Hour` 和 `Minute`，保留 `--attempt final`。

## 状态与安全

- 下载文件保存到 `download.base_dir` 加每本杂志的 `download_subdir`。
- `state.json` 会记录已下载 issue ID，用于避免重复下载。
- `state.json` 还会记录当前重试周期，避免前面轮次已经下载成功后在最终轮误报警，并防止同一周期重复发送通知。
- `--force` 只忽略检查频率，仍然保留重复下载保护。
- `--redownload` 会明确允许重新下载当前匹配 issue。
- `.env`、`state.json`、`logs/`、`artifacts/`、`downloads/`、`.venv/` 已加入 `.gitignore`，不应提交到 GitHub。
