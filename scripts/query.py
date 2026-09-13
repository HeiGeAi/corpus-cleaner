# -*- coding: utf-8 -*-
"""两级检索 CLI: 给 agent/人在土壤库里找素材,免手写多轮 grep。
标题/标签/摘要命中加权(粗筛层),正文命中兜底(深读层),综合排序输出候选文件。
用法: python3 query.py --lib <库目录> <关键词> [关键词...] [--cat 类目] [--top 10]
多个关键词按"或"检索、按总分排序;只想精确匹配就给一个词。
输出是候选清单,不替你读文件 —— 命中后按路径深读正文,引用守 SOIL.md 协议。"""
import os, sys, argparse, re

SKIP_TOP = {"INDEX.md", "CATALOG.md", "SOIL.md", "提取质量报告.md"}

def parse_md(path):
    """返回 (front_matter_dict, body)。front matter 解析只取本库生成的简单 key: value。"""
    with open(path, encoding="utf-8", errors="ignore") as fp:
        text = fp.read()
    fm = {}
    body = text
    if text.startswith("---"):
        parts = text.split("\n---", 2)
        if len(parts) >= 2:
            for line in parts[0].splitlines()[1:]:
                if ":" in line:
                    k, v = line.split(":", 1)
                    fm[k.strip()] = v.strip().strip('"')
            body = parts[1] if len(parts) == 2 else parts[1] + parts[2]
    return fm, body

def context_line(body, kw, width=50):
    i = body.lower().find(kw)
    if i < 0:
        return ""
    s = max(0, i - width // 2)
    frag = re.sub(r"\s+", " ", body[s:i + len(kw) + width // 2]).strip()
    return f"…{frag}…"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", required=True, help="土壤库目录")
    ap.add_argument("keywords", nargs="+", help="检索关键词(可多个,或的关系)")
    ap.add_argument("--cat", default=None, help="限定类目目录名")
    ap.add_argument("--top", type=int, default=10)
    a = ap.parse_args()
    kws = [k.lower() for k in a.keywords]

    hits = []
    for root, dirs, files in os.walk(a.lib):
        dirs[:] = [d for d in dirs if not d.startswith((".", "_"))]
        rel_root = os.path.relpath(root, a.lib)
        if a.cat and rel_root != "." and not rel_root.startswith(a.cat):
            continue
        for f in files:
            if not f.endswith(".md") or (rel_root == "." and f in SKIP_TOP):
                continue
            if a.cat and rel_root == ".":
                continue
            p = os.path.join(root, f)
            fm, body = parse_md(p)
            bl = body.lower()
            meta = " ".join([fm.get("title", f), fm.get("tags", ""), fm.get("excerpt", ""),
                             fm.get("source", "")]).lower()
            score, why, ctx = 0, [], ""
            for kw in kws:
                t = fm.get("title", f).lower().count(kw)
                m = meta.count(kw)
                b = min(bl.count(kw), 10)
                score += t * 5 + (m - t if m > t else 0) * 3 + b
                parts = []
                if t: parts.append(f"标题×{t}")
                if m - t > 0: parts.append(f"标签摘要×{m - t}")
                if b:
                    parts.append(f"正文×{bl.count(kw)}")
                    if not ctx:
                        ctx = context_line(body, kw)
                if parts:
                    why.append(f"{kw}({' '.join(parts)})" if len(kws) > 1 else " ".join(parts))
            if score > 0:
                hits.append((score, os.path.relpath(p, a.lib), " ".join(why), ctx,
                             fm.get("quality", "")))

    if not hits:
        print(f"没有命中: {' '.join(a.keywords)}"
              + (f" (类目 {a.cat})" if a.cat else "")
              + "。可换近义词/减字数再试,或如实告知没有此素材。")
        return
    hits.sort(key=lambda x: -x[0])
    print(f"命中 {len(hits)} 个文件,按相关度取前 {min(a.top, len(hits))}:\n")
    for score, path, why, ctx, q in hits[:a.top]:
        tag = f" [{q}]" if q and q != "文字型" else ""
        print(f"[{score:>4}] {path}{tag}")
        print(f"       {why}")
        if ctx:
            print(f"       {ctx}")
    print("\n下一步: 按路径深读候选正文,引用规则见库根目录 SOIL.md。")

if __name__ == "__main__":
    main()
