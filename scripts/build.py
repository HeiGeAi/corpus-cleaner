# -*- coding: utf-8 -*-
"""阶段6: 由 manifest + _raw 生成结构化归档库。
清空类目目录重建(MD 都是衍生物),每文件一个标准化 MD(front matter + 正文),
大类按关键词分子类,生成 INDEX.md 总索引 + 提取质量报告.md。
默认只为有真实内容的 text/sparse 生成 MD; 加 --keep-image 也为图片型生成占位 MD。
用法: python3 build.py --out <库> [--keep-image]"""
import os, sys, argparse, shutil
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (load_manifest, safe_md, classify, subcategory, SUBCATEGORY_FOR,
                    SUBCATEGORY_RULES, DEFAULT_SUBCATEGORY)

QLABEL = {"text": "文字型", "sparse": "稀疏", "image": "图片型"}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep-image", action="store_true", help="也为图片型生成占位MD")
    a = ap.parse_args()
    manifest = load_manifest(a.out)
    cats = sorted({r.get("category", "其他") for r in manifest})

    # 清空类目目录(不碰 _raw / manifest / 已有的精细结构化目录如非本流程生成的)
    for c in cats:
        d = os.path.join(a.out, c)
        if os.path.exists(d):
            shutil.rmtree(d)

    qset = {"text", "sparse", "image"} if a.keep_image else {"text", "sparse"}
    written = 0
    for r in manifest:
        q = r.get("quality")
        if q not in qset:
            continue
        cat = r.get("category", "其他")
        tgt = os.path.join(a.out, cat, subcategory(r["name"])) if cat == SUBCATEGORY_FOR else os.path.join(a.out, cat)
        os.makedirs(tgt, exist_ok=True)
        body = ""
        if r.get("raw") and os.path.exists(os.path.join(a.out, r["raw"])):
            body = open(os.path.join(a.out, r["raw"]), encoding="utf-8").read().strip()
        is_ocr = r.get("ocr")
        fm = ["---", f"title: {os.path.splitext(r['name'])[0]}", f"source: {r['name']}",
              f"type: {r['ext'].lstrip('.')}", f"category: {cat}",
              f"{r.get('unit','pages')}: {r.get('count','')}", f"chars: {r.get('chars','')}",
              f"quality: {'文字型(OCR)' if is_ocr else QLABEL.get(q, q)}"]
        if is_ocr: fm.append("ocr: true")
        if r.get("converted"): fm.append("converted: true (LibreOffice)")
        fm += ["---", ""]
        if is_ocr:
            fm.append("> 扫描页 OCR 识别,个别字可能有误,作参考土壤足够。\n")
        elif q == "image":
            fm.append(f"> 图片型,文本稀少({r.get('chars',0)}字),内容主要在图中,需视觉提炼。\n")
        fm.append(body)
        open(os.path.join(tgt, safe_md(r["name"])), "w", encoding="utf-8").write("\n".join(fm))
        written += 1

    # 统计
    live = [r for r in manifest if r.get("quality") in qset]
    cc = Counter(r.get("category", "?") for r in live)
    sub_cnt = Counter(subcategory(r["name"]) for r in live if r.get("category") == SUBCATEGORY_FOR)
    qc = Counter(r.get("quality") for r in manifest)
    ocr_n = sum(1 for r in live if r.get("ocr"))

    # INDEX
    idx = ["# 素材土壤库 · 总索引", "",
           "结构化 Markdown,靠 grep / read 检索。每文件一个标准化 MD(front matter + 正文)。", "",
           f"共 {len(live)} 个可用文件。质量见 [提取质量报告.md](提取质量报告.md),元数据见 manifest.json。", "",
           "## 类目", ""]
    for cat in sorted(cc, key=lambda c: -cc[c]):
        idx.append(f"- [`{cat}/`]({cat}/) — {cc[cat]} 个")
        if cat == SUBCATEGORY_FOR:
            for s, _ in SUBCATEGORY_RULES + [(DEFAULT_SUBCATEGORY, None)]:
                if sub_cnt.get(s):
                    idx.append(f"  - `{s}/` ({sub_cnt[s]})")
    idx += ["", "## 检索约定",
            "- front matter 的 quality 字段标可用性;`ocr: true` 表示扫描识别(可能有个别字误)",
            "- 按主题找参考 -> 对应类目目录,grep 关键词",
            f"- 共 {ocr_n} 本扫描书经 OCR 转正",
            "- _raw/ 留有全部提取文本备份"]
    open(os.path.join(a.out, "INDEX.md"), "w", encoding="utf-8").write("\n".join(idx))

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
            rep += [f"- [{r.get('chars','?')}字] [{r['category']}] {r['name']}" for r in
                    sorted(rows, key=lambda r: -r.get("chars", 0))]
    open(os.path.join(a.out, "提取质量报告.md"), "w", encoding="utf-8").write("\n".join(rep))

    print(f"重建 {written} 个 MD")
    print("类目:", dict(cc))
    if sub_cnt: print(f"{SUBCATEGORY_FOR} 子类:", dict(sub_cnt))
    print(f"OCR 转正 {ocr_n} 本")

if __name__ == "__main__":
    main()
