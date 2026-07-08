# corpus-cleaner · 素材土壤库：清洗归档 + 检索使用

> 把一个塞满文件的素材包变成任何 agent 都能按协议检索的 Markdown 土壤库，绝大部分零 token。清洗只是地基，让库被用起来才是目的。

<div align="center">

![Version](https://img.shields.io/badge/version-v0.2.0-111827.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB.svg?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-0F766E.svg)
![License](https://img.shields.io/badge/license-MIT-059669.svg)

[我为什么做这个](#我为什么做这个) · [库为什么会闲置](#库为什么会闲置) · [怎么分层](#怎么分层) · [检索层](#检索层三件套) · [实战](#实战) · [快速开始](#快速开始) · [English](#english)

</div>

---

## 我为什么做这个

很多人桌面有这么一个文件夹。

囤了几年的 PDF / PPT / Word / 扫描书，几十上百 GB。真要用的时候找不到、打不开、格式杂、扫描书没法搜、特殊字体提取出来一堆乱码、老格式 .ppt 根本读不了。

直接放着烂可惜，**砸 LLM 和 OCR 成本全做又划不来**。

我清理过一个 478 文件 7GB 的营销素材包，跑完发现**绝大部分内容根本用不到 LLM**。分层处理，工具能搞定的先搞定，真正贵的手段只用在最后一层。这是它成为工具的原因。

## 库为什么会闲置

v0.1 做完清洗就停手了，结果库建好之后几乎没被用过。复盘发现问题在使用端：

- 库里只有一句「grep 检索」，来找素材的 agent 没有检索协议，要么全库通读烧上下文，要么碰运气 grep
- 没有粗筛层，标题和正文关键词全靠撞
- 没有增量能力，新素材进不来，库慢慢过期

v0.2 把这三块补齐：**build 之后每个库自带 SOIL.md（使用协议）+ CATALOG.md（粗筛目录），extract 天然增量，重跑安全**。同一套方法论的姊妹库验证过：焊上检索协议的库被高频使用，只有素材的库闲置。

## 为什么先分层再谈 LLM

一个 1000 文件的素材包里：

- 70% 是文字版 PDF / PPTX / DOCX，**Python 库就能读**
- 10% 是老格式或特殊字体的小问题，**工具修一下就行**（LibreOffice 转换、NFKC 部首归一化）
- 15% 是扫描文字书，**tesseract OCR 零 token 救回**
- 5% 才是纯设计版面（艺术字嵌图），轮到视觉模型

直接全上 LLM 或视觉模型，90% 的算力浪费在脚本能搞定的事上。**每多一层手段，成本数量级地涨。** 正确顺序反过来：先用最便宜的手段把能拿的全拿了，再看剩下多少值得贵的手段。

## 怎么分层

8 个阶段，按需触发。每个都零 token，产物是纯 Markdown + JSON，可读可改。

| 阶段 | 干什么 | 依赖 |
|---|---|---|
| 1+2 `extract` | 递归扫描 + pdf/pptx/docx/doc/epub 全部提取，自动判质量分类；**增量合并，重跑安全** | pymupdf, python-pptx, python-docx |
| 3 `fix_garble` | 部首归一化 + 去叠字，修特殊字体乱码 | 无 |
| 4 `convert_legacy` | LibreOffice 逐个转老格式 .ppt → .pptx 再提取 | LibreOffice |
| 5 `ocr_books` | 采样判定扫描文字书，全本 tesseract OCR，**逐本落盘断点续跑** | tesseract + 语言包 |
| 6 `build` | 归档 + 检索层三件套（INDEX / CATALOG / SOIL） | 无 |
| 7 `verify` | 质量校对 + 归档一致性校验，删原始前必跑 | 无 |
| 8 `cleanup` | 安全删原始（默认 dry-run），保留没进库的图片型 | 无 |

另有 `query.py` 两级检索器（标题/关键词加权 + 正文兜底），给来库里找素材的 agent 和人用。

决策点（质量阈值、分类关键词）都暴露在 `common.py` 和参数里。换领域改 `CATEGORY_RULES` 就行。

## 检索层三件套

`build` 之后每个库根目录自带：

- **SOIL.md** 使用协议，写给来检索的 agent：两级检索（先粗筛后深读，禁全库通读）、诚实空结果、引用溯源、OCR 文件核对后再精确引用
- **CATALOG.md** 粗筛目录，每文件一行：`标题 | 类目 | 字数 | 关键词 | 摘要 | 路径`，grep 它就是粗筛
- **INDEX.md** 总索引：类目分布 + 检索约定；手工维护的索引区块用 `--index-extra` 传入，重建不丢

每个文件的 front matter 带 `tags`（词频关键词）和 `excerpt`（首段摘要），零 token 生成，够粗筛用。

## 边界

**能做**：把混杂文档包变成可检索的结构化库、给老库补检索层、增量入库、救回印刷体中文扫描书、修常见特殊字体乱码。

**不能做**：

- 纯设计版面（作品集 / 品牌手册 / 海报式文案）的视觉理解。文案是艺术字嵌图，OCR 救不了，需要视觉模型逐页读，有 token 成本。这个工具帮你**识别和标记**这类文件，处理交给视觉模型或人。
- 单个文档的精细操作（写 docx / 转 PDF / 改 PPT）。专用工具更合适。这个工具专做「一批文件」和「库」。

## 实战

实测 478 文件 7GB 的营销文案素材包（品牌全案、4A 提案、扫描文案书、小红书标题合集、设计方案、大师文案珍藏 混杂）：

- **90% 可直接用**（431/477）
- **28 本扫描书 OCR 救回**，含 27 万字的 The Copy Book、Neil French、李欣频创意课等大师文案宝典
- **24 个特殊字体 PDF 乱码自动修复**
- **20 个老格式 .ppt 全部转换**，只 1 个源文件物理损坏
- **原始 7GB → 库 34MB**，后清理原始素材到 0

全程零 LLM token。

## 快速开始

```bash
git clone https://github.com/HeiGeAi/corpus-cleaner.git
cd corpus-cleaner

# Python 依赖
pip install -r requirements.txt

# 系统工具(可选,缺哪个对应阶段跳过)
# macOS
brew install --cask libreoffice
brew install tesseract tesseract-lang
# Linux (Debian/Ubuntu)
sudo apt install libreoffice tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-chi-tra
# Windows
# LibreOffice: libreoffice.org
# Tesseract:   github.com/UB-Mannheim/tesseract/wiki

# 建库
python3 scripts/extract.py        --src "你的素材包" --out "输出库"
python3 scripts/fix_garble.py     --out "输出库"                # 看到乱码再跑
python3 scripts/convert_legacy.py --src "..." --out "..."       # 有 .ppt 再跑
python3 scripts/ocr_books.py      --src "..." --out "..."       # 有扫描书再跑
python3 scripts/build.py          --out "..."                   # 归档+检索层三件套
python3 scripts/verify.py         --out "..."
python3 scripts/cleanup.py        --src "..." --out "..."       # 默认预览,加 --apply 真删

# 增量入库: 新文件丢进素材目录后
python3 scripts/extract.py --src "..." --out "..."              # 只提新文件,已处理的不动
python3 scripts/build.py   --out "..."

# 在库里找素材
python3 scripts/query.py --lib "输出库" 关键词1 关键词2 --top 10
```

## 兼容性

| 平台 | 状态 |
|---|---|
| macOS | 主测，推荐 |
| Linux | 支持（装 LibreOffice 和 tesseract 即可，.doc 走 LibreOffice fallback） |
| Windows | 实验性（路径自动检测已加，实战未充分测试） |

可选依赖缺失时，对应阶段会给出安装提示，其他阶段继续工作。`extract` / `fix_garble` / `build` / `verify` / `cleanup` / `query` 只需要 Python 包，全平台可跑。

v0.1 建的老库直接跑新 `build.py` 即可升级出检索层，老文件名保持原样，外部引用不断。

## 项目结构

```text
corpus-cleaner/
├── SKILL.md          # 给 Claude/agent 的工作流(skill 入口): 建库/增量/激活/使用四场景
├── README.md         # 给人看的介绍
├── requirements.txt
├── LICENSE
├── references/
│   └── notes.md      # 踩坑记录、阈值由来、增量兼容与检索层设计依据
└── scripts/
    ├── common.py            # 共享:清洗、分类规则、质量判定、增量合并、摘要关键词
    ├── extract.py           # 阶段 1+2: 递归扫描 + 分层提取(增量,重跑安全)
    ├── fix_garble.py        # 阶段 3: 乱码修复
    ├── convert_legacy.py    # 阶段 4: 老格式 .ppt 转换
    ├── ocr_books.py         # 阶段 5: 扫描书 OCR(断点续跑)
    ├── build.py             # 阶段 6: 归档 + INDEX/CATALOG/SOIL 检索层
    ├── verify.py            # 阶段 7: 质量校对 + 归档一致性
    ├── cleanup.py           # 阶段 8: 安全删原始
    └── query.py             # 两级检索器: 粗筛加权 + 正文兜底
```

## 数据策略

仓库只有代码、规则、文档，**没有任何素材或提取产物**。你的原始文件、清洗出的库、manifest 全在本地。

`scripts/common.py` 的 `CATEGORY_RULES` / `SUBCATEGORY_RULES` 默认是中文营销/文案领域的分类关键词。换领域改这里就好。

## 设计思想

一键全自动黑箱在这类活上不可靠，本工具走另一条路：每个阶段独立可调用，产物可读可改，质量阈值、分类规则、删除范围都暴露给人。

人和脚本协作，脚本不替代人。库为使用而建，检索协议随库交付。

## License

MIT。fork 后自己改也行。

---

<a id="english"></a>

# corpus-cleaner (English)

> Turn a folder stuffed with mixed documents into a structured Markdown library that agents retrieve by protocol. Mostly zero-token. Cleaning is the foundation; getting the library used is the point.

## Why I built this

Most people have this folder somewhere: hundreds of GB of PDF/PPT/Word/scanned-book files piled up over years. The moment you actually need them, you can't find anything. Scattered formats, scanned books aren't searchable, weird-font PDFs extract as garbled text, legacy .ppt files won't open.

Doing nothing wastes the asset. Throwing LLM/OCR at everything wastes money.

I cleaned my own 478-file, 7GB marketing corpus and realized **the vast majority needed no LLM at all**. Layer the work: cheap tools handle most of it, expensive moves stay for the last layer.

## Why libraries go unused (v0.2)

v0.1 stopped at cleaning. The library sat idle: agents arriving to search had no retrieval protocol, no coarse-scan layer, and no way to add new material. v0.2 fixes all three — every built library now ships with **SOIL.md** (retrieval protocol: two-tier search, honest empty results, source attribution) and **CATALOG.md** (one line per file: title | category | size | keywords | excerpt | path), `extract` is incremental and safe to re-run, and OCR checkpoints per book.

## How it layers

In a typical 1000-file corpus: 70% text PDFs/PPTX/DOCX (Python libs read them), 10% legacy/font issues (LibreOffice, NFKC), 15% scanned text books (tesseract, free), 5% pure design layouts (only then vision models). Each extra layer costs an order of magnitude more — take everything cheap can grab first.

| Stage | What | Deps |
|---|---|---|
| 1+2 `extract` | Recursive scan + extract, quality judge, auto-classify; **incremental merge, safe to re-run** | pymupdf, python-pptx, python-docx |
| 3 `fix_garble` | NFKC radical normalization + repeat-char dedup | none |
| 4 `convert_legacy` | LibreOffice converts legacy .ppt one by one | LibreOffice |
| 5 `ocr_books` | Sample-classify scanned books, full OCR, **checkpoint per book** | tesseract + lang packs |
| 6 `build` | Archive + retrieval layer (INDEX / CATALOG / SOIL) | none |
| 7 `verify` | Quality + archive consistency check | none |
| 8 `cleanup` | Safely delete originals (dry-run by default) | none |

Plus `query.py`: weighted two-tier retrieval (title ×5 / tags ×3 / body ×1) for agents searching the library.

## Battle-tested

478 files, 7GB marketing corpus: **90% directly usable** (431/477), 28 scanned books recovered via OCR, 24 weird-font PDFs auto-fixed, 20 legacy .ppt converted, 7GB → 34MB. Zero LLM tokens.

## Quick start

```bash
git clone https://github.com/HeiGeAi/corpus-cleaner.git
cd corpus-cleaner
pip install -r requirements.txt

python3 scripts/extract.py --src <corpus> --out <library>
python3 scripts/build.py   --out <library>            # archive + INDEX/CATALOG/SOIL
python3 scripts/verify.py  --out <library>
python3 scripts/query.py   --lib <library> keyword    # two-tier retrieval

# incremental: drop new files into <corpus>, then
python3 scripts/extract.py --src <corpus> --out <library>
python3 scripts/build.py   --out <library>
```

Libraries built by v0.1 upgrade in place: just run the new `build.py` — old filenames stay stable.

## Data policy

The repo contains only code, rules, and docs. **No corpora or extraction outputs.** Your source files and the cleaned library stay local. Default classification keywords target Chinese marketing/copy; change `CATEGORY_RULES` in `common.py` for other domains.

## License

MIT.
