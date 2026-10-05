<div align="center">

# zotero-scholium（注疏）

**让 Claude Code 或 Codex 读完论文，直接在 Zotero 里做好批注。**

重点句高亮并附译文，段落旁写页边批注，条目下生成阅读笔记。<br>
全部是 Zotero 原生注释，可编辑、可检索、随文库同步。

[![CI](https://github.com/weilr/zotero-scholium/actions/workflows/ci.yml/badge.svg)](https://github.com/weilr/zotero-scholium/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/weilr/zotero-scholium?color=blue)](https://github.com/weilr/zotero-scholium/releases/latest)
[![Zotero 7–10](https://img.shields.io/badge/zotero-7%20%7C%208%20%7C%209%20%7C%2010-cc2936.svg)](https://www.zotero.org/)

[English](README.md) | 中文

[快速上手](#快速上手) · [功能](#功能) · [工作原理](#工作原理) · [命令行](docs/cli.zh-CN.md) · [插件](plugin/README.md) · [更新日志](CHANGELOG.md)

</div>

<img src="docs/images/hero.webp" alt="在 Zotero 里一键批注：在 Scholium 区块输入附加要求，点批注，运行经过六个步骤，随后论文上出现三色高亮、侧栏译文、页边批注、便签和下划线" width="100%">

<sub>用 Claude Code 对 <i>Direct Preference Optimization</i>（CC BY 4.0）运行一次，所用个人配置见下表；动图经过加速，实际用时三分钟。本页所有示例都来自这次运行。</sub>

## 功能

<table>
<tr>
<td width="32%"><b>按含义分色高亮</b><br>红色是撑起全文的论点，绿色是方法，黄色是其余要点。用哪些颜色、各代表什么，由个人配置决定。</td>
<td><img src="docs/images/f-highlights.webp" alt="一段带黄、红、绿三色高亮的正文"></td>
</tr>
<tr>
<td><b>每条高亮附译文</b><br>高亮的评论就是这句话的译文，侧栏里原句和译文上下对照。</td>
<td><img src="docs/images/f-translations.webp" alt="侧栏里的两张高亮卡片，各有英文原句和中文译文"></td>
</tr>
<tr>
<td><b>页边批注</b><br>段落旁一两句话：读到这里的反应、疑问，或和其他章节的联系。不压正文、不压图表，彼此也不重叠。</td>
<td><img src="docs/images/f-margin.webp" alt="段落旁的蓝色页边批注"></td>
</tr>
<tr>
<td><b>标题上方的总结</b><br>首页顶部三四句话，概括全文。</td>
<td><img src="docs/images/f-summary.webp" alt="论文标题上方的四行蓝色总结"></td>
</tr>
<tr>
<td><b>下划线和便签</b><br>个人配置要求时，给定义加下划线，在每张图旁贴一张便签，说明该看什么。</td>
<td><img src="docs/images/f-marks.webp" alt="紫色下划线标出的定义及旁边的页边批注，图 1 旁的便签及其在侧栏中的内容，在原页上扫入"></td>
</tr>
<tr>
<td><b>阅读笔记</b><br>条目下的子笔记：论文做了什么、关键数字、哪些可信哪些存疑、悬而未决的问题。公式会渲染。</td>
<td><img src="docs/images/f-note.webp" alt="Zotero 笔记编辑器中的阅读笔记，从概述一路滚动到方法、结果和待解问题，公式已渲染"></td>
</tr>
<tr>
<td><b>在 Zotero 里一键批注</b><br>Scholium 区块对选中的论文运行 Claude Code 或 Codex，并显示每一步。结束后可以接着对话修改，比如「把第 5 页的译文改短」。</td>
<td><img src="docs/images/f-pane.webp" alt="运行中的第 2 页和 Scholium 区块：输入附加要求，点批注，步骤和过程记录推进，最后注释出现在页面上"></td>
</tr>
<tr>
<td><b>个人配置</b><br>从文库里已有的注释归纳你的标注习惯，再加上你自己的规则。每次运行都照它来，可以在 Zotero 里直接编辑。</td>
<td><img src="docs/images/f-profile.webp" alt="个人配置编辑器：左边是 Markdown 规则，右边是预览"></td>
</tr>
<tr>
<td><b>显示或隐藏</b><br>阅读器工具栏里的眼睛按钮，在所有阅读器中隐藏或重新显示本工具的注释。</td>
<td><img src="docs/images/f-toggle.webp" alt="点两下眼睛按钮：页面和侧栏里的注释先消失，再出现"></td>
</tr>
</table>

写入前代理会先预演：没对上的句子、多出术语或数字的译文、套话、重叠的高亮和放不下的页边批注都会列出来，改好再写。技能遵循 [Agent Skills](https://agentskills.io/) 规范，Claude Code、Codex、Cursor 等代理都能用。

## 快速上手

需要 Zotero 7 及以上并打开本地 API（设置 → 高级 →「允许此计算机上的其他应用程序与 Zotero 通讯」），以及 Python 3.9+ 和 PyMuPDF（`pip install pymupdf`）。

### 在 Zotero 里一键批注

1. 安装 [Claude Code](https://claude.com/claude-code) 或 [Codex](https://github.com/openai/codex) 并登录。
2. 为它安装技能：
   ```bash
   npx skills add weilr/zotero-scholium -g -y
   ```
3. 下载 [`scholium-bridge.xpi`](https://github.com/weilr/zotero-scholium/releases/latest/download/scholium-bridge.xpi)，在 Zotero 中安装：工具 → 插件 → ⚙ → 从文件安装插件。
4. 选中一篇论文，打开 **Scholium** 区块，点 **批注这篇**。Zotero 10 首次写入时会询问是否允许，选「始终允许」。

### 在代理对话里使用

按上面的方式装好技能，然后直接说：

```
给我 Zotero 里的《Direct Preference Optimization》做标注
把《Direct Preference Optimization》的核心论点高亮并翻译，加上页边批注
为《Direct Preference Optimization》写一篇阅读笔记
```

完成后关闭并重新打开 PDF 即可看到结果。

<details>
<summary>其他安装方式与更新</summary>

**Claude Code 插件**，由 `/plugin` 负责更新：

```
/plugin marketplace add weilr/zotero-scholium
/plugin install zotero-scholium@zotero-scholium
```

**手动安装：** 将 [`skills/zotero-scholium/`](skills/zotero-scholium/) 复制到代理的技能目录：Claude Code 为 `~/.claude/skills/`，Codex 为 `~/.codex/skills/`，其他代理为 `~/.agents/skills/`。该目录自成一体。

**更新：** `npx skills update zotero-scholium`，或 `/plugin update zotero-scholium@zotero-scholium`。插件通过 Zotero 的插件更新机制自动更新。

</details>

## 工作原理

```mermaid
flowchart LR
    A["Zotero 中的 PDF"] -->|extract| B["编号句子"]
    B --> C["代理读一遍，写配置：<br/>句子编号、译文、页边批注、阅读笔记"]
    C -->|预演| D["报告：未匹配、风格、<br/>译文、布局"]
    D -->|修正| C
    D -->|写入| E["Zotero 本地 API<br/>或随附插件"]
    E --> F["原生注释<br/>与子笔记"]
```

代理只需挑句子编号、写内容。原文在页面上的准确位置、页边批注放在段落旁哪块空白，都由工具算出；最后通过 Zotero 10 的本地 API（Zotero 7–9 通过随附插件）写入。

详见 [docs/design.md](docs/design.md)（数据模型、写入通道、重复运行）和 [references/configuration.md](skills/zotero-scholium/references/configuration.md)（全部选项与报告字段），两者均为英文。

## 参与贡献

欢迎提交问题报告和合并请求，开发说明见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可证

[MIT](LICENSE)

## 致谢

- [Zotero](https://www.zotero.org/)：其本地 API 使无插件写入成为可能。
- [PyMuPDF](https://pymupdf.readthedocs.io/)：用于文本提取与页面几何分析。
- 截图中的论文是 Rafailov 等人的 *Direct Preference Optimization: Your Language Model is Secretly a Reward Model*（NeurIPS 2023，[arXiv:2305.18290](https://arxiv.org/abs/2305.18290)，[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)）。
