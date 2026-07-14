# -*- coding: utf-8 -*-
"""阶段6: 由 manifest + _raw 生成结构化归档库,以及让库"能被用起来"的三件套:
INDEX.md(总索引) + CATALOG.md(粗筛目录,每文件一行) + SOIL.md(给检索 agent 的使用协议)。
清空类目目录重建(MD 都是衍生物,真身在 _raw),每文件一个标准化 MD(front matter + 正文),
front matter 带 tags(词频关键词)和 excerpt(首段摘要),给两级检索当粗筛层。
默认只为有真实内容的 text/sparse 生成 MD; 加 --keep-image 也为图片型生成占位 MD。
--index-extra <file>: 把手工维护的索引区块(如精细结构化目录)拼进 INDEX.md,重建不丢。
用法: python3 build.py --out <库> [--keep-image] [--index-extra <md文件>]"""
import os, sys, argparse
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (load_manifest, safe_md, subcategory, SUBCATEGORY_FOR,
                    SUBCATEGORY_RULES, DEFAULT_SUBCATEGORY, fm_value,
                    auto_excerpt, auto_keywords, safe_join, secure_exists,
                    secure_makedirs, secure_read_text, secure_rmtree,
                    secure_write_text)

QLABEL = {"text": "文字型", "sparse": "稀疏", "image": "图片型"}

