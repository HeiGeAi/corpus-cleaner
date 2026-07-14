# -*- coding: utf-8 -*-
"""阶段3: 修复特殊字体导致的乱码(康熙部首区字符 + 叠字)。
原理: PDF 子集字体的 ToUnicode 映射坏,把字编码成康熙部首区字符或重复字形。
修法: 部首区字符单独 NFKC 归一化(不动标点/全角),再去掉"本文件内反复出现"的相邻重复字(避开正常叠词)。
用法: python3 fix_garble.py --out <库目录> [--rad 0.03] [--dup 0.06]"""
import os, sys, argparse, unicodedata
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (load_manifest, save_manifest, garble_score, HAN_RE, safe_join,
                    secure_exists, secure_read_text, secure_write_text)

def norm_radicals(text):
    out = []
    for ch in text:
        o = ord(ch)
        if 0x2E80 <= o <= 0x2EFF or 0x2F00 <= o <= 0x2FDF:
            out.append(unicodedata.normalize("NFKC", ch))
        else:
            out.append(ch)
    return "".join(out)

def dedup_repeats(text):
    chars = list(text)
    dup = Counter()
    for i in range(1, len(chars)):
        if chars[i] == chars[i-1] and HAN_RE.match(chars[i]):
            dup[chars[i]] += 1
    garble = {c for c, n in dup.items() if n >= 3}  # 反复重复=乱码; 偶发=正常叠词
    return "".join(ch for i, ch in enumerate(chars)
                   if not (i > 0 and ch == chars[i-1] and ch in garble))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--rad", type=float, default=0.03, help="部首率阈值")
    ap.add_argument("--dup", type=float, default=0.06, help="叠字率阈值")
    a = ap.parse_args()
    manifest = load_manifest(a.out)
    try:
        raw_paths = {
            id(r): safe_join(a.out, r["raw"])
            for r in manifest
            if r.get("quality") in ("text", "sparse") and r.get("raw")
        }
    except ValueError as e:
        sys.exit(f"拒绝不安全的 manifest 路径: {e}")
    fixed = 0
    print(f"{'before':>18}{'after':>14}  文件")
    for r in manifest:
        if r.get("quality") not in ("text", "sparse") or not r.get("raw"):
            continue
        raw_rel = r["raw"]
        if not secure_exists(a.out, raw_rel):
            continue
        t = secure_read_text(a.out, raw_rel)
        if len(HAN_RE.findall(t)) < 50:
            continue
        rad0, dup0 = garble_score(t)
        if rad0 <= a.rad and dup0 <= a.dup:
            continue
        t2 = dedup_repeats(norm_radicals(t))
        rad1, dup1 = garble_score(t2)
        secure_write_text(a.out, raw_rel, t2)
        r["chars"] = len(HAN_RE.findall(t2)); r["garble_fixed"] = True
        fixed += 1
        print(f"  部{rad0*100:4.1f}%叠{dup0*100:4.1f}% -> 部{rad1*100:4.1f}%叠{dup1*100:4.1f}%  {r['name'][:40]}")
    save_manifest(a.out, manifest)
    print(f"\n修复 {fixed} 个乱码文件")

if __name__ == "__main__":
    main()
