<div align="center">

# zotero-scholium（注疏）

**将阅读结果写回 Zotero，生成原生、可编辑的注释。**

[![CI](https://github.com/weilr/zotero-scholium/actions/workflows/ci.yml/badge.svg)](https://github.com/weilr/zotero-scholium/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Zotero 7–10](https://img.shields.io/badge/zotero-7%20%7C%208%20%7C%209%20%7C%2010-cc2936.svg)](https://www.zotero.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

[English](README.md) | [中文](README.zh-CN.md)

</div>

## 目录

- [概述](#概述)
- [安装](#安装)
- [用法](#用法)
- [技能内容](#技能内容)
- [工作原理](#工作原理)
- [功能](#功能)
- [命令行使用](#命令行使用)
  - [配置](#配置) · [写入通道](#写入通道)
- [学习用户的标注画像](#学习用户的标注画像)
- [安全边界](#安全边界)
- [故障排查](#故障排查)
- [开发](#开发)
- [参与贡献](#参与贡献)
- [许可证](#许可证)

## 概述

zotero-scholium 将论文的阅读结果（由研究者撰写或由大语言模型生成）以 Zotero 一等对象的形式保存：带评论的高亮与下划线注释、置于页边空白处的文本注释，以及条目下的子笔记。这些结果在 Zotero 阅读器中与手工添加的注释无异，可以直接编辑，并作为普通文库数据同步。

工具不对 PDF 文件进行任何修改。在 Zotero 10 及以上版本中，工具通过 Zotero 10.0 新增的官方本地 API 写入接口工作，无需安装插件；Zotero 7 至 9 通过随附的小型插件支持。

技能遵循 [Agent Skills 规范](https://agentskills.io/)，可用于 Claude Code、Codex、Cursor 以及其他读取 `SKILL.md` 的代理。

项目处于 alpha 阶段。官方 API 路径已在 Windows 上的 Zotero 10.0.1 中测试；Zotero 7–9 的插件路径已实现，但测试较少。

## 安装

```bash
npx skills add weilr/zotero-scholium
```

这一命令通过 [skills 命令行工具](https://github.com/vercel-labs/skills) 为 Claude Code、Codex、Cursor 及其支持的其他代理安装技能。可以交互式选择代理，也可以加上 `-g -y` 非交互地安装到用户目录。

### Claude Code 插件

Claude Code 也可以把技能作为插件安装，由 `/plugin` 负责更新：

```
/plugin marketplace add weilr/zotero-scholium
/plugin install zotero-scholium@zotero-scholium
```

### 手动安装

将[技能目录](skills/zotero-scholium/)（`skills/zotero-scholium/`）复制到代理的技能目录：Claude Code 为 `~/.claude/skills/`，Codex 为 `~/.codex/skills/`，其他代理为 `~/.agents/skills/`。该目录自成一体，不依赖仓库的其他部分。

### 环境要求

- Python 3.9 及以上，并安装 [PyMuPDF](https://pymupdf.readthedocs.io/)：`pip install pymupdf`
- Zotero 7 及以上，处于运行状态；本地服务器默认已启用
- 仅 Zotero 7–9 需要：随附的 [`scholium-bridge` 插件](plugin/README.md)。Zotero 10 无需插件。

### 更新

```bash
npx skills update zotero-scholium
```

Claude Code 插件方式则使用 `/plugin update zotero-scholium@zotero-scholium`。

## 用法

只要请求代理标注、高亮、翻译 Zotero 文库中的某篇论文或为其做笔记，技能就会自动启用。Zotero 需处于运行状态。

**示例：**

```
给我 Zotero 里的《Attention Is All You Need》做标注
```

```
把《Attention Is All You Need》的核心论点和主要结果高亮并翻译，加上页边批注
```

```
为《Attention Is All You Need》写一篇阅读笔记
```

代理会通过本地 API 定位条目、选择句子、撰写评论与页边批注、用内置脚本写入，并报告结果。Zotero 10 首次写入会弹出授权对话框，选择"始终允许"。写入后关闭并重新打开该 PDF 即可看到注释。中文请求按随附的中文写作规范执行。

## 技能内容

| 路径 | 内容 |
|---|---|
| `skills/zotero-scholium/SKILL.md` | 工作流程：定位条目、选择句子、撰写评论与页边批注、调用脚本、核对结果 |
| `skills/zotero-scholium/references/style-zh.md` | 中文评论、页边批注与阅读笔记的写作规范 |
| `skills/zotero-scholium/references/zotero-annotations.md` | Zotero 注释的数据模型 |
| `skills/zotero-scholium/scripts/scholium.py` | 工具本体，与 `src/zotero_scholium/cli.py` 完全一致 |
| `skills/zotero-scholium/examples/` | 配置文件与阅读笔记模板 |
| `skills/zotero-scholium/agents/openai.yaml` | Codex 中的显示名称与触发策略 |

## 工作原理

1. 以只读方式用 PyMuPDF 打开 PDF，对每一页建立词级索引。
2. 将每条高亮短语与规范化后的词序列匹配，按文本行生成 PDF 用户空间中的矩形，并计算 Zotero 的排序索引。
3. 根据全文档词坐标的分布估计正文栏的边界；每条总结锚定到所在段落的首行，布局在相邻的页边，避开已有注释、图表、相邻批注、页眉和页脚。
4. 先移除上一次运行创建的工具自身注释，再通过所选通道写入新的注释对象。

注释条目的实测 JSON 结构、本地 API 的授权流程以及通道顺序的取舍见 [设计说明](docs/design.md)。

## 功能

- **原生注释。** 高亮、下划线与页边文字均为 Zotero 注释条目：可编辑、可检索、可同步。不改动 PDF 文件。
- **页边批注自动布局。** 批注置于段落所在一侧的页边，自动避开图表、已有注释、相邻批注、页眉与页脚。
- **可定制的位置与样式。** 首页顶部的论文总结、页底的一句评语、固定放在某一侧的批注、便签，或单条批注的颜色与字号；画像会学习这些习惯。
- **稳健的原文匹配。** 词级匹配，忽略空白、连字符与连字。
- **译文一致性检查。** 评论中出现而高亮原文中没有的术语或数字，在写入前以警告形式报告。
- **画像学习。** `scholium profile --from-library` 从文库中已有的注释归纳用户自己的标注习惯；用户的明确规则始终优先。
- **可安全重复运行。** 每个对象都带有所有权标签；重新运行只替换工具自身的注释，绝不删除笔记。
- **三条写入通道。** 官方本地 API（Zotero 10+）、随附插件（Zotero 7–9）或生成脚本，按可用性自动选择。

## 命令行使用

工具也可以直接运行，供脚本或其他代理框架调用：

```bash
pip install pymupdf
pip install .                            # 提供 `scholium` 命令
```

1. **通过本地 API 定位条目及其 PDF 附件**（Zotero 需处于运行状态）：

   ```
   http://localhost:23119/api/users/0/items?q=attention+is+all+you+need
   http://localhost:23119/api/users/0/items/<ITEM_KEY>/children
   ```

2. **编写配置文件。** 完整模板见[配置模板](skills/zotero-scholium/examples/config.template.json)。

   ```json
   {
     "pdf": "/path/to/Zotero/storage/<ATTACHMENT_KEY>/paper.pdf",
     "item_key": "<ITEM_KEY>",
     "attachment_key": "<ATTACHMENT_KEY>",
     "out_dir": "out",
     "note_html": "reading_note.html",
     "note_title_prefix": "Attention Is All You Need",
     "highlights": [
       {"page": 1, "core": true, "text": "We propose a new simple network architecture, the Transformer, based solely on attention mechanisms", "comment": "我们提出一种新的简单网络架构 Transformer，完全基于 attention 机制。"}
     ],
     "summaries": [
       {"page": 1, "anchor": "dispensing with recurrence and convolutions entirely", "text": "用 attention 取代循环结构，整个模型只有 attention 和前馈层。"}
     ]
   }
   ```

3. **生成、检查、写入。**

   ```bash
   scholium --config config.json            # 匹配原文，渲染预览，报告未匹配的句子
   scholium --config config.json --apply    # 写入 Zotero（Zotero 10 首次运行需确认授权对话框）
   scholium --config config.json --list     # 读取当前库中已有的注释与笔记
   ```

   第一条命令生成 `annotations.json`、备用的 `create_annotations.js` 以及所配置页面的 `preview_p<N>.png`，并列出无法定位的短语。

[本地 API 调用示例](examples/direct_api_example.py)（`examples/direct_api_example.py`）以约三十行代码演示了 Zotero 10 本地 API 的基本调用，可用于其他应用。

### 配置

| 键 | 必填 | 说明 |
|---|---|---|
| `pdf` | 是 | PDF 附件路径 |
| `item_key`、`attachment_key` | 是 | 父条目与附件的 Zotero key |
| `out_dir` | 是 | 生成文件的输出目录 |
| `highlights[]` | | `page`（从 1 起）、`text`（逐字原文）、`comment`，以及 `level`、`color`、旧式布尔值 `core` 三者之一；可选 `type: "underline"` |
| `summaries[]` | | `page`、`anchor`（定位段落的唯一短语）、`text`（不含硬换行）；可选 `place`（`"top"` 或 `"bottom"`：横跨正文栏、置于该页顶部或底部的文本框，无需 anchor）、`side`（`"left"`、`"right"`）、`color`、`font_size`、`kind: "note"`（便签） |
| `levels` | | 命名颜色，例如 `{"claim": "#ff6666", "term": "#ffd400"}` |
| `note_html`、`note_title_prefix` | | 子笔记的 HTML 文件；前缀用于识别已存在的同名笔记 |
| `core_color`、`other_color`、`text_color` | | 默认 `#ff6666`、`#ffd400`、`#1a73e8` |
| `font_size` | | 页边文字字号，单位 pt（默认 8） |
| `margin_side` | | `auto`（默认：段落所在一侧，或较宽的页边）、`left` 或 `right` |
| `summary_kind` | | `text`（默认：可见的页边文字）或 `note`（便签） |
| `preview_pages` | | 渲染为 PNG 预览的页码（默认 `[1]`） |
| `data_dir` | | Zotero 数据目录（默认从 PDF 路径或 Zotero 首选项推断）；存放画像与 bridge 令牌 |
| `cleanup` | | `true`（默认）：写入前删除本工具此前在该附件上创建的注释；`false`：保留全部已有注释，只新增 |
| `cleanup_external` | | 仅 bridge 通道：同时清理从 PDF 文件导入的注释（默认 `false`） |
| `note_replace` | | 创建新笔记前删除同前缀的已有子笔记（默认 `false`；破坏性选项） |

### 写入通道

| `--backend` | Zotero 版本 | 机制 |
|---|---|---|
| `api`（10+ 默认） | 10.0 及以上 | 官方本地 API 写入支持。`POST /api/local/authorize` 弹出一次确认对话框，所得 key 按 Zotero 实例保存在用户配置目录。 |
| `bridge` | 7–9 | [随附插件 `scholium-bridge`](plugin/README.md) 在本机提供仅接受数据的端点，由 Zotero 数据目录中的令牌文件保护。通过 工具 → 插件 → 从文件安装插件 安装。 |
| `js` | 任意 | 生成 `create_annotations.js`，在 工具 → 开发者 → 运行 JavaScript 中手动执行。 |

`--backend auto` 按上述顺序选择第一个可用的通道。

## 学习用户的标注画像

不同用户的标注习惯差异很大：颜色的含义、是否使用下划线、是否书写页边文字、是否添加评论。工具不预设风格，而是分析文库中已有的注释并加以描述。

```bash
scholium profile --from-library      # 只读；生成 profile.json 与 profile.md
```

`profile.md` 保存在 Zotero 数据目录（即存放 `zotero.sqlite` 与 `storage/` 的目录）下的 `zotero-scholium/` 中，画像与它所描述的文库放在一起；`scholium profile --path` 可打印实际位置。数据目录依次取自 `--data-dir`、`ZOTERO_DATA_DIR`、PDF 路径或 Zotero 自身的首选项。文件包含三个部分，优先级依次升高：

| 部分 | 内容 | 重新运行时 |
|---|---|---|
| 统计 | 颜色及其比例、注释类型、评论长度与风格、密度、笔记 | 重新生成 |
| `## Interpretation` | 各颜色的含义以及新注释应遵循的规则，由代理填写、用户修正 | 保留 |
| `## User's rules (always win)` | 用户的明确要求，按原话记录 | 保留 |

工具自身创建的注释不计入统计，因此画像始终描述用户本人的习惯。

## 安全边界

- PDF 以只读方式打开，不会被写入。
- 工具创建的所有注释与笔记均带有标签 `zotero-scholium`。重复运行时，仅删除带有该标签、或内容与本次生成完全相同的注释。
- 已有的子笔记不会被删除。若存在同名笔记，新笔记以"标题 (v2, YYYY-MM-DD)"形式的版本化标题创建。
- 从 PDF 文件导入的"外部"注释（显示为锁定状态）默认保留，除非启用 `cleanup_external`。
- 本地 API key 与插件令牌仅保存在本机，不纳入版本控制。

## 故障排查

**写入后看不到注释。**
关闭并重新打开 Zotero 阅读器中的该 PDF；已打开的阅读器标签页不会重新加载外部创建的注释。

**部分短语被报告为 `missed`。**
短语跨页、包含提取时呈现方式不同的符号，或小型大写字母的单词在提取文本中与相邻单词粘连。请改用同一页内较短的子串。

**Zotero 再次弹出授权对话框。**
本地 API key 与实例的 `Zotero-Server-ID` 绑定。重新安装 Zotero 或迁移数据目录会改变该 ID，需要重新申请 key。

**部分注释显示为锁定状态。**
这些是 Zotero 从 PDF 文件内嵌的注释导入的。本工具不会创建此类注释，默认也不会删除它们。

## 开发

```bash
pip install -e ".[dev]"
pytest                                      # 测试基于合成 PDF，不含任何第三方内容
python scripts/check_skill_script_sync.py   # 技能目录中包含 cli.py 的副本，两者必须保持一致
python scripts/check_skill_frontmatter.py   # SKILL.md 的 front matter 必须是严格合法的 YAML
```

插件由发布工作流打包；如需本地构建，将 `plugin/scholium-bridge/` 中的 `manifest.json` 与 `bootstrap.js` 置于 zip 压缩包根目录，命名为 `scholium-bridge.xpi`。

## 参与贡献

欢迎提交问题报告与合并请求。报告问题时请说明 Zotero 版本、操作系统与所用写入通道，并尽可能附上失败命令的输出及 `--list` 的结果。

1. Fork 仓库并新建分支。
2. 完成修改，并在 `tests/` 中补充或调整测试。
3. 运行 `pytest`、`python scripts/check_skill_script_sync.py` 与 `python scripts/check_skill_frontmatter.py`。
4. 提交 Pull Request，说明改动内容与测试所用的 Zotero 版本。

## 许可证

本项目以 [MIT 许可证](LICENSE) 发布。

## 致谢

- [Zotero](https://www.zotero.org/)：其本地 API 使无插件写入成为可能。
- [PyMuPDF](https://pymupdf.readthedocs.io/)：用于文本提取与页面几何分析。
