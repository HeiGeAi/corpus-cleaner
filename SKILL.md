---
name: corpus-cleaner
description: 素材土壤库的全生命周期工具：把混杂的文档资料包（PDF/PPTX/PPT/DOCX/DOC/epub，可能含扫描书和设计版面）清洗、提取、OCR、分类，归档成结构化可检索的 Markdown 土壤库；给已有的土壤库做增量入库、升级检索层（粗筛目录+使用协议）、体检修复；也指导 agent 按协议检索使用土壤库。当用户有一个塞满文件的素材包/资料包/合集文件夹想"整理成知识库""清洗成可检索的库""做成写作土壤""提取里面的文字内容""归档这些资料"时使用，即使没明说"清洗"二字。也适用于：往已有土壤库里加新素材、给老库补检索索引/使用协议、库里找素材写稿、几十上百个 PDF/PPT 批量提取文字、扫描版 PDF 要 OCR、特殊字体 PDF 乱码要修、老格式 .ppt 打不开要转换、资料整理完想删原始大文件省空间。处理的是"一批文件"和"库"（单文件转换用 pdf/docx/pptx 等专用 skill）。
---

# 素材土壤库：清洗归档 + 检索使用

把一个混杂的文档文件夹变成结构化、可检索的 Markdown 土壤库，并让它真正被用起来。

**实践结论（为什么有使用层）**：土壤库的价值大头在被检索使用，素材本身只是地基。清洗完只留一句"grep 检索"的库会闲置；焊上检索协议（SOIL.md）和粗筛目录（CATALOG.md）的库才对写作/研究 agent 产生杠杆。所以本 skill 管全生命周期：建库、增量、激活、使用。

## 四个场景,先对号入座

| 场景 | 特征 | 走法 |
|---|---|---|
| A 从零建库 | 手里是原始素材包 | 工作流阶段 1→8 |
| B 增量入库 | 库已在,来了新素材 | 新文件放进素材目录 → extract(天然增量) → 按需 3/4/5 → build → verify |
| C 激活老库 | 库只有正文没有检索层 | 直接 build(生成 SOIL/CATALOG/INDEX;手工索引区块用 --index-extra 保住) |
| D 用库找素材 | 写作/研究要引用素材 | 读库根目录 SOIL.md 按协议检索;或 query.py 一步粗筛 |

## 核心思想:分层处理,成本递增

不要一上来就对所有文件用 LLM 或 OCR。按成本从低到高分层,**每层只处理上一层搞不定的**:

1. 脚本零成本能提的(文字版 PDF、PPTX、DOCX),全部先提。这是 80%+。
2. 老格式 / 乱码,用工具修(LibreOffice、NFKC 归一化),仍零 token。
3. 扫描文字书,用 tesseract OCR 救回,零 token。
4. 纯设计版面(内容是艺术字嵌图),才考虑视觉模型逐页读,有成本,挑高价值的做。

经验:一个典型素材包,90% 内容能零 token 提取入库。把贵的手段留给真正需要的少数。

## 前置依赖

```bash
pip install -r requirements.txt                    # pymupdf / python-pptx / python-docx

# 可选,缺哪个对应阶段跳过:
# macOS
brew install --cask libreoffice                    # 阶段4 老 .ppt + 非macOS的 .doc
brew install tesseract tesseract-lang              # 阶段5 扫描书 OCR
# Linux (Debian/Ubuntu)
sudo apt install libreoffice tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-chi-tra
# Windows: 从 libreoffice.org 和 github.com/UB-Mannheim/tesseract/wiki 下载安装
```
脚本自动跨平台检测 LibreOffice 路径。macOS 上 .doc 用 textutil(自带),其他平台 fallback 到 LibreOffice。

## 工作流(场景 A;场景 B/C 取其中几步)

所有脚本在 `scripts/`,统一参数 `--src`(原始素材包目录)`--out`(输出库目录)。按序运行,每步看输出再决定下一步是否需要。

### 1+2. 扫描 + 分层提取(必做;重跑安全,天然增量)
```bash
python3 scripts/extract.py --src "<素材包>" --out "<库目录>"
```
递归扫描子目录,打印类型分布,提取所有 PDF/PPTX/DOCX/DOC/epub 到 `<库>/_raw/all/*.txt`,增量合并进 `manifest.json`。每个文件判 `quality`:`text`(文字型)/`sparse`(稀疏)/`image`(图片型,内容在图里)/`needs_conversion`(老格式ppt)。按文件名关键词自动分 `category`。
**增量语义**:已处理好的记录(含 OCR/转换/修复成果)原样保留,只提新文件和上次失败的。所以"往素材目录加文件后重跑"就是增量入库。`--force` 才会强制重提。
看输出的质量分布,决定后面几步做不做。

### 3. 乱码修复(如果有特殊字体文件)
```bash
python3 scripts/fix_garble.py --out "<库目录>"
```
有些 PDF 用了子集字体,提取出来是叠字(整理理、不不)或康熙部首字符(⽂⻚)。这步自动检测并修复。判断要不要做:抽看几个文字型 MD,有叠字就跑。

### 4. 老格式 .ppt 转换(如果扫描分布里有 .ppt)
```bash
python3 scripts/convert_legacy.py --src "<素材包>" --out "<库目录>"
```
LibreOffice 把 `needs_conversion` 的老 .ppt 逐个转 pptx 再提取(一个损坏不带累整批),损坏的标 failed。

