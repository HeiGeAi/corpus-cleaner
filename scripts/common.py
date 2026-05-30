# -*- coding: utf-8 -*-
"""共享逻辑: 文本清洗、质量判定、分类规则、文件名安全化。
分类规则按内容领域调整 —— 默认是营销/文案素材的分类,换领域时改 CATEGORY_RULES 和 SUBCATEGORY_RULES 即可。"""
import os, re, json

# ---------- 文本清洗 ----------
def clean(s):
    """去替换字符和控制字符,保留换行/制表。"""
    if not s:
        return ""
    s = str(s).replace("�", "").replace("￿", "")
    return "".join(ch for ch in s if ch in "\n\t" or ord(ch) >= 32)

# ---------- 质量判定阈值 ----------
# PDF/PPT 按 平均字符/页 判定: 高=文字型可直接用, 中=稀疏, 低=图片型(内容在图里)
def judge_quality(chars, units, kind="pdf"):
    avg = chars / units if units else 0
    if kind == "pptx":
        hi, lo = 60, 12
    else:  # pdf
        hi, lo = 80, 15
    if avg >= hi:
        return "text"
    if avg >= lo:
        return "sparse"
    return "image"

# ---------- 分类规则(按领域调整) ----------
CATEGORY_RULES = [
    ("文案珍藏", ["文案", "金句", "slogan", "珍藏", "经典", "合集", "apple", "iphone",
               "无印良品", "掌生谷粒", "东东枪", "基本修养", "数英", "奥美", "文案的"]),
    ("品牌手册", ["品牌手册", "vi手册", "视觉规范", "品牌规范", "brandbook", "品牌全案", "品牌手冊"]),
    ("平台运营", ["小红书", "抖音", "直播", "视频号", "b站", "快手", "私域", "种草",
               "运营", "达人", "kol", "投放", "公众号", "社媒"]),
    ("行业报告", ["报告", "洞察", "趋势", "白皮书", "蓝皮书", "研究", "数据", "榜", "分析", "日历"]),
    ("营销策划", ["策划", "全案", "campaign", "方案", "营销", "推广", "活动", "传播",
               "策略", "brief", "提案", "创意", "培训", "作品集"]),
]
# 大类内的二级分类(只对命中的大类生效,默认对“营销策划”)
SUBCATEGORY_FOR = "营销策划"
SUBCATEGORY_RULES = [
    ("作品集", ["作品集", "案例集"]),
    ("培训教程", ["培训", "教程", "方法论", "技巧", "怎么写", "如何写", "入门", "创意培训",
               "修辞法", "炼成", "论语", "之道", "可延展", "创意课", "思维模型", "创造概念",
               "copy book", "french", "法兰奇", "广告语法", "顶尖文案", "顶尖广告"]),
    ("节日营销", ["cny", "春节", "新年", "妇女节", "女神节", "三八", "618", "双11", "双十一",
               "中秋", "七夕", "圣诞", "情人节", "母亲节", "父亲节", "国庆", "元宵", "520",
               "年货", "新春", "开学", "万圣"]),
    ("活动策划", ["音乐节", "快闪", "发布会", "市集", "launch", "活动", "盛典", "嘉年华",
               "巡展", "周年", "画展", "酒水节", "露营", "奥运"]),
    ("4A提案", ["4a", "提案", "比稿", "jwt", "ddb", "奥美", "havas", "恒美", "智威汤逊",
              "tbwa", "karma", "grey", "精信", "传播方案", "传播策略", "campaign",
              "创意策略", "脚本", "tvc"]),
]
DEFAULT_SUBCATEGORY = "品牌综合方案"
DEFAULT_CATEGORY = "其他"

def classify(name):
    nl = name.lower()
    for label, kws in CATEGORY_RULES:
        if any(k in nl for k in kws):
            return label
    return DEFAULT_CATEGORY

def subcategory(name):
    nl = name.lower()
    for label, kws in SUBCATEGORY_RULES:
        if any(k in nl for k in kws):
            return label
    return DEFAULT_SUBCATEGORY

# ---------- 文件名安全化(做 .md 文件名) ----------
def safe_md(name):
    return os.path.splitext(name)[0].replace("/", "／") + ".md"

# ---------- manifest 读写 ----------
def load_manifest(out_dir):
    p = os.path.join(out_dir, "manifest.json")
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else []

def save_manifest(out_dir, manifest):
    json.dump(manifest, open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

# ---------- 乱码检测(康熙部首区 + 相邻叠字) ----------
RADICAL_RE = re.compile(r"[⺀-⻿⼀-⿟]")
HAN_RE = re.compile(r"[一-鿿]")

def garble_score(text):
    """返回 (部首率, 叠字率)。高 = 字体映射坏的乱码。"""
    hl = HAN_RE.findall(text)
    nh = len(hl) or 1
    dup = sum(1 for i in range(1, len(hl)) if hl[i] == hl[i-1]) / nh
    rad = len(RADICAL_RE.findall(text)) / nh
    return rad, dup

# ---------- 跨平台: 工具路径检测 ----------
def find_soffice():
    """跨平台查找 LibreOffice 可执行文件,找不到返回 None。"""
    import shutil, sys
    p = shutil.which("soffice") or shutil.which("libreoffice")
    if p:
        return p
    candidates = {
        "darwin": ["/Applications/LibreOffice.app/Contents/MacOS/soffice"],
        "linux": ["/usr/bin/soffice", "/usr/bin/libreoffice", "/snap/bin/libreoffice"],
        "win32": [r"C:\Program Files\LibreOffice\program\soffice.exe",
                  r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"],
    }
    for c in candidates.get(sys.platform, []):
        if os.path.exists(c):
            return c
    return None

def require_tool(name, install_hint):
    """断言系统命令存在,缺则给出多平台安装提示。"""
    import shutil
    if not shutil.which(name):
        raise SystemExit(f"未找到 {name}。{install_hint}")
