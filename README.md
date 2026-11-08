# Rust Zulip 中文日报

用中文跟进 [rust-lang Zulip](https://rust-lang.zulipchat.com/) 的技术讨论。
网站提供中文话题摘要、逐条中英对照、收藏和阅读进度。

**当前采用按需更新：需要时让 Codex 在本机获取讨论、翻译和总结，然后提交快照；
GitHub Actions 仅构建和发布，不再每日自动抓取，也不调用付费 AI API。**

网站：[Rust Zulip 中文日报](https://yilin0518.github.io/rust-zulip-zh-daily/)

## 需要更新时

在 Codex 中打开本仓库，告诉它：

> 按 docs/UPDATING.md 更新日报并推送到远程。

完整步骤见 [按需更新说明](docs/UPDATING.md)。首次使用可以只更新指定频道和话题数。
本机更新过程不调用翻译或 AI API；由 Codex 本身完成语言工作，消耗当前订阅的使用额度。
Zulip 公开频道默认匿名读取；已有 bot 凭据时也可以使用认证读取。

## 阅读功能

- 中文标题和摘要优先的首页；频道筛选、中英文标题/摘要搜索，以及最近更新/消息数排序。
- 默认中文阅读，英文原文可逐条展开，也可切换双语或 English。
- 收藏、未读消息和继续阅读，阅读偏好保存在当前浏览器，不跨设备同步。
- 每话题与每条消息都有固定链接，支持 GitHub Pages 子路径、直接访问和刷新。
- 话题正文按需加载，每次先展示 60 条，再继续加载；支持跳到最新消息。
- 引用折叠、Rust 代码高亮、代码复制、字号调整、深浅主题和手机布局。

默认读取 `general`、`t-compiler`、`t-libs`、`t-opsem`，每频道最近活跃的 20 个话题。
长话题最多保留**最近 1000 条消息**，按时间正序展示。摘要仅覆盖实际获取的记录。
未读以消息 ID 判断，编辑原有消息不会重新标为未读。搜索不包含正文。
当前是滚动话题列表，不是按日期保存的历史日报。

## 本地开发

需要 Python 3.10+、Node.js 22。Python 脚本仅使用标准库。

```powershell
npm ci
python scripts/manual_update.py render
npm run dev
```

`render` 使用已提交的 `data/site_snapshot.json`，不访问网络。
没有真实快照时，可用 `python scripts/make_sample_data.py` 生成明确标注的界面示例。
不要直接双击 Vue 的 `site/index.html`，也不要用普通 HTTP 服务器运行前端源文件。

```powershell
npm test
python -m unittest discover -s tests
npm run build
npm run preview
```

生产产物在 `dist/`。Vite 使用相对资源路径，话题采用 hash 路由，无需服务器路由重写。

## 目录结构

```text
.github/workflows/daily.yml   # publish-site：推送后测试、构建和发布
docs/UPDATING.md              # 本机获取、人工/代理翻译、审校、推送流程
scripts/manual_update.py     # prepare / apply / finalize / render
scripts/zulip_client.py      # 认证和 web-public 只读客户端
scripts/site_data.py         # 轻量目录与话题正文导出
scripts/update_report.py     # 翻译与摘要完整性报告
site/src/                   # Vue 3 + TypeScript 阅读界面
site/data/                  # 生成数据，不提交
data/site_snapshot.json     # 提交到 Git 的可发布内容快照
data/translation_cache.json # 消息与标题翻译缓存
data/summary_cache.json     # 与原文 digest 对应的摘要缓存
work/update/                # 本机任务与未完成结果，不提交
tests/                      # Python 更新流程测试
```

## GitHub Pages

仓库 Settings → Pages → Source 选择 GitHub Actions。
`publish-site` 在 main 上推送内容快照或相关代码后运行，也可手动触发。
它不需要 Zulip、翻译或 OpenAI Secrets，不会自动修改和推送缓存。
没有完整的新结果时，`finalize` 不会替换快照；已经完成的分批翻译可以保存后继续处理。

首次改版使用的快照由 `import-published` 从原站迁移，保留原有机器译文及其不足，
并在快照的 `quality.migrated` 中记录来源。这不代表对既有翻译做了重新审校。

## 历史 API 管线

`scripts/pipeline.py`、`scripts/translate.py` 和 `scripts/summarize.py` 仍保留供单独使用，
但已退出默认发布流程。若自行运行，按 `.env.example` 设置环境变量，并自行承担服务费用。
脚本不会自动读取 `.env`。ChatGPT Plus 不能代替脚本所需的 API 凭据。

该旧管线已修复 UTF-8 分块、冷却重试、部分成功缓存和长话题读取问题。
可设置 `REQUIRE_COMPLETE_TRANSLATIONS=true`，在内容不完整时阻止成功退出；
`OPENAI_TRANSLATION_CHAR_BUDGET` 可限制每次运行请求的翻译原文字符数（0 表示不设限，
不包含摘要或服务内部重试），`UPDATE_REPORT_PATH` 可指定检查报告位置。

人工校对缓存时，应修改对应条目的 `zh` 并保留原始 `en` 和消息键。
修改生成的 `site/data/` 会被后续 render 覆盖。历史缓存可能含部分英文，不能仅凭缓存存在
认定其语言质量；有疑问时仍需对照原文审校。

## 说明

数据和发言版权归 rust-lang 社区及原作者所有；翻译和摘要仅供学习参考。
重要技术结论请核对原帖，尤其注意区分个人意见、提案和已达成的团队决定。