### 5. 扫描书 OCR(如果图片型里有文字书)
```bash
python3 scripts/ocr_books.py --src "<素材包>" --out "<库目录>"
```
先对每个图片型 PDF 采样几页 OCR,按识别字数区分**扫描文字书**(值得全本 OCR)和**纯设计版面**(跳过)。再全本 OCR 扫描书。**每本完成即写盘,中断后重跑自动跳过已完成的,放心后台跑长任务。**
注意:`--threshold` 默认 150 字/页。设计型文案合集(艺术字)会被判低于阈值跳过,那类要视觉模型读(见下方"图片型的取舍")。

### 6. 归档 + 检索层(必做,每次改完数据都重跑)
```bash
python3 scripts/build.py --out "<库目录>" [--index-extra <手工索引区块.md>]
```
清空类目目录,由 manifest+_raw 重新生成每文件的标准化 MD(front matter 带 tags 词频关键词 + excerpt 首段摘要),并生成检索层三件套:
- `INDEX.md` 总索引(类目分布;`--index-extra` 把手工维护的区块拼在头部,重建不丢)
- `CATALOG.md` 粗筛目录,每文件一行:标题|类目|字数|关键词|摘要|路径
- `SOIL.md` 使用协议,写给来检索的 agent(两级检索、诚实引用、溯源)
这步幂等,是"重建"工具——前面任何阶段改了 manifest 都重跑它刷新库。默认只为 text/sparse 生成 MD,加 `--keep-image` 保留图片型占位。

### 7. 质量校对(删原始前必做)
```bash
python3 scripts/verify.py --out "<库目录>"
```
检测空/过短、乱码残留、OCR 字数偏低,并校验归档一致性(manifest 记录缺 MD、类目里的孤儿 MD)。有异常先回对应阶段修(乱码→3,空/OCR偏低→5,缺MD→6),再校对,直到文字类无异常。

### 8. 安全删除原始(可选,用户要省空间时)
```bash
python3 scripts/cleanup.py --src "<素材包>" --out "<库目录>"            # 先预览
python3 scripts/cleanup.py --src "<素材包>" --out "<库目录>" --apply    # 确认后真删
```
**默认 dry-run,只列不删。** 只删"已完整进库"的(text/sparse 且 _raw 留档存在)。
图片型/损坏文件内容没进库,默认保留;用户明确不要视觉内容时加 `--delete-image` 才一并删。
这是不可逆操作,务必先 verify 通过、先预览、且向用户讲清"图片型删了内容就没了"再 --apply。

## 场景 D:在库里找素材(教 agent 用库)

先读库根目录的 `SOIL.md`(每个新库 build 时自带),核心约定:

1. **两级检索**:先 grep `CATALOG.md` 粗筛(标题/关键词/摘要命中),再按路径深读正文,单轮 3-5 个文件。禁止全库通读。
2. **兜底**:粗筛无命中时 `grep -r "关键词" <类目目录>`,或用本 skill 的检索器:
   ```bash
   python3 scripts/query.py --lib "<库目录>" 关键词1 关键词2 [--cat 类目] [--top 10]
   ```
   标题×5/标签摘要×3/正文×1 加权排序,输出候选路径和命中上下文。
3. **诚实与溯源**:检索不到就明说没有;引用注明来源文件;`ocr: true` 的文件精确引用前先核对原文。

## 关键判断(写给运行这个 skill 的你)

- **同内容多版本挑干净的**:素材包常有同一份资料的多个版本(一个乱码、一个清晰)。提取后比对,弃用乱码版,别浪费力气修它。
- **图片型的取舍**:图片型分两种。扫描文字书(阶段5的OCR能救)和纯设计版面(作品集/品牌手册/海报式文案)。后者内容是艺术字嵌设计,OCR救不了,只能视觉模型逐页读,成本高——**先问用户这类视觉内容他要不要**,很多人的文字场景根本不需要,直接保持占位或删掉。要做的话,渲染页面(fitz get_pixmap)成图,Read 进来人工/视觉转录,挑高价值的几本,别全做。
- **摘要增值(可选,有会话 token 成本)**:build 自带的 tags/excerpt 是零成本词频法,够粗筛。高价值类目想要真摘要,可由你(或子 agent)批量读 `_raw` 写三行摘要回填 MD 的 front matter——只对用户点名的高价值类目做,先报成本再动手。
- **删原始的红线**:`text/sparse` 内容已在 `_raw` 留档,删原始安全;`image/failed` 内容没进库,删了永久丢失。cleanup.py 已按此分。删前一定 verify + 预览 + 跟用户确认。
- **别覆盖手工资产**:build 只清空 manifest 里出现的类目目录,手工建的精细结构化目录(如单独整理的公式库)不会被碰;但 INDEX.md 会重生成,手工索引区块要用 `--index-extra` 传入保住。SOIL.md 同理,建库人加过自定义约定就把它挪进 index-extra 或改完别重跑 build。
- **分类不必完美**:`common.py` 的分类关键词是按营销/文案领域配的。换领域就改 `CATEGORY_RULES`/`SUBCATEGORY_RULES`。分类错几个无所谓,用户能手动挪,重点是内容都提到了、可检索。
- **质量阈值**:PDF 按 平均字符/页 判 text(≥80)/sparse(≥15)/image(<15),PPTX 用 60/12。扫描书 OCR 采样阈值 150 字/页。这些在 common.py / 脚本参数里可调。

详细的踩坑记录和阈值由来见 `references/notes.md`。
