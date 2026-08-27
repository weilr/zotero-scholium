<div align="center">

# zotero-scholium（注疏）

**将阅读结果写回 Zotero，生成原生、可编辑的注释。**

[![CI](https://github.com/weilr/zotero-scholium/actions/workflows/ci.yml/badge.svg)](https://github.com/weilr/zotero-scholium/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![Zotero 7–10](https://img.shields.io/badge/zotero-7%20%7C%208%20%7C%209%20%7C%2010-cc2936.svg)](https://www.zotero.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

[概述](#概述) ·
[安装](#安装) ·
[快速开始](#快速开始) ·
[配置](#配置) ·
[设计说明](docs/design.md) ·
[English README](README.md)

</div>

<!-- 截图占位：docs/images/reader.png（Zotero 阅读器中带译文评论的高亮与页边批注） -->

## 概述

zotero-scholium 将论文的阅读结果（由研究者撰写或由大语言模型生成）以 Zotero 一等对象的形式保存：带评论的高亮与下划线注释、置于页边空白处的文本注释，以及条目下的子笔记。这些结果在 Zotero 阅读器中与手工添加的注释无异，可以直接编辑，并作为普通文库数据同步。

工具不对 PDF 文件进行任何修改。在 Zotero 10 及以上版本中，工具通过 Zotero 10.0 新增的官方本地 API 写入接口工作，无需安装插件；Zotero 7 至 9 通过随附的小型插件支持。

项目处于 alpha 阶段。官方 API 路径已在 Windows 上的 Zotero 10.0.1 中测试；Zotero 7–9 的插件路径已实现，但测试较少。

## 功能

- **原生注释。** 高亮、下划线与页边文字均作为 Zotero 注释条目创建，而不是写入 PDF 的标记；可编辑、可检索、可同步。
- **页边批注自动布局。** 简短总结以文本注释的形式显示在相应段落旁。工具从页面测量栏的几何位置，在双栏版式中将批注放在段落所在的一侧，并自动处理与相邻批注和页脚的重叠。页面上已有的注释（包括用户自己的页边文字）会在布局前从 Zotero 读取，作为已占用区域避开。
- **稳健的原文匹配。** 在词级匹配短语，忽略空白、连字符与连字，因此可以直接使用从 PDF 提取的文本。
- **译文一致性检查。** 评论中出现而高亮原文中没有的术语或数字，以及与高亮范围明显不成比例的评论，在写入前以警告形式报告。
- **画像学习。** `scholium profile --from-library` 分析文库中已有的注释（颜色、类型、评论长度与风格、密度），生成供代理遵循的画像，取代内置风格；用户的明确规则始终优先。
- **可安全重复运行。** 工具创建的每个对象都带有所有权标签。重新运行时只替换工具自身的注释，用户的注释不受影响，已有笔记不会被删除。
- **三条写入通道。** 官方本地 API（Zotero 10+）、随附插件（Zotero 7–9）、生成脚本手动执行，按可用性自动选择。
- **代理集成。** 随附的 Claude Code 技能可由一句请求驱动完整流程；其他代理框架可以同样方式使用命令行接口。

## 环境要求

- Python 3.9 及以上
- [PyMuPDF](https://pymupdf.readthedocs.io/)（`pip install pymupdf`）
- Zotero 7 及以上，且本地服务器已启用（默认启用）
- 仅 Zotero 7–9 需要：随附的 `scholium-bridge` 插件

## 安装

```bash
pip install pymupdf
pip install .
```

安装后提供 `scholium` 命令。单文件模块 `src/zotero_scholium/cli.py` 也可以不经安装直接运行。

## 快速开始

1. **通过本地 API 定位条目及其 PDF 附件**（Zotero 需处于运行状态）：

   ```
   http://localhost:23119/api/users/0/items?q=<标题关键词>
   http://localhost:23119/api/users/0/items/<ITEM_KEY>/children
   ```

2. **编写配置文件。** 完整模板见
   [`skill/zotero-scholium/examples/config.template.json`](skill/zotero-scholium/examples/config.template.json)。

   ```json
   {
     "pdf": "/path/to/Zotero/storage/<ATTACHMENT_KEY>/paper.pdf",
     "item_key": "<ITEM_KEY>",
     "attachment_key": "<ATTACHMENT_KEY>",
     "out_dir": "out",
     "note_html": "reading_note.html",
     "note_title_prefix": "论文标题",
     "highlights": [
       {"page": 1, "core": true, "text": "PDF 中的原句（逐字）", "comment": "译文或评论"}
     ],
     "summaries": [
       {"page": 1, "anchor": "该段落中独有的一段原文", "text": "一句话页边批注"}
     ]
   }
   ```

3. **生成、检查、写入。**

   ```bash
   scholium --config config.json            # 匹配原文，渲染预览，报告未匹配的句子
   scholium --config config.json --apply    # 写入 Zotero（Zotero 10 首次运行需确认授权对话框）
   scholium --config config.json --list     # 读取当前库中已有的注释与笔记
   ```

   第一条命令生成 `annotations.json`、备用的 `create_annotations.js` 以及所配置页面的 `preview_p<N>.png`，并列出无法定位的短语。写入后关闭并重新打开该 PDF 即可看到新注释。

## 学习用户的标注画像

不同用户的标注习惯差异很大：颜色的含义、是否使用下划线、是否书写页边文字、是否添加评论。工具不预设风格，而是分析文库中已有的注释并加以描述。

```bash
scholium profile --from-library      # 只读；生成 profile.json 与 profile.md
```

`profile.md` 在 Windows 上位于 `%APPDATA%/zotero-scholium/`，其他系统位于 `~/.config/zotero-scholium/`。文件包含三个部分，优先级依次升高：

| 部分 | 内容 | 重新运行时 |
|---|---|---|
| 统计 | 颜色及其比例、注释类型、评论长度与风格、密度、笔记 | 重新生成 |
| `## Interpretation` | 各颜色的含义以及新注释应遵循的规则，由代理填写、用户修正 | 保留 |
| `## User's rules (always win)` | 用户的明确要求，按原话记录 | 保留 |

工具自身创建的注释不计入统计，因此画像始终描述用户本人的习惯。

## 写入通道

| `--backend` | Zotero 版本 | 机制 |
|---|---|---|
| `api`（10+ 默认） | 10.0 及以上 | 官方本地 API 写入支持。`POST /api/local/authorize` 弹出一次确认对话框，所得 key 按 Zotero 实例保存在用户配置目录。 |
| `bridge` | 7–9 | 随附插件 [`plugin/scholium-bridge`](plugin/README.md) 在本机提供仅接受数据的端点，由 Zotero 数据目录中的令牌文件保护。通过 工具 → 插件 → Install Plugin From File 安装。 |
| `js` | 任意 | 生成 `create_annotations.js`，在 工具 → 开发者 → 运行 JavaScript 中手动执行。 |

`--backend auto` 按上述顺序选择第一个可用的通道。

## 配置

| 键 | 必填 | 说明 |
|---|---|---|
| `pdf` | 是 | PDF 附件路径 |
| `item_key`、`attachment_key` | 是 | 父条目与附件的 Zotero key |
| `out_dir` | 是 | 生成文件的输出目录 |
| `highlights[]` | | `page`（从 1 起）、`text`（逐字原文）、`comment`，以及 `level`、`color`、旧式布尔值 `core` 三者之一；可选 `type: "underline"` |
| `summaries[]` | | `page`、`anchor`（定位段落的唯一短语）、`text`（不含硬换行） |
| `levels` | | 命名颜色，例如 `{"claim": "#ff6666", "term": "#ffd400"}` |
| `note_html`、`note_title_prefix` | | 子笔记的 HTML 文件；前缀用于识别已存在的同名笔记 |
| `author` | | 阅读器中显示的注释作者名（默认为空） |
| `core_color`、`other_color`、`text_color` | | 默认 `#ff6666`、`#ffd400`、`#1a73e8` |
| `font_size` | | 页边文字字号，单位 pt（默认 8） |
| `preview_pages` | | 渲染为 PNG 预览的页码（默认 `[1]`） |
| `data_dir` | | Zotero 数据目录（bridge 通道；默认从 PDF 路径推断） |
| `cleanup_external` | | 仅 bridge 通道：同时清理从 PDF 文件导入的注释（默认 `false`） |
| `note_replace` | | 创建新笔记前删除同前缀的已有子笔记（默认 `false`；破坏性选项） |

## 安全边界

- PDF 以只读方式打开，不会被写入。
- 工具创建的所有注释与笔记均带有标签 `zotero-scholium`。重复运行时，仅删除带有该标签、署名与配置一致、或内容与本次生成完全相同的注释。
- 已有的子笔记不会被删除。若存在同名笔记，新笔记以"标题 (v2, YYYY-MM-DD)"形式的版本化标题创建。
- 从 PDF 文件导入的"外部"注释（显示为锁定状态）默认保留，除非启用 `cleanup_external`。
- 本地 API key 与插件令牌仅保存在本机，且已列入 `.gitignore`。

## 与代理配合使用

[`skill/zotero-scholium/`](skill/zotero-scholium/) 是一个 [Claude Code](https://claude.com/claude-code) 技能。将该目录复制到 `~/.claude/skills/` 后，"请标注 Zotero 中的这篇论文"之类的请求即可端到端完成：技能指导模型定位条目、选择高亮句、以研究者笔记的语体撰写评论和页边批注，并调用本工具。`references/style-zh.md` 提供了详细的中文写作规范。

[`examples/direct_api_example.py`](examples/direct_api_example.py) 以约三十行代码演示了 Zotero 10 本地 API 的基本调用，可用于其他应用。

## 工作原理

1. 以只读方式用 PyMuPDF 打开 PDF，对每一页建立词级索引。
2. 将每条高亮短语与规范化后的词序列匹配，按文本行生成 PDF 用户空间中的矩形，并计算 Zotero 的排序索引。
3. 根据词坐标的分布估计正文栏的边界；每条总结锚定到所在段落的首行，布局在相邻的页边，并消除重叠。
4. 先移除上一次运行创建的工具自身注释，再通过所选通道写入新的注释对象。

注释条目的实测 JSON 结构、本地 API 的授权流程以及通道顺序的取舍见 [docs/design.md](docs/design.md)。

## 常见问题

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
```

插件由发布工作流打包；如需本地构建，将 `plugin/scholium-bridge/` 中的 `manifest.json` 与 `bootstrap.js` 置于 zip 压缩包根目录，命名为 `scholium-bridge.xpi`。

## 参与贡献

欢迎提交问题报告与合并请求。提交问题时请说明 Zotero 版本、操作系统与所用通道，并尽可能附上失败命令的输出及 `--list` 的结果。对 `src/zotero_scholium/cli.py` 的修改须通过 `python scripts/sync_skill_script.py` 同步到技能目录，CI 会检查两者是否一致。

## 许可证

本项目以 [MIT 许可证](LICENSE) 发布。

## 致谢

- [Zotero](https://www.zotero.org/)：其本地 API 使无插件写入成为可能。
- [PyMuPDF](https://pymupdf.readthedocs.io/)：用于文本提取与页面几何分析。
