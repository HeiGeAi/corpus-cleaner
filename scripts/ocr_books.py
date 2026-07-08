# -*- coding: utf-8 -*-
"""阶段5: 救回图片型 PDF 里的扫描文字书。
先对每个图片型 PDF 采样几页 OCR, 按识别字数区分: 扫描文字书(高字数,值得全本OCR) vs 纯设计版面(低字数,跳过)。
再对扫描书全本 tesseract OCR(零 token 成本)。
每本 OCR 完立即写盘 manifest —— 全本 OCR 是小时级任务,中断后重跑会自动跳过已完成的书,断点续跑。
用法: python3 ocr_books.py --src <素材包> --out <库> [--threshold 150] [--dpi 150]
依赖: brew install tesseract tesseract-lang"""
import os, sys, argparse, subprocess, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import clean, load_manifest, save_manifest, rec_key, flat_name, require_tool

def ocr_page(doc, i, dpi, lang):
    pix = doc[i].get_pixmap(dpi=dpi)
    tf = tempfile.NamedTemporaryFile(suffix=".png", delete=False); png = tf.name; tf.close()
    pix.save(png)
    r = subprocess.run(["tesseract", png, "stdout", "-l", lang, "--psm", "3"], capture_output=True)
    os.remove(png)
    return clean(r.stdout.decode("utf-8", "ignore").strip())

def main():
    import fitz
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--threshold", type=int, default=150, help="采样均字数>=此值判为扫描书")
    ap.add_argument("--dpi", type=int, default=150)
    ap.add_argument("--lang", default="chi_sim+chi_tra")
    a = ap.parse_args()
    require_tool("tesseract",
                 "装: macOS `brew install tesseract tesseract-lang` / "
                 "Linux `apt install tesseract-ocr tesseract-ocr-chi-sim tesseract-ocr-chi-tra` / "
                 "Windows 从 github.com/UB-Mannheim/tesseract/wiki 下载")
    RAW = os.path.join(a.out, "_raw", "all"); os.makedirs(RAW, exist_ok=True)
    manifest = load_manifest(a.out)
    imgs = [r for r in manifest if r.get("quality") == "image" and r.get("ext") == ".pdf"
            and not r.get("ocr")]
    print(f"图片型 PDF {len(imgs)} 个, 采样判定扫描书...")
    books, missing = [], 0
    for r in imgs:
        p = os.path.join(a.src, rec_key(r))
        if not os.path.exists(p):
            missing += 1; continue
        try:
            doc = fitz.open(p); n = doc.page_count
            sample = sorted(set([min(2, n-1), n//5, n//2, n*4//5]))
            avg = sum(len(ocr_page(doc, i, a.dpi, "chi_sim")) for i in sample) / len(sample)
            doc.close()
            if avg >= a.threshold:
                books.append(r)
                print(f"  [书] {round(avg)}字/页 {n}页  {r['name'][:46]}")
        except Exception as e:
            print(f"  [err] {r['name'][:40]}: {e}")
    if missing:
        print(f"  (原始文件已不在 src 的跳过 {missing} 个)")
    print(f"\n判为扫描文字书: {len(books)} 个, 全本 OCR 中(每本完成即写盘,中断可续)...")
    done = 0
    for idx, r in enumerate(books, 1):
        try:
            doc = fitz.open(os.path.join(a.src, rec_key(r))); n = doc.page_count
            parts = [ocr_page(doc, i, a.dpi, a.lang) for i in range(n)]
            doc.close()
        except Exception as e:
            print(f"  [err] {r['name'][:40]}: {e}"); continue
        full = "\n\n".join(parts); chars = len(full.replace("\n", "").strip())
        rp = os.path.join(RAW, flat_name(rec_key(r)) + ".txt")
        open(rp, "w", encoding="utf-8").write(full)
        r.update({"chars": chars, "quality": "text", "ocr": True, "count": n,
                  "raw": os.path.relpath(rp, a.out)})
        save_manifest(a.out, manifest)   # 逐本落盘,断点续跑的关键
        done += 1
        print(f"  [{idx}/{len(books)}] {chars}字 {n}页  {r['name'][:44]}")
    print(f"\nOCR 转正 {done} 本扫描书。下一步: build.py 重建库")

if __name__ == "__main__":
    main()
