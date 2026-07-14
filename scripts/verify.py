# -*- coding: utf-8 -*-
"""阶段7: 质量校对。检测空/过短、乱码残留、OCR字数偏低; 校验归档库与 manifest 一致
(每条记录的 MD 是否在、类目目录里有没有孤儿 MD); 列出"删原始会丢内容"的文件。
用法: python3 verify.py --out <库>"""
import os, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (load_manifest, garble_score, HAN_RE, safe_md, safe_join,
                    subcategory, SUBCATEGORY_FOR, secure_exists, secure_is_dir,
                    secure_read_text)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    manifest = load_manifest(a.out)
    try:
        categories = {r.get("category", "其他") for r in manifest}
        category_dirs = {c: safe_join(a.out, c) for c in categories}
        raw_paths = {
            id(r): safe_join(a.out, r["raw"])
            for r in manifest
            if r.get("raw")
        }
    except ValueError as e:
        sys.exit(f"拒绝不安全的 manifest 路径: {e}")
    empty, garble, short_book, noraw = [], [], [], []
    ok = checked = 0
    for r in manifest:
        q = r.get("quality")
        if q not in ("text", "sparse"):
            continue
        rp = r.get("raw")
        if not rp or not secure_exists(a.out, rp):
            noraw.append(r["name"]); continue
        t = secure_read_text(a.out, rp); body = t.strip(); checked += 1
        if len(body) < 30:
            empty.append((r["name"], len(body))); continue
        if len(HAN_RE.findall(t)) >= 50:
            rad, dup = garble_score(t)
            if rad > 0.03 or dup > 0.06:
                garble.append((r["name"], round(rad*100, 1), round(dup*100, 1))); continue
        if r.get("ocr") and r.get("count", 0) >= 20 and r.get("chars", 0) < r["count"] * 50:
            short_book.append((r["name"], r.get("count"), r.get("chars")))
        ok += 1
    print(f"校对 text/sparse: {checked} 个 | 正常 {ok} | 空 {len(empty)} | 乱码残留 {len(garble)} | OCR偏低 {len(short_book)} | 无raw {len(noraw)}")
    for title, rows in [("空/过短", empty), ("乱码残留(部首%/叠字%)", garble),
                        ("OCR字数偏低", short_book), ("无raw", noraw)]:
        if rows:
            print(f"\n=== {title} ===")
            for x in rows: print("  ", x)

    # 归档库一致性: manifest 记录 <-> 类目目录里的 MD
    cats = categories
    built = any(secure_is_dir(a.out, c) for c in cats)
    if built:
        expected = {}
        for r in manifest:
            if r.get("quality") not in ("text", "sparse"):
                continue
            cat = r.get("category", "其他")
            sub = subcategory(r["name"]) if cat == SUBCATEGORY_FOR else None
            parts = [cat, sub, safe_md(r)] if sub else [cat, safe_md(r)]
            rel = os.path.join(*parts)
            safe_join(a.out, rel)
            expected[rel] = r["name"]
        missing_md = [v for k, v in expected.items() if not secure_exists(a.out, k)]
        orphan = []
        for c in cats:
            d = category_dirs[c]
            for root, _, files in os.walk(d):
                for f in files:
                    rel = os.path.relpath(os.path.join(root, f), a.out)
                    if f.endswith(".md") and rel not in expected:
                        orphan.append(rel)
        print(f"\n归档一致性: 缺 MD {len(missing_md)} | 孤儿 MD {len(orphan)}")
        if missing_md:
            print("  缺 MD(跑 build.py 重建):", missing_md[:10], "..." if len(missing_md) > 10 else "")
        if orphan:
            print("  孤儿 MD(不在 manifest,可能是旧版命名或手工文件):")
            for o in orphan[:10]: print("   ", o)
            if len(orphan) > 10: print(f"    ...共 {len(orphan)} 个")
    else:
        print("\n(库尚未 build,跳过归档一致性检查)")

    images = [r for r in manifest if r.get("quality") == "image"]
    failed = [r["name"] for r in manifest if r.get("quality") == "failed"]
    print(f"\n删原始会丢内容: 图片型 {len(images)} 个 + 损坏 {len(failed)} 个(内容未进库)")
    if empty or garble or short_book or noraw:
        print("\n⚠ 有异常,建议修复(乱码->fix_garble; 空/OCR偏低->ocr_books或单独OCR)后再删原始")
    else:
        print("\n✓ 文字类无异常")

if __name__ == "__main__":
    main()
