# Rust Zulip 中文日报

把 [rust-lang Zulip](https://rust-lang.zulipchat.com/) 社区每天的最新讨论**自动翻译成中文并生成 AI 总结**，
以双语网页形式展示：左侧频道 + 话题导航（英文/中文标题），右侧查看话题完整对话（中文翻译为主、英文原文保留）。

覆盖频道：`general`、`t-compiler`、`t-libs`、`t-opsem`，每频道最新 **20** 个话题（可配置）。

## 功能

- 每日自动更新（GitHub Actions 定时 06:00 UTC = 北京时间 14:00），也可在 Actions 页手动点 “Run workflow” 立即更新
- 左侧导航：频道分组 + 话题列表（英文标题 + 中文标题 + 消息数 + 最后活跃时间），支持中英文搜索
- 右侧对话：每条消息中英文对照，可一键切换「双语 / 中文 / English」
- 帖子总结：将话题内全部英文聊天原文发送给 AI，生成主要内容、结论及待解决问题的中文摘要
- 翻译缓存：已翻译的消息不会重复翻译，增量更新极快
- OpenAI 兼容接口：可使用 OpenAI 官方 API 或支持 OpenAI 协议的第三方服务

## 目录结构

```
├── .github/workflows/daily.yml   # 每日定时 + 手动触发的更新与部署
├── scripts/
│   ├── pipeline.py               # 主管线：拉取 → 翻译 → 生成站点数据
│   ├── zulip_client.py           # Zulip API 客户端
│   ├── translate.py              # OpenAI 兼容翻译 + 缓存 + 代码/URL 保护
│   └── summarize.py              # 帖子 AI 总结 + 缓存
├── site/                         # 静态站点（部署到 GitHub Pages）
│   ├── index.html / app.js / style.css
│   └── data/*.json               # 每次运行生成的双语数据
├── data/translation_cache.json   # 翻译缓存（需提交到仓库）
└── data/summary_cache.json       # 总结缓存（帖子变化时自动更新）
```

## 快速开始

### 1. 创建 Zulip bot（一次即可）

rust-lang Zulip 的 API 需要登录凭据（即使频道是公开的）：

1. 登录 https://rust-lang.zulipchat.com （没有账号可用 GitHub 账号注册）
2. 右上角齿轮 → **Personal settings** → **Bots**
3. 点 **Add a new bot**，类型选 Generic bot，创建后记录 **bot 邮箱**（形如 `xxx-bot@rust-lang.zulipchat.com`）和 **API Key**

### 2. 配置 GitHub Secrets

仓库 → **Settings → Secrets and variables → Actions**：

| 名称 | 必填 | 说明 |
|---|---|---|
| `ZULIP_EMAIL` | 是 | Zulip bot 邮箱 |
| `ZULIP_API_KEY` | 是 | Zulip bot API Key |
| `OPENAI_API_KEY` | 是 | OpenAI 官方或第三方兼容服务的 API Key |

可选 Variables（仓库 Settings → Variables）：

| 名称 | 默认 | 说明 |
|---|---|---|
| `TOPICS_PER_STREAM` | `20` | 每频道最新话题数 |
| `STREAMS` | `general,t-compiler,t-libs,t-opsem` | 自定义频道 |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` | 第三方服务请填写其兼容 API 根地址 |
| `OPENAI_MODEL` | 无 | 服务商提供的模型名称，必须配置 |
| `AI_CONCURRENCY` | `4` | 同时生成帖子总结的最大请求数；遇到限流可调低 |

### 3. 启用 GitHub Pages

仓库 → **Settings → Pages** → Source 选择 **GitHub Actions**。（部署脚本会自动处理后续步骤）

### 4. 手动跑一次

仓库 → **Actions** → 左侧 **daily-update** → 右上 **Run workflow** → 等待完成。
完成后访问 `https://<你的用户名>.github.io/<仓库名>/`。

## 本地运行

```bash
# 1. 安装依赖（仅标准库 + requests 可选，本脚本纯标准库即可）
python --version

# 2. 配置凭据（Windows PowerShell 示例）
$env:ZULIP_EMAIL="xxx-bot@rust-lang.zulipchat.com"
$env:ZULIP_API_KEY="你的APIKey"
$env:TRANSLATE_BACKEND="openai"
$env:OPENAI_API_KEY="你的 API Key"
$env:OPENAI_BASE_URL="https://api.openai.com/v1" # 第三方服务改为服务商地址
$env:OPENAI_MODEL="你的模型名称"
$env:AI_CONCURRENCY="4"

# 3. 运行管线（拉取 + 翻译 + 生成 site/data/）
python scripts/pipeline.py

# 4. 本地预览（浏览器打开 http://127.0.0.1:8000）
cd site && python -m http.server 8000
```

> 注意：直接用文件双击打开 `index.html` 时浏览器会拦截本地 `fetch`，请用上面的 http.server 方式预览。

## AI 服务配置

项目调用 OpenAI Chat Completions 兼容接口。使用官方 OpenAI 时，将 `OPENAI_BASE_URL` 设置为
`https://api.openai.com/v1`；使用第三方服务时，填写服务商提供的 API 根地址和模型名称。
翻译与总结使用同一个模型和 API Key。

代码块、行内代码、URL、邮箱在翻译前会被提取保护，不会被破坏。

## 常见问题

- **首次运行很久？** 首次要翻译并总结几十个话题，属正常；之后翻译和总结都会走缓存。
- **某条消息只有英文？** 说明该条翻译失败（后端限流/网络），已保留原文，下次运行会自动重试。
- **想改更新时间？** 编辑 `.github/workflows/daily.yml` 里的 `cron` 表达式（UTC 时区）。
- **翻译结果想人工校对？** 直接改 `site/data/*.json` 再 push 即可，下次运行会保留人工改过的内容（缓存以消息 id 为准）。

## 免责声明

本工具仅供个人学习交流使用；数据版权归 rust-lang 社区及原作者所有。翻译由机器生成，仅供参考。
