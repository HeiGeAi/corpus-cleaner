# -*- coding: utf-8 -*-
"""阶段8: 安全删除原始素材。默认 dry-run(只列不删), 加 --apply 才真删。
默认只删"已完整进库"的(text/sparse, 且 _raw 留档存在)+ skip_duplicate。
图片型/损坏(内容没进库)默认保留; 加 --delete-image 才一并删(确认不要视觉内容时)。
删前逐个验证 _raw 留档存在且非空, 无留档一律保留。
用法: python3 cleanup.py --src <素材包> --out <库> [--apply] [--delete-image]"""
import os, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (load_manifest, save_manifest, rec_key, safe_join,
                    pin_root,
                    secure_file_size, secure_file_stat, secure_listdir,
                    secure_unlink)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--apply", action="store_true", help="真删(否则只预览)")
    ap.add_argument("--delete-image", action="store_true", help="连图片型/损坏一起删(内容会永久丢失)")
    a = ap.parse_args()
    out_root = pin_root(a.out, missing_ok=True)
    src_root = pin_root(a.src, missing_ok=True)
    manifest = load_manifest(out_root)
    if os.path.dirname(os.fspath(src_root)) == os.fspath(src_root):
        sys.exit("拒绝把文件系统根目录作为 --src")
    try:
        source_rels = {id(r): rec_key(r) for r in manifest}
        archive_rels = {
            id(r): r["raw"]
            for r in manifest
            if r.get("raw")
        }
        for r in manifest:
            safe_join(src_root, source_rels[id(r)])
            if id(r) in archive_rels:
                safe_join(out_root, archive_rels[id(r)])
    except ValueError as e:
        sys.exit(f"拒绝不安全的 manifest 路径: {e}")

    to_delete, keep, no_archive = [], [], []
    source_stats = {}
    for r in manifest:
        try:
            source_stats[id(r)] = secure_file_stat(src_root, source_rels[id(r)])
        except FileNotFoundError:
            continue
        q = r.get("quality")
        if q in ("text", "sparse"):
            archive_rel = archive_rels.get(id(r))
            try:
                archive_size = secure_file_size(out_root, archive_rel) if archive_rel else -1
            except FileNotFoundError:
                archive_size = -1
            if archive_size > 10:
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
    delsz = sum(source_stats[id(r)].st_size for r in to_delete)
    keepsz = sum(source_stats[id(r)].st_size for r in keep if id(r) in source_stats)
    print(f"{'[预览]' if not a.apply else '[执行]'} 将删 {len(to_delete)} 个 ({gb(delsz)}), 保留 {len(keep)} 个 ({gb(keepsz)})")
    if no_archive:
        print(f"⚠ 无留档保留不删: {len(no_archive)} 个 -> {no_archive}")
    if not a.apply:
        print("\n这是预览。确认无误后加 --apply 真删。图片型默认保留,加 --delete-image 才删。")
        return
    freed = 0
    try:
        for r in to_delete:
            archive_rel = archive_rels.get(id(r))
            if r.get("quality") in ("text", "sparse"):
                if not archive_rel or secure_file_size(out_root, archive_rel) <= 10:
                    raise RuntimeError(f"删除前复核发现留档缺失或过短: {r['name']}")
            freed += secure_unlink(
                src_root,
                source_rels[id(r)],
                expected=source_stats[id(r)],
            )
            r["original_deleted"] = True
    finally:
        save_manifest(out_root, manifest)   # 统一落盘,finally 保证中断时状态不丢
    try:
        leftover = [f for f in secure_listdir(src_root) if not f.startswith(".")]
    except FileNotFoundError:
        leftover = []
    if a.delete_image and not leftover:
        print("原始目录已空；为避免根目录替换竞态，保留空目录本身")
    print(f"已删 {len(to_delete)} 个, 释放 {gb(freed)}; 原始目录剩 {len(leftover)} 个")

if __name__ == "__main__":
    main()
