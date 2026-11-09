eval.py run at bac8a66: evalset.json's four papers, one run each; Haiku, low effort, zh-CN, one-click Annotate; the agent was shown no budget (--max-msgs 60, --max-usd from the result lines); Zotero 10.0.8 on Windows. The agent ran scholium.py from the export in dpo and resnet and from the installed skill (v0.2.2) in ddpm and distill.

| metric | eval-dpo | eval-ddpm | eval-resnet | eval-distill | total |
|---|---|---|---|---|---|
| paper | 2305.18290 | 2006.11239 | 1512.03385 | 1503.02531 | |
| model | claude-haiku-5-5 | claude-haiku-5-5 | claude-haiku-5-5 | claude-haiku-5-5 |  |
| cost (USD) | 0.0234 | 0.0199 | 0.0232 | 0.02 | 0.0865 |
| wall time (s) | 91 | 98 | 103 | 109 | 401 |
| agent time (s) | 77 | 83 | 87 | 93 | 340 |
| turns | 10 | 11 | 11 | 13 | 45 |
| input tokens | 14 | 14 | 14 | 16 | 58 |
| cache read | 309467 | 261215 | 274235 | 271310 | 1116227 |
| cache write | 67107 | 51408 | 59968 | 46419 | 224902 |
| output tokens | 13755 | 14034 | 16835 | 16101 | 60725 |
|   of which thinking | 7029 | 7902 | 10679 | 9353 | 34963 |
| highlights | 32 | 24 | 31 | 31 | 118 |
|   core | 12 | 12 | 14 | 12 | 50 |
| pages with highlights | 9 | 9 | 8 | 8 |  |
| references start (page) | 11 | 9 | 9 | 9 |  |
| highlights from the references on | 0 | 4 | 2 | 0 |  |
|   share | 0.0 | 0.167 | 0.065 | 0.0 |  |
| comments empty | 0 | 0 | 0 | 0 |  |
| comments copying the English | 0 | 0 | 0 | 0 |  |
| comment length (chars, mean) | 61.9 | 67.3 | 47.9 | 56.4 |  |
| translation warnings (first dry run) | 0 | 0 | 0 | 0 |  |
| translation warnings (at apply) | 0 | 2 | 1 | 2 |  |
| margin notes | 5 | 5 | 4 | 6 | 20 |
| sticky notes | 0 | 0 | 0 | 0 | 0 |
| layout warnings | 0 | 0 | 0 | 0 |  |
| overlaps | 0 | 0 | 0 | 6 |  |
| margin notes set smaller | 0 | 0 | 0 | 0 |  |
| margin notes made sticky | 0 | 0 | 0 | 0 |  |
| phrases not found | 0 | 0 | 0 | 0 |  |
| reading note (chars) | 1825 | 1610 | 1495 | 1371 |  |
|   paragraphs | 7 | 7 | 7 | 7 |  |
|   headings | 7 | 7 | 7 | 7 |  |
|   has an <h1> | True | True | True | True |  |
|   has the citation | True | True | True | True |  |
| note title warnings | 0 | 0 | 0 | 0 |  |
| dry runs | 0 | 0 | 0 | 0 |  |
|   failed | 0 | 0 | 0 | 0 |  |
| --apply runs | 1 | 1 | 1 | 2 |  |
| applied | True | True | True | True |  |
| tool errors | 0 | 0 | 0 | 1 |  |
| agent runs (retries) | 1 | 1 | 1 | 1 |  |
| run ended in error | False | False | False | False |  |
| stopped by the probe | False | False | False | False |  |
| per page | 1:7 2:7 4:1 5:1 6:2 7:1 8:1 9:7 10:5 | 1:3 2:7 5:3 6:4 8:3 9:1 13:1 14:1 15:1 | 1:12 2:4 4:1 5:3 6:1 7:4 8:4 12:2 | 1:5 2:6 3:3 4:5 5:3 6:1 7:4 8:4 | |
| style warnings at apply | {} | {} | {} | {"overlap": 6} | |
| tool calls | Read 4, Skill 1, Write 2, apply 1 | Edit 1, Read 4, Skill 1, Write 2, apply 1 | Read 5, Skill 1, Write 2, apply 1 | Edit 1, Read 5, Skill 1, Write 2, apply 2 | |
