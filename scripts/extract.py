# -*- coding: utf-8 -*-
"""阶段1+2: 扫描类型分布 + 分层提取文本到 _raw/all/, 写 manifest.json。
用法: python3 extract.py --src <素材包目录> --out <输出库目录>
零成本(无 LLM)。老格式 .ppt 标 needs_conversion 留给 convert_legacy.py。"""
import os, sys, argparse, zipfile, subprocess, re, tempfile, shutil
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import clean, judge_quality, classify, load_manifest, save_manifest, find_soffice

def extract_pdf(p):
    import fitz
    doc = fitz.open(p); n = doc.page_count
    parts = [pg.get_text("text") for pg in doc]
    doc.close()
    full = clean("\n".join(parts)); chars = len(full.strip())
    return full, {"unit": "pages", "count": n, "chars": chars, "quality": judge_quality(chars, n, "pdf")}

def extract_pptx(p):
    from pptx import Presentation
    prs = Presentation(p); parts = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame: parts.append(shape.text_frame.text)
            if shape.has_table:
                for row in shape.table.rows:
                    parts.append("\t".join(c.text for c in row.cells))
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
            parts.append("[备注] " + slide.notes_slide.notes_text_frame.text)
    n = len(prs.slides); full = clean("\n".join(parts)); chars = len(full.strip())
    return full, {"unit": "slides", "count": n, "chars": chars, "quality": judge_quality(chars, n, "pptx")}

def extract_docx(p):
    import docx
    d = docx.Document(p); parts = [par.text for par in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts.append("\t".join(c.text for c in row.cells))
    full = clean("\n".join(parts)); chars = len(full.strip())
    return full, {"unit": "paragraphs", "count": len(d.paragraphs), "chars": chars,
                  "quality": "text" if chars >= 200 else "sparse"}

def extract_doc(p):
    """处理 .doc 老格式 Word。macOS 用 textutil(快),其他平台 fallback 到 LibreOffice。"""
    if sys.platform == "darwin" and shutil.which("textutil"):
        r = subprocess.run(["textutil", "-convert", "txt", "-stdout", p],
                           capture_output=True, timeout=60)
        full = clean(r.stdout.decode("utf-8", "ignore"))
    else:
        soff = find_soffice()
        if not soff:
            raise RuntimeError(".doc 需要 textutil(macOS自带) 或 LibreOffice(其他平台)")
        tmp = tempfile.mkdtemp()
        try:
            subprocess.run([soff, "--headless", "--convert-to", "txt:Text", "--outdir", tmp, p],
                           capture_output=True, timeout=120)
            txt = os.path.join(tmp, os.path.splitext(os.path.basename(p))[0] + ".txt")
            full = clean(open(txt, encoding="utf-8").read()) if os.path.exists(txt) else ""
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    chars = len(full.strip())
    return full, {"unit": "doc", "count": 1, "chars": chars,
                  "quality": "text" if chars >= 200 else "sparse"}

def extract_epub(p):
    z = zipfile.ZipFile(p)
    htmls = sorted(n for n in z.namelist() if n.lower().endswith((".html", ".xhtml", ".htm")))
    parts = []
    for h in htmls:
        raw = z.read(h).decode("utf-8", "ignore")
        raw = re.sub(r"(?is)<(script|style).*?</\1>", "", raw)
        raw = re.sub(r"(?s)<[^>]+>", " ", raw)
        parts.append(re.sub(r"&[a-z]+;", " ", raw))
    full = re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]{2,}", " ", clean("\n".join(parts))))
    return full, {"unit": "chapters", "count": len(htmls), "chars": len(full.strip()), "quality": "text"}

EXTRACTORS = {".pdf": extract_pdf, ".pptx": extract_pptx, ".docx": extract_docx,
              ".doc": extract_doc, ".epub": extract_epub}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    RAW = os.path.join(a.out, "_raw", "all"); os.makedirs(RAW, exist_ok=True)

    files = sorted(f for f in os.listdir(a.src)
                   if not f.startswith(".") and os.path.isfile(os.path.join(a.src, f)))
    by_ext = Counter(os.path.splitext(f)[1].lower() for f in files)
    print("=== 类型分布 ===")
    for ext, n in by_ext.most_common():
        print(f"  {ext or '(无)'}: {n}")
    # epub/mobi 去重: 同名 epub 在则 mobi skip
    epub_bases = {os.path.splitext(f)[0] for f in files if f.lower().endswith(".epub")}

    manifest = []
    done = 0
    for fn in files:
        ext = os.path.splitext(fn)[1].lower()
        p = os.path.join(a.src, fn)
        rec = {"name": fn, "ext": ext, "size": os.path.getsize(p), "category": classify(fn)}
        try:
            if ext == ".ppt":
                rec.update({"quality": "needs_conversion", "note": "老格式PPT,需LibreOffice转换"})
            elif ext == ".mobi":
                if os.path.splitext(fn)[0] in epub_bases:
                    rec.update({"quality": "skip_duplicate", "note": "与epub同书"})
                else:
                    rec.update({"quality": "unsupported", "note": "mobi无epub版,未提取"})
            elif ext in EXTRACTORS:
                full, meta = EXTRACTORS[ext](p)
                rp = os.path.join(RAW, fn + ".txt")
                open(rp, "w", encoding="utf-8").write(full)
                rec.update(meta); rec["raw"] = os.path.relpath(rp, a.out)
            else:
                rec.update({"quality": "unsupported"})
        except Exception as e:
            rec.update({"quality": "failed", "error": f"{type(e).__name__}: {e}"})
            print(f"[FAIL] {fn[:40]}: {e}")
        manifest.append(rec)
        done += 1
        if done % 25 == 0:
            print(f"  ...{done}/{len(files)}")
    save_manifest(a.out, manifest)
    qc = Counter(r.get("quality") for r in manifest)
    print("\n=== 提取完成 ===")
    print("质量分布:", dict(qc))
    print("类目分布:", dict(Counter(r["category"] for r in manifest)))

if __name__ == "__main__":
    main()
