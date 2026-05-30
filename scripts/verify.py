# -*- coding: utf-8 -*-
"""阶段7: 质量校对。检测空/过短、乱码残留、OCR字数偏低; 列出"删原始会丢内容"的文件。
用法: python3 verify.py --out <库>"""
import os, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_manifest, garble_score, HAN_RE

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    manifest = load_manifest(a.out)
    empty, garble, short_book, noraw = [], [], [], []
    ok = checked = 0
    for r in manifest:
        q = r.get("quality")
        if q not in ("text", "sparse"):
            continue
        rp = r.get("raw"); full = os.path.join(a.out, rp) if rp else None
        if not full or not os.path.exists(full):
            noraw.append(r["name"]); continue
        t = open(full, encoding="utf-8").read(); body = t.strip(); checked += 1
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
    images = [r for r in manifest if r.get("quality") == "image"]
    failed = [r["name"] for r in manifest if r.get("quality") == "failed"]
    print(f"\n删原始会丢内容: 图片型 {len(images)} 个 + 损坏 {len(failed)} 个(内容未进库)")
    if empty or garble or short_book or noraw:
        print("\n⚠ 有异常,建议修复(乱码->fix_garble; 空/OCR偏低->ocr_books或单独OCR)后再删原始")
    else:
        print("\n✓ 文字类无异常")

if __name__ == "__main__":
    main()
