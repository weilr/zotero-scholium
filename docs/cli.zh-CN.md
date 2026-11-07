# 命令行使用

[English](cli.md) | 中文

技能背后的工具也可以直接运行，供脚本或其他代理框架调用。

```bash
pip install pymupdf
pip install .                            # 提供 `scholium` 命令
```

技能目录中的同一文件是 `skills/zotero-scholium/scripts/scholium.py`，接受相同的参数，有两种运行方式：

```bash
python scholium.py …                     # 需已安装 Python 和 PyMuPDF
uv run scholium.py …                     # uv 读取脚本内嵌的元数据（PEP 723），自动获取 Python 和 PyMuPDF
```

## 步骤

1. **定位条目及其 PDF 附件**（Zotero 需处于运行状态并已打开本地 API）：

   ```bash
   scholium status --query "direct preference optimization"   # 匹配的条目及其 key
   scholium status ITEM_KEY                 # 这篇论文的 PDF、其上已有的注释和笔记
   scholium samples --exclude ITEM_KEY      # 以往运行的几条高亮、页边批注和笔记开头，作为风格参考
   ```

2. **把论文读成编号句子。**

   ```bash
   scholium extract --pdf paper.pdf --sentences out/sentences.json --out out/sentences.txt
   ```

   文件开头是行号索引：每页从哪一行开始；找得到时，还有正文在哪一行结束、参考文献从哪一行开始、其后的文字和附录从哪一行开始。
   没有文字层的 PDF（未做 OCR 的扫描件）会让 `extract` 以退出码 3 停下，并输出 JSON `error`，提示先做 OCR。

3. **编写配置文件。** 完整模板见[配置模板](../skills/zotero-scholium/examples/config.template.json)。

   ```json
   {
     "pdf": "/path/to/Zotero/storage/<ATTACHMENT_KEY>/paper.pdf",
     "item_key": "<ITEM_KEY>",
     "attachment_key": "<ATTACHMENT_KEY>",
     "out_dir": "out",
     "note_html": "reading_note.html",
     "note_title_prefix": "Direct Preference Optimization",
     "sentences": "out/sentences.json",
     "highlights": [
       {"id": 34, "core": true, "comment": "我们的主要贡献是直接偏好优化（DPO），一种从偏好中训练语言模型、无需 RL 的简单算法。"},
       {"page": 2, "core": false, "text": "In contrast, DPO directly optimizes for the policy best satisfying the preferences", "comment": "相比之下，DPO 直接优化最符合偏好的策略。"}
     ],
     "summaries": [
       {"id": 21, "text": "这张图把差别讲得很清楚。右边没有奖励模型，也没有采样循环。"},
       {"page": 1, "place": "top", "font_size": 9, "text": "横跨首页顶部的三四句总结"}
     ]
   }
   ```

   只保留用户要求的输出类型。每篇论文使用独立的 `out_dir`，如 `out/<ATTACHMENT_KEY>`，句子文件和笔记文件也放在该目录。仅完整重做时使用 `cleanup: true`；不设时只做添加（补笔记、页边批注或处理选定范围）。带阅读笔记的重做可设 `note_replace: true`，把工具以前的笔记移入回收站。

   群组文库里的条目，在配置里加 `"group_id": <群组 ID>`（插件的 `paper.json` 里有），`status` 和 `samples` 加 `--group <ID>`。

   `cleanup`、`note_replace`、`cleanup_external`、`snap` 和高亮的 `core` 只能是 `true` 或 `false`，`"false"` 这样的字符串会被拒绝。可选键写 `null` 表示取其默认值。`font_size` 与 `band_min_font_size` 一样，须为 4 到 36 之间的数。`note_html` 须为已存在的 HTML 文件的路径，不能直接写 HTML。颜色写作 `#rrggbb`，大小写均可，写入时转为 Zotero 要求的小写。高亮的 `comment` 是该句的译文；论文本身已是读者的语言时省略它。