def wan(chars):
    return f"{chars/10000:.1f}万字" if chars >= 10000 else f"{chars}字"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep-image", action="store_true", help="也为图片型生成占位MD")
    ap.add_argument("--index-extra", default=None, help="拼进INDEX的手工区块md文件")
    a = ap.parse_args()
    manifest = load_manifest(a.out)
    if not manifest:
        sys.exit(f"manifest.json 不存在或为空: {os.path.join(a.out, 'manifest.json')} —— 先跑 extract.py,或检查 --out 路径是否写对")
    cats = sorted({r.get("category", "其他") for r in manifest})
    if any(c.replace("\\", "/").split("/", 1)[0].casefold() == "_raw" for c in cats):
        sys.exit("拒绝把保留目录 _raw 用作类目，避免删除原始提取物")

    # manifest 是可编辑文件，任何路径必须在删除旧归档前一次性预检。
    # 否则恶意或误写的 `..`/绝对路径可让 rmtree 越过 --out。
    try:
        category_dirs = {c: safe_join(a.out, c) for c in cats}
        raw_paths = {
            id(r): safe_join(a.out, r["raw"])
            for r in manifest
            if r.get("raw")
        }
    except ValueError as e:
        sys.exit(f"拒绝不安全的 manifest 路径: {e}")

    # 清空类目目录重建。只碰 manifest 里出现的类目,手工目录(精细结构化等)不动。
    for c in cats:
        secure_rmtree(a.out, c, missing_ok=True)

    qset = {"text", "sparse", "image"} if a.keep_image else {"text", "sparse"}
    written = 0
    catalog_rows = []
    for r in manifest:
        q = r.get("quality")
        if q not in qset:
            continue
        cat = r.get("category", "其他")
        sub = subcategory(r["name"]) if cat == SUBCATEGORY_FOR else None
        target_rel = os.path.join(cat, sub) if sub else cat
        secure_makedirs(a.out, target_rel)
        body = ""
        raw_rel = r.get("raw")
        if raw_rel and secure_exists(a.out, raw_rel):
            body = secure_read_text(a.out, raw_rel).strip()
        kws = auto_keywords(body) if body else []
        exc = auto_excerpt(body) if body else ""
        is_ocr = r.get("ocr")
        title = os.path.splitext(r["name"])[0]
        fm = ["---", f"title: {fm_value(title)}", f"source: {fm_value(r['name'])}",
              f"type: {r['ext'].lstrip('.')}", f"category: {fm_value(cat)}"]
        if sub: fm.append(f"subcategory: {fm_value(sub)}")
        fm += [f"{r.get('unit','pages')}: {r.get('count','')}", f"chars: {r.get('chars','')}",
               f"quality: {fm_value('文字型(OCR)' if is_ocr else QLABEL.get(q, q))}"]
        if kws: fm.append("tags: [" + ", ".join(fm_value(k) for k in kws) + "]")
        if exc: fm.append(f"excerpt: {fm_value(exc)}")
        if is_ocr: fm.append("ocr: true")
        if r.get("converted"): fm.append("converted: true (LibreOffice)")
        fm += ["---", ""]
        if is_ocr:
            fm.append("> 扫描页 OCR 识别,个别字可能有误,作参考土壤足够。\n")
        elif q == "image":
            fm.append(f"> 图片型,文本稀少({r.get('chars',0)}字),内容主要在图中,需视觉提炼。\n")
        fm.append(body)
        md_name = safe_md(r)
        secure_write_text(a.out, os.path.join(target_rel, md_name), "\n".join(fm))
        written += 1
        loc = f"{cat}/{sub}" if sub else cat
        row_kw = " ".join(kws) if kws else "-"
        row_exc = exc.replace("|", "/") if exc else "-"
        catalog_rows.append((title.replace("|", "/"), loc, r.get("chars", 0),
                             row_kw, row_exc, f"{loc}/{md_name}",
                             "OCR" if is_ocr else QLABEL.get(q, q)))

    # 统计
    live = [r for r in manifest if r.get("quality") in qset]
    cc = Counter(r.get("category", "?") for r in live)
    sub_cnt = Counter(subcategory(r["name"]) for r in live if r.get("category") == SUBCATEGORY_FOR)
    qc = Counter(r.get("quality") for r in manifest)
    ocr_n = sum(1 for r in live if r.get("ocr"))

    # CATALOG.md —— 粗筛层,每文件一行,agent 先 grep 这里再深读
    cat_lines = ["# CATALOG · 粗筛目录", "",
                 "每文件一行: `标题 | 类目 | 字数 | 关键词 | 摘要 | 路径`。",
                 "检索姿势: 先 grep 本文件锁定候选,再按路径深读正文。协议见 [SOIL.md](SOIL.md)。", ""]
    for t, loc, ch, kw, exc, path, ql in sorted(catalog_rows, key=lambda x: (x[1], -x[2])):
        cat_lines.append(f"- {t} | {loc} | {wan(ch)}{'·' + ql if ql != '文字型' else ''} | {kw} | {exc} | {path}")
    secure_write_text(a.out, "CATALOG.md", "\n".join(cat_lines))

    # SOIL.md —— 给消费这个库的 agent 的使用协议
    soil = ["# SOIL · 土壤库使用协议", "",
            "这是一个清洗过的素材土壤库。本文件写给来检索的 agent,约定检索方式与引用纪律。", "",
            "## 两级检索,先粗后深", "",
            "1. **粗筛**: 先 grep [CATALOG.md](CATALOG.md)(每文件一行,含标题/关键词/摘要),",
            "   或看 [INDEX.md](INDEX.md) 的类目分布。禁止一上来全库通读。",
            "2. **深读**: 粗筛命中的文件按路径 Read 正文。单轮深读控制在 3-5 个文件,不够再扩。",
            "3. **兜底**: 关键词冷门、粗筛无命中时,`grep -r \"关键词\"` 对应类目目录,再挑文件深读。",
            "", "有 corpus-cleaner skill 在手时可用 `python3 scripts/query.py --lib <本库> <关键词>`,",
            "标题/关键词命中加权排序,正文命中兜底,免手写多轮 grep。", "",
            "## 诚实与溯源", "",
            "- 检索不到就明说没有。库里不存在的内容,不能出现在引用里。",
            "- 引用要可溯源: 产出中注明素材来自哪个文件(front matter 的 source 是原始文件名)。",
            "- front matter 标 `ocr: true` 的文件经扫描识别,个别字可能有误,可参考,精确引用前先核对。",
            "- 标注图片型的文件正文是占位,内容在原图里,不能当正文引用。", "",
            "## 边界", "",
            "- 本库提供事实、案例、句式、方法论;风格和判断由使用方自己负责,库不替你写。",
            "- 类目分布: " + ", ".join(f"{c} {cc[c]}" for c in sorted(cc, key=lambda c: -cc[c])) + "。",
            "", "<!-- 建库人可在此追加领域约定/禁用内容/账号隔离等,build 重跑会覆盖本文件,改完请存 --index-extra 同款手工区块 -->"]
    secure_write_text(a.out, "SOIL.md", "\n".join(soil))

    # INDEX
    idx = ["# 素材土壤库 · 总索引", "",
           "结构化 Markdown,靠 grep / read 检索。每文件一个标准化 MD(front matter + 正文)。", "",
           f"共 {len(live)} 个可用文件。用法协议见 [SOIL.md](SOIL.md),粗筛目录见 [CATALOG.md](CATALOG.md),",
           f"质量见 [提取质量报告.md](提取质量报告.md),元数据见 manifest.json。", ""]
    if a.index_extra and os.path.exists(a.index_extra):
        idx += [open(a.index_extra, encoding="utf-8").read().strip(), ""]
    idx += ["## 类目", ""]
    for cat in sorted(cc, key=lambda c: -cc[c]):
        idx.append(f"- [`{cat}/`]({cat}/) — {cc[cat]} 个")
        if cat == SUBCATEGORY_FOR:
            for s, _ in SUBCATEGORY_RULES + [(DEFAULT_SUBCATEGORY, None)]:
                if sub_cnt.get(s):
                    idx.append(f"  - `{s}/` ({sub_cnt[s]})")
    idx += ["", "## 检索约定",
            "- 两级检索: 先 grep CATALOG.md 粗筛,命中再深读正文(详见 SOIL.md)",
            "- front matter 的 quality 字段标可用性;`ocr: true` 表示扫描识别(可能有个别字误)",
            f"- 共 {ocr_n} 本扫描书经 OCR 转正",
            "- _raw/ 留有全部提取文本备份"]
    secure_write_text(a.out, "INDEX.md", "\n".join(idx))

    # 质量报告
    rep = ["# 提取质量报告", "", f"全量 {len(manifest)} 个文件。", "", "## 质量分布", "",
           "| 质量 | 数量 |", "|---|---|"]
    for q, n in qc.most_common():
        rep.append(f"| {q} | {n} |")
    usable = qc.get("text", 0) + qc.get("sparse", 0)
    rep.append(f"\n**可直接用: {usable}/{len(manifest)} ({usable*100//max(len(manifest),1)}%)**")
    for tag, title in [("image", "图片型(内容在图里)"), ("needs_conversion", "待转换"),
                       ("failed", "提取失败"), ("unsupported", "不支持")]:
        rows = [r for r in manifest if r.get("quality") == tag]
        if rows:
            rep += ["", f"## {title} ({len(rows)})", ""]
            rep += [f"- [{r.get('chars','?')}字] [{r.get('category','?')}] {r['name']}" for r in
                    sorted(rows, key=lambda r: -r.get("chars", 0))]
    secure_write_text(a.out, "提取质量报告.md", "\n".join(rep))

    print(f"重建 {written} 个 MD + INDEX.md + CATALOG.md + SOIL.md + 提取质量报告.md")
    print("类目:", dict(cc))
    if sub_cnt: print(f"{SUBCATEGORY_FOR} 子类:", dict(sub_cnt))
    print(f"OCR 转正 {ocr_n} 本")

if __name__ == "__main__":
    main()
