# -*- coding: utf-8 -*-
"""阶段8: 安全删除原始素材。默认 dry-run(只列不删), 加 --apply 才真删。
默认只删"已完整进库"的(text/sparse, 且 _raw 留档存在)+ skip_duplicate。
图片型/损坏(内容没进库)默认保留; 加 --delete-image 才一并删(确认不要视觉内容时)。
删前逐个验证 _raw 留档存在且非空, 无留档一律保留。
用法: python3 cleanup.py --src <素材包> --out <库> [--apply] [--delete-image]"""
import os, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import load_manifest, save_manifest

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--apply", action="store_true", help="真删(否则只预览)")
    ap.add_argument("--delete-image", action="store_true", help="连图片型/损坏一起删(内容会永久丢失)")
    a = ap.parse_args()
    manifest = load_manifest(a.out)
    to_delete, keep, no_archive = [], [], []
    for r in manifest:
        src = os.path.join(a.src, r["name"])
        if not os.path.exists(src):
            continue
        q = r.get("quality")
        if q in ("text", "sparse"):
            rp = r.get("raw"); full = os.path.join(a.out, rp) if rp else None
            if full and os.path.exists(full) and os.path.getsize(full) > 10:
                to_delete.append(r)
            else:
                no_archive.append(r["name"])  # 没留档 -> 不删
        elif q == "skip_duplicate":
            to_delete.append(r)
        elif q in ("image", "failed"):
            (to_delete if a.delete_image else keep).append(r)
        else:
            keep.append(r)

    def gb(b): return f"{b/1024/1024/1024:.2f}GB" if b > 1e9 else f"{b/1024/1024:.0f}MB"
    delsz = sum(os.path.getsize(os.path.join(a.src, r["name"])) for r in to_delete)
    keepsz = sum(os.path.getsize(os.path.join(a.src, r["name"])) for r in keep if os.path.exists(os.path.join(a.src, r["name"])))
    print(f"{'[预览]' if not a.apply else '[执行]'} 将删 {len(to_delete)} 个 ({gb(delsz)}), 保留 {len(keep)} 个 ({gb(keepsz)})")
    if no_archive:
        print(f"⚠ 无留档保留不删: {len(no_archive)} 个 -> {no_archive}")
    if not a.apply:
        print("\n这是预览。确认无误后加 --apply 真删。图片型默认保留,加 --delete-image 才删。")
        return
    freed = 0
    for r in to_delete:
        p = os.path.join(a.src, r["name"]); freed += os.path.getsize(p); os.remove(p)
        r["original_deleted"] = True
    save_manifest(a.out, manifest)
    leftover = [f for f in os.listdir(a.src) if not f.startswith(".")] if os.path.exists(a.src) else []
    if a.delete_image and os.path.exists(a.src) and not leftover:
        import shutil; shutil.rmtree(a.src); print("原始目录已空,已删除")
    print(f"已删 {len(to_delete)} 个, 释放 {gb(freed)}; 原始目录剩 {len(leftover)} 个")

if __name__ == "__main__":
    main()