4. **生成、检查、写入。** 首先不带 `--apply` 运行，检查下述四类报告并修正配置，再写入。

   ```bash
   scholium --config config.json            # 生成并报告，不写入
   scholium --config config.json --apply    # 生成、检查、写入 Zotero、回读（没装插件时经本地 API 写入，首次运行需确认授权对话框）
   scholium --config config.json --list     # 各类型/颜色数量、非本工具的注释、笔记标题（--full：全部输出）
   ```

   每次运行都生成 `annotations.json`、备用的 `create_annotations.js` 以及 `preview_pages` 所列页面的 `preview_p<N>.png`（默认不生成），并报告 `missed`（附该页上最接近的原句）、`style_warnings`、`translation_warnings`、`layout_warnings` 以及运行前后 PDF 的哈希；没有内容的字段（包括未变的 PDF 的哈希）不列出，加 `--verbose` 时全部列出。`missed`、`style_warnings`（`core_count` 除外）或 `layout_warnings` 不为空时 `--apply` 不写入（`--accept KIND`、`--allow-missed`、`--allow-warnings`）。页边批注放不下时，单栏页面先换到另一侧页边，仍放不下则改为便签；页首或页尾的文字放不下时自动缩小字号，最小 8 pt，仍放不下则改为便签。

   `--backend auto`（默认）依次经 Scholium 插件、Zotero 10 的本地 API、旧版插件写入，都不可用时生成 JavaScript 文件。本地 API 关闭时转到下一个通道，报告中说明原因；经本地 API 的读取会指出打开它的设置。本地 API 和 JavaScript 文件与插件一样，在写入任何内容之前拒绝不是该附件父条目的 `item_key`。注释使用 PDF 自身的页码标签（即 Zotero 显示的页码，如 `iv`），`sortIndex` 按阅读顺序编排，Zotero 因此按正文顺序列出注释；报告中的页码仍是从 1 开始的页序号。

   脚本通过 `127.0.0.1:23119` 访问 Zotero；设置了 `SCHOLIUM_ZOTERO_PORT` 时改用它指定的端口。插件启动智能体时会把它设为所在 Zotero 的端口。

[本地 API 调用示例](../examples/direct_api_example.py)以约三十行代码演示了 Zotero 10 本地 API 的基本调用，可用于其他应用。

## 参考

技能目录中的文件同样是命令行的参考（英文）。

| 文件 | 内容 |
|---|---|
| [`SKILL.md`](../skills/zotero-scholium/SKILL.md) | 工作流程：定位条目、选择句子、撰写评论与页边批注、调用脚本、核对结果 |
| [`references/configuration.md`](../skills/zotero-scholium/references/configuration.md) | 配置键、命令与报告字段 |
| [`references/backends.md`](../skills/zotero-scholium/references/backends.md) | 写入通道、失败处理与注意事项 |
| [`references/batch.md`](../skills/zotero-scholium/references/batch.md) | 一次请求多篇论文（用子代理）；内容审查 |
| [`references/profile.md`](../skills/zotero-scholium/references/profile.md) | 标注画像：`scholium profile --from-library` 从文库已有的注释归纳画像，`scholium profile --path` 打印它的位置；优先级与流程 |
| [`references/style-zh.md`](../skills/zotero-scholium/references/style-zh.md) | 中文评论、页边批注与阅读笔记的写作规范 |
| [`references/zotero-annotations.md`](../skills/zotero-scholium/references/zotero-annotations.md) | Zotero 注释的数据模型 |
| [`scripts/scholium.py`](../skills/zotero-scholium/scripts/scholium.py) | 工具本体，与 `src/zotero_scholium/cli.py` 完全一致 |
| [`examples/`](../skills/zotero-scholium/examples/) | 配置文件与阅读笔记模板 |
| [`agents/openai.yaml`](../skills/zotero-scholium/agents/openai.yaml) | Codex 中的显示名称与触发策略 |
