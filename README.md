# corpus-cleaner · 文档素材包清洗归档

> 把一个塞满文件的素材包变成任何 agent 都能 grep 检索的 Markdown 库,绝大部分零 token。

<div align="center">

![Version](https://img.shields.io/badge/version-v0.1.0-111827.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB.svg?logo=python&logoColor=white)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux%20%7C%20Windows-0F766E.svg)
![License](https://img.shields.io/badge/license-MIT-059669.svg)

[我为什么做这个](#我为什么做这个) · [为什么不直接全上 LLM](#为什么不是直接全上-llm) · [怎么分层](#怎么分层) · [实战](#实战) · [快速开始](#快速开始) · [兼容性](#兼容性) · [English](#english)

</div>

---

## 我为什么做这个

很多人桌面有这么一个文件夹。

囤了几年的 PDF / PPT / Word / 扫描书,几十上百 GB。真要用的时候找不到、打不开、格式杂、扫描书没法搜、特殊字体提取出来一堆乱码、老格式 .ppt 根本读不了。

直接放着烂可惜,**砸 LLM 和 OCR 成本全做又不划算**。

去年我帮自己清理了一个 478 文件 7GB 的营销素材包,跑完发现**绝大部分内容根本不需要 LLM**。分层处理,工具能搞定的先搞定,真正贵的手段只用在最后一层。这是把它沉淀成 skill 的原因。

## 为什么不是直接全上 LLM

一个 1000 文件的素材包里:

- 70% 是文字版 PDF / PPTX / DOCX,**Python 库就能读**
- 10% 是老格式或特殊字体的小问题,**工具修一下就行**(LibreOffice 转换、NFKC 部首归一化)
- 15% 是扫描文字书,**tesseract OCR 零 token 救回**
- 5% 才是纯设计版面(艺术字嵌图),轮到视觉模型

直接全上 LLM 或视觉模型,90% 的算力浪费在脚本能搞定的事上。**每多一层手段,成本数量级地涨**。

正确做法反过来:先用最便宜的手段把能拿的全拿了,再看剩下多少值得贵的手段。

## 怎么分层

8 个阶段,按需触发。每个都零 token,产物是纯 Markdown + JSON,可读可改。

| 阶段 | 干什么 | 依赖 |
|---|---|---|
| 1+2 `extract` | 扫描类型分布 + pdf/pptx/docx/doc/epub 全部提取,自动判质量分类 | pymupdf, python-pptx, python-docx |
| 3 `fix_garble` | 部首归一化 + 去叠字,修特殊字体乱码 | 无 |
| 4 `convert_legacy` | LibreOffice 转老格式 .ppt → .pptx 再提取 | LibreOffice |
| 5 `ocr_books` | 采样判定扫描文字书,全本 tesseract OCR | tesseract + 语言包 |
| 6 `build` | 分类归档 + 生成 INDEX 和质量报告 | 无 |
| 7 `verify` | 校对,删原始前必跑 | 无 |
| 8 `cleanup` | 安全删原始(默认 dry-run),保留没进库的图片型 | 无 |

决策点(质量阈值、分类关键词)都暴露在 `common.py` 和参数里。换领域改 `CATEGORY_RULES` 就行。

## 边界

**能做**:把混杂文档包变成可 grep 检索的结构化库,给 agent 当土壤,救回印刷体中文扫描书,修常见特殊字体乱码。

**不能做**:

- 纯设计版面(作品集 / 品牌手册 / 海报式文案)的视觉理解。文案是艺术字嵌图,OCR 救不了,需要视觉模型逐页读,有 token 成本。这个 skill 帮你**识别和标记**这类文件,处理交给视觉模型或人。
- 单个文档的精细操作(写 docx / 转 PDF / 改 PPT)。专用 skill 更合适。这个 skill 专做"一批文件"。

## 实战

实测 478 文件 7GB 的营销文案素材包(品牌全案、4A 提案、扫描文案书、小红书标题合集、设计方案、大师文案珍藏 混杂):

- **90% 可直接用**(431/477)
- **28 本扫描书 OCR 救回**,含 27 万字的 The Copy Book、Neil French、李欣频创意课等大师文案宝典
- **24 个特殊字体 PDF 乱码自动修复**
- **20 个老格式 .ppt 全部转换**,只 1 个源文件物理损坏
- **原始 7GB → 库 34MB**,后清理原始素材到 0

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

# 跑 pipeline
python3 scripts/extract.py        --src "你的素材包" --out "输出库"
python3 scripts/fix_garble.py     --out "输出库"                # 看到乱码再跑
python3 scripts/convert_legacy.py --src "..." --out "..."       # 有 .ppt 再跑
python3 scripts/ocr_books.py      --src "..." --out "..."       # 有扫描书再跑
python3 scripts/build.py          --out "..."
python3 scripts/verify.py         --out "..."
python3 scripts/cleanup.py        --src "..." --out "..."       # 默认预览,加 --apply 真删
```

## 兼容性

| 平台 | 状态 |
|---|---|
| macOS | 主测,推荐 |
| Linux | 支持(装 LibreOffice 和 tesseract 即可,.doc 走 LibreOffice fallback) |
| Windows | 实验性(路径自动检测已加,实战未充分测试) |

可选依赖缺失时,对应阶段会给出安装提示,其他阶段继续工作。`extract` / `fix_garble` / `build` / `verify` / `cleanup` 只需要 Python 包,全平台可跑。

## 项目结构

```text
corpus-cleaner/
├── SKILL.md          # 给 Claude/agent 的工作流(skill 入口)
├── README.md         # 给人看的介绍
├── requirements.txt
├── LICENSE
├── references/
│   └── notes.md      # 踩坑记录、阈值由来、调参依据
└── scripts/
    ├── common.py            # 共享:清洗、分类规则、质量判定、跨平台工具检测
    ├── extract.py           # 阶段 1+2: 扫描 + 分层提取
    ├── fix_garble.py        # 阶段 3: 乱码修复
    ├── convert_legacy.py    # 阶段 4: 老格式 .ppt 转换
    ├── ocr_books.py         # 阶段 5: 扫描书 OCR
    ├── build.py             # 阶段 6: 归档 + 索引
    ├── verify.py            # 阶段 7: 质量校对
    └── cleanup.py           # 阶段 8: 安全删原始
```

## 数据策略

仓库只有代码、规则、文档,**没有任何素材或提取产物**。你的原始文件、清洗出的库、manifest 全在本地。

`scripts/common.py` 的 `CATEGORY_RULES` / `SUBCATEGORY_RULES` 默认是中文营销/文案领域的分类关键词。换领域改这里就好。

## 设计思想

不追求一键全自动黑箱。每个阶段独立可调用,产物可读可改,质量阈值、分类规则、删除范围都暴露给人。

人和脚本协作,脚本不替代人。

## License

MIT。fork 后自己改也行。

---

<a id="english"></a>

# corpus-cleaner (English)

> Turn a folder stuffed with mixed documents into a structured, grep-able Markdown library that any agent can search. Mostly zero-token.

## Why I built this

Most people have this folder somewhere: hundreds of GB of PDF/PPT/Word/scanned-book files piled up over years. The moment you actually need them, you can't find anything. Scattered formats, scanned books aren't searchable, weird-font PDFs extract as garbled text, legacy .ppt files won't open.

Doing nothing wastes the asset. Throwing LLM/OCR at everything wastes money.

I cleaned my own 478-file, 7GB marketing corpus and realized **the vast majority needed no LLM at all**. Layer the work: cheap tools handle most of it, expensive moves stay for the last layer. That's why this became a skill.

## Why not just throw LLM/OCR at everything

In a typical 1000-file corpus:

- 70% are text PDF / PPTX / DOCX — **Python libs read them directly**
- 10% are legacy formats or font issues — **fix with tools** (LibreOffice convert, NFKC radicals)
- 15% are scanned text books — **tesseract OCR for free**
- 5% are pure design layouts — **only then bring in vision models**

Going full-LLM wastes 90% of the compute on things scripts can do. Each extra layer costs an order of magnitude more.

Reverse the order: take everything cheap can grab first, then look at what's left and worth paying for.

## How it layers

| Stage | What | Deps |
|---|---|---|
| 1+2 `extract` | Scan distribution + extract pdf/pptx/docx/doc/epub, judge quality, auto-classify | pymupdf, python-pptx, python-docx |
| 3 `fix_garble` | NFKC radical normalization + repeat-char dedup | none |
| 4 `convert_legacy` | LibreOffice batch convert legacy .ppt | LibreOffice |
| 5 `ocr_books` | Sample-classify scanned books, then full tesseract OCR | tesseract + lang packs |
| 6 `build` | Categorize, write standardized MDs, INDEX + quality report | none |
| 7 `verify` | Quality check before deleting originals | none |
| 8 `cleanup` | Safely delete originals (dry-run by default), keep unconverted image-type files | none |

Every output is plain Markdown + JSON manifest, readable and editable. Thresholds and classification keywords live in `common.py`.

## Battle-tested

478 files, 7GB marketing corpus mixed with brand decks, 4A pitches, scanned copy books, small-RED-book title collections, design layouts, and master copywriting collections:

- **90% directly usable** (431/477)
- **28 scanned books recovered via OCR**, including The Copy Book (270k chars), Neil French, Li Xinpin
- **24 weird-font PDFs auto-fixed**
- **20 legacy .ppt all converted**, only 1 physically damaged
- **Original 7GB → 34MB library**, then originals fully cleaned

Zero LLM tokens spent.

## Quick start

```bash
git clone https://github.com/HeiGeAi/corpus-cleaner.git
cd corpus-cleaner
pip install -r requirements.txt

# macOS
brew install --cask libreoffice
brew install tesseract tesseract-lang
# Linux (Debian/Ubuntu)
sudo apt install libreoffice tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-chi-tra
# Windows: libreoffice.org, github.com/UB-Mannheim/tesseract/wiki

python3 scripts/extract.py        --src <corpus> --out <library>
python3 scripts/fix_garble.py     --out <library>           # if garble found
python3 scripts/convert_legacy.py --src ... --out ...       # if legacy .ppt
python3 scripts/ocr_books.py      --src ... --out ...       # if scanned books
python3 scripts/build.py          --out ...
python3 scripts/verify.py         --out ...
python3 scripts/cleanup.py        --src ... --out ...       # dry-run; add --apply
```

## Compatibility

| Platform | Status |
|---|---|
| macOS | Primary, full functionality |
| Linux | Supported (LibreOffice + tesseract); .doc falls back to LibreOffice |
| Windows | Experimental (path detection added, not battle-tested) |

Missing optional dependencies just skip the relevant stage. `extract` / `fix_garble` / `build` / `verify` / `cleanup` only need Python packages and run everywhere.

## Data policy

The repo contains only code, rules, and docs. **No corpora or extraction outputs.** Your source files and the cleaned library stay local.

`scripts/common.py` default classification keywords target Chinese marketing/copy. Change `CATEGORY_RULES` for other domains.

## License

MIT.
