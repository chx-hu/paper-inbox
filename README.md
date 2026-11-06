# Paper Inbox

[中文](#中文) · [English](#english)

## 中文

一款 macOS 文献收件箱：每天收集论文，结合你的 Zotero 文库排序，阅读简洁摘要，并将收藏的论文交给 Codex 精读。

### 功能

- 来源：arXiv、bioRxiv 和可选期刊。默认精选最多 10 篇，可在设置中调整为 1–50 篇；Cell 和 Cell Systems 不参与检索。
- 显示标题、作者及有依据的单位对应、来源、日期、相关性和中文摘要。支持未读、已读及收藏；文字可直接选中复制。
- 设置中切换中文／English、选择期刊、分类、精读模型和推理强度。
- 收藏触发 Codex 精读，多篇任务可以并行。报告包含问题、动机、方法、结果、正文图解读及 take-home message；SI 按需阅读。
- 新精读的 Motivation 与 Take-home message 保存中英两版，随界面语言显示；普通论文摘要目前以中文为主。
- 精读完成后保存至 Zotero 的“AI 文献收藏”。**取消收藏会将对应文库条目移入 Zotero 回收站，不只是移出分类**；重新收藏恢复原条目。不会清空回收站，阅读报告保留。
- 登录电脑后自动启动，按日检查更新；电脑需要已登录且联网。

### 快速安装

目前提供 **macOS 13+ 源码安装**，尚无签名、公证的 DMG。需要 Git、Xcode Command Line Tools、Homebrew、Zotero，以及可用的 Codex 账户。

1. 安装 [Zotero](https://www.zotero.org/download/) 和 [Homebrew](https://brew.sh/)。在 Zotero 个人文库中准备至少一篇带摘要的论文，创建“AI 文献收藏”分类。
2. 在终端准备环境：

```sh
xcode-select --install
brew install uv poppler node
npm install -g @openai/codex
codex login
```

3. 下载本仓库源码 ZIP 并解压，进入该文件夹，运行：

```sh
sh setup.sh
sh doctor.sh --offline
open "Paper Inbox.app"
```

向导会下载固定版本的检索组件、安装 Python 3.11 环境，询问 Zotero 文库位置、阅读材料目录、每日篇数和语言，并构建应用。默认文库是 `~/Zotero/zotero.sqlite`，阅读目录是 `~/Documents/Paper Inbox Reading`。请保留源码文件夹，应用运行时仍会使用其中的文件。

4. 可选：登录电脑后自动启动，以及授权 Zotero 同步：

```sh
sh install-login.sh
sh authorize-zotero.sh
```

授权时保持 Zotero 打开，在其窗口选择“始终允许”。[完整中文入门指南](docs/QUICKSTART.zh-CN.md) 包含权限与故障排查。

Codex 使用你自己的账户和可用额度，不提供免费或无限模型调用；模型是否可用取决于账户权限。建议安装 Codex 桌面应用以打开精读任务。应用不依赖 GitHub Actions，不发送邮件。

### 使用与限制

在“设置”（`⌘,`）选择来源和每天篇数，保存后在下次更新生效。更新源码后运行 `sh build.sh` 重新构建。文献来源可能延迟或暂时不可用，题录不保证包含摘要或可获取全文；推荐排序需要本机 Zotero 摘要作为兴趣参考。界面支持双语，但不会自动把已有单语报告补译。

### 目录结构

- `src/`：Python 后端和 SwiftUI 界面源码。
- `tests/`：自动化测试。
- `scripts/`：安装配置、检查和发布辅助工具。
- `docs/`、`skills/`：使用说明和论文阅读技能。
- `cache/`：本机运行数据，不提交。

### 开发与隐私

```sh
sh test.sh
python3 scripts/make_release.py
```

本机配置、授权凭据、缓存和阅读材料不应提交：`.gitignore` 排除 `sources.json`、`config.json`、`.env`、`cache/`、`reports/`、`vendor/` 和应用构建产物。分享时使用发布脚本生成的源码包，不直接分享使用后的整个文件夹。

目前已验证本机构建和自动化测试；尚未验证全新 Mac 的完整安装。欢迎通过 Issues 报告问题，附 macOS 版本、复现步骤和脱敏错误信息。

## English

A macOS inbox for research papers. Discover papers daily, rank them against your Zotero library, read concise summaries, and send favorites to Codex for a closer reading.

### Features

- Retrieve papers from arXiv, bioRxiv, and selected journals. The default daily limit is 10, configurable from 1 to 50. Cell and Cell Systems are excluded.
- View titles, authors, supported author–affiliation links, sources, dates, relevance scores, and Chinese summaries. Track unread, read, and favorite papers; select text to copy it.
- Switch the interface between Chinese and English. Configure sources, categories, journals, reading models, and reasoning effort in Settings.
- Favoriting starts a Codex reading task; multiple tasks can run concurrently. Reports cover the problem, motivation, methods, results, main figures, and take-home message. Supplementary material is consulted when needed.
- New reading tasks return Motivation and Take-home message in both Chinese and English, displayed in the selected interface language. Regular paper summaries remain primarily Chinese.
- Completed readings save the paper to Zotero’s “AI 文献收藏” collection. **Unfavoriting moves the corresponding library item to Zotero Trash, rather than merely removing collection membership.** Refavoriting restores the same item. Trash is never emptied, and reading reports are retained.
- Optional login startup enables daily update checks while the computer is logged in and online.

### Quick start

This is a **source installation for macOS 13+**, not a signed or notarized DMG. You need Git, Xcode Command Line Tools, Homebrew, Zotero, and an eligible Codex account.

1. Install [Zotero](https://www.zotero.org/download/) and [Homebrew](https://brew.sh/). Add at least one paper with an abstract to your personal Zotero library, and create a collection named **AI 文献收藏**.
2. Prepare the environment in Terminal:

```sh
xcode-select --install
brew install uv poppler node
npm install -g @openai/codex
codex login
```

3. Download and extract this repository’s source ZIP. Open Terminal in that folder and run:

```sh
sh setup.sh
sh doctor.sh --offline
open "Paper Inbox.app"
```

The wizard downloads a pinned retrieval dependency, installs a Python 3.11 environment, asks for your library and reading directory, daily limit, and language, and builds the app. Defaults are `~/Zotero/zotero.sqlite` and `~/Documents/Paper Inbox Reading`. Keep the source folder in place: the app uses its runtime files.

4. Optionally enable login startup and authorize Zotero synchronization:

```sh
sh install-login.sh
sh authorize-zotero.sh
```

Keep Zotero open and choose **Always Allow** in its authorization dialog. If macOS requests access to the selected folders, allow the app or terminal you are using. Run `sh doctor.sh --offline` to diagnose local configuration; it does not test remote paper services.

Codex uses your own account and available usage allowance; access to a model depends on your account. Installing the Codex desktop app is recommended for opening reading tasks. The app does not depend on GitHub Actions and sends no email.

### Usage and limitations

Open Settings with `⌘,`. Source and daily-limit changes take effect on the next update. After changing source code, run `sh build.sh` to rebuild. Sources may be delayed or unavailable; metadata does not guarantee an abstract or accessible full text. Relevance ranking currently requires abstracts in a local Zotero library. Existing monolingual reports are not automatically translated.

### Repository layout

- `src/`: Python backend and SwiftUI application source.
- `tests/`: automated tests.
- `scripts/`: configuration, diagnostics, and release helpers.
- `docs/` and `skills/`: documentation and paper-reading skill.
- `cache/`: local runtime data, excluded from Git.

### Development and privacy

```sh
sh test.sh
python3 scripts/make_release.py
```

Do not commit local configuration, credentials, caches, or reading materials. The included `.gitignore` excludes `sources.json`, `config.json`, `.env`, `cache/`, `reports/`, `vendor/`, and app bundles. Share the source archive produced by the release script, not your entire working installation.

Local builds and automated tests have been checked; installation on a completely fresh Mac has not yet been verified. For bug reports, include your macOS version, reproduction steps, and redacted error messages.

## License / 许可证

Distributed under **AGPLv3**; see [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md). Retrieval and ranking depend on a pinned version of [chx-hu/zotero-arxiv-daily](https://github.com/chx-hu/zotero-arxiv-daily), including work from TideDra. Preserve the included license and attribution notices when redistributing.

本项目按 **AGPLv3** 分发。检索与排序依赖固定版本的 zotero-arxiv-daily，包含 TideDra 的工作；再分发时请保留许可证和版权说明。
