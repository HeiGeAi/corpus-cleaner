# -*- coding: utf-8 -*-
"""共享逻辑: 文本清洗、质量判定、分类规则、manifest 增量合并、文件名安全化、摘要关键词。
分类规则按内容领域调整 —— 默认是营销/文案素材的分类,换领域时改 CATEGORY_RULES 和 SUBCATEGORY_RULES 即可。"""
import hashlib
import json
import os
import re
import secrets
import stat

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

# ---------- 文件标识与命名 ----------
def rec_key(rec):
    """manifest 记录的唯一键。新记录用相对路径 rel,老记录(v0.1)只有 name,兼容两代。"""
    return rec.get("rel") or rec.get("name")

def flat_name(rel):
    """把相对路径压平成 _raw 下的安全文件名: 子目录/文件.pdf -> 子目录__文件.pdf"""
    return rel.replace(os.sep, "__").replace("/", "__")


def bounded_filename(stem, suffix, identity, max_bytes=220):
    """按 UTF-8 字节数限制单个文件名,超长时保留稳定哈希。"""
    candidate = stem + suffix
    if len(candidate.encode("utf-8")) <= max_bytes:
        return candidate
    digest = hashlib.sha256(str(identity).encode("utf-8")).hexdigest()[:12]
    tail = "." + digest + suffix
    budget = max_bytes - len(tail.encode("utf-8"))
    prefix = stem.encode("utf-8")[:max(1, budget)].decode("utf-8", "ignore").rstrip(" .")
    return (prefix or "file") + tail


def raw_filename(rel):
    """所有提取/转换/OCR 阶段共用的确定性 raw 文件名。"""
    normalized = str(rel).replace("\\", "/")
    flat = flat_name(normalized)
    if "/" in normalized:
        flat += "." + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:10]
    return bounded_filename(flat, ".txt", normalized)


def safe_join(root, relative):
    """把 manifest 里的相对路径限制在指定根目录内。

    与 openat 安全操作共用同一套组件解析，再用 realpath 防指向根目录外的符号链接。
    候选路径不允许等于根目录本身，避免删除型调用误操作整个根。
    """
    root_real = os.path.realpath(os.path.abspath(root))
    parts = _relative_parts(relative)
    candidate = os.path.realpath(os.path.join(root_real, *parts))
    try:
        contained = os.path.commonpath([root_real, candidate]) == root_real
    except ValueError:
        contained = False
    if not contained or candidate == root_real:
        raise ValueError(f"路径越界或指向根目录: {relative!r}")
    return candidate


# ---------- 抗目录替换的文件操作 ----------
def _relative_parts(relative, allow_empty=False):
    """把外部相对路径拆成可供 openat 使用的组件。"""
    rel = os.fspath(relative or "")
    if "\x00" in rel:
        raise ValueError(f"路径包含空字符: {relative!r}")
    normalized = rel.replace("\\", "/")
    if (normalized.startswith("/") or normalized.startswith("//")
            or re.match(r"^[A-Za-z]:", normalized)):
        raise ValueError(f"路径越界或指向根目录: {relative!r}")
    if not normalized:
        if allow_empty:
            return []
        raise ValueError(f"路径越界或指向根目录: {relative!r}")
    parts = normalized.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"路径越界或包含歧义组件: {relative!r}")
    return parts


def _require_dir_fd_support():
    """安全写删必须有 openat 系列能力；缺失时宁可拒绝而不做竞态回退。"""
    required = (os.open, os.stat, os.mkdir, os.unlink, os.rename, os.rmdir)
    missing = [fn.__name__ for fn in required if fn not in os.supports_dir_fd]
    if (missing or not hasattr(os, "O_NOFOLLOW")
            or not hasattr(os, "O_DIRECTORY")):
        detail = ", ".join(missing) or "O_NOFOLLOW/O_DIRECTORY"
        raise RuntimeError(f"当前平台缺少安全目录操作能力: {detail}")


def _dir_flags():
    return (os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0))


def _open_root_fd(root, create=False):
    """打开根目录本身，拒绝已解析路径中的符号链接。"""
    _require_dir_fd_support()
    root_abs = os.path.abspath(os.fspath(root))
    # macOS 的 /var、/tmp 等系统路径本身是符号链接，先固定其真实前缀，
    # 再逐级用 O_NOFOLLOW 打开，避免受控路径组件在检查后被替换。
    root_real = os.path.realpath(root_abs)
    if not os.path.isabs(root_real):
        raise ValueError(f"根目录必须是绝对路径: {root!r}")
    parts = [part for part in root_real.split(os.sep) if part]
    fd = os.open(os.sep, _dir_flags())
    try:
        for part in parts:
            try:
                child = os.open(part, _dir_flags(), dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, dir_fd=fd)
                child = os.open(part, _dir_flags(), dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except Exception:
        os.close(fd)
        raise


def _open_dir_fd(root, relative="", create=False):
    """从根目录句柄逐级打开子目录，整个遍历过程不跟随符号链接。"""
    parts = _relative_parts(relative, allow_empty=True)
    fd = _open_root_fd(root, create=create)
    try:
        for part in parts:
            try:
                child = os.open(part, _dir_flags(), dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, dir_fd=fd)
                child = os.open(part, _dir_flags(), dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except Exception:
        os.close(fd)
        raise


def _open_parent_fd(root, relative, create=False):
    """返回目标父目录句柄、末级文件名和父目录相对路径。"""
    parts = _relative_parts(relative)
    parent_parts = parts[:-1]
    parent_rel = "/".join(parent_parts)
    return _open_dir_fd(root, parent_rel, create=create), parts[-1], parent_rel


def _same_object(left, right):
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _same_snapshot(left, right):
    """比较预检时的文件身份与内容元数据，避免同 inode 内容被换掉。"""
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    return all(getattr(left, field) == getattr(right, field) for field in fields)


def _assert_parent_stable(root, parent_relative, parent_fd):
    """确认调用方看到的父目录路径仍指向已打开的同一个目录。"""
    check_fd = _open_dir_fd(root, parent_relative, create=False)
    try:
        if not _same_object(os.fstat(parent_fd), os.fstat(check_fd)):
            raise RuntimeError("目标父目录在操作期间被替换")
    finally:
        os.close(check_fd)


def _lstat_at(parent_fd, name):
    return os.stat(name, dir_fd=parent_fd, follow_symlinks=False)


def _open_metadata_fd(parent_fd, name):
    """不要求读权限地打开文件身份句柄，供 fstat、改名和删除校验使用。"""
    base = os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    access_modes = []
    for flag_name in ("O_PATH", "O_EVTONLY"):
        flag = getattr(os, flag_name, None)
        if flag is not None:
            access_modes.append(flag)
    access_modes.extend((os.O_RDONLY, os.O_WRONLY))
    last_permission_error = None
    for access in access_modes:
        try:
            return os.open(name, access | base, dir_fd=parent_fd)
        except PermissionError as exc:
            last_permission_error = exc
    if last_permission_error is not None:
        raise last_permission_error
    raise PermissionError(f"无法打开文件身份句柄: {name!r}")


_STAGE_PAYLOAD = "payload"


def _create_staging_dir(parent_fd):
    """在目标父目录内创建仅当前用户可进入的临时工作目录并返回其 fd。"""
    for _ in range(32):
        name = f".corpus-stage-{os.getpid()}-{secrets.token_hex(12)}"
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
        except FileExistsError:
            continue
        created = None
        stage_fd = None
        opened = None
        try:
            created = _lstat_at(parent_fd, name)
            stage_fd = os.open(name, _dir_flags(), dir_fd=parent_fd)
            opened = os.fstat(stage_fd)
            if not stat.S_ISDIR(created.st_mode) or not _same_object(created, opened):
                raise RuntimeError("私有暂存目录在打开期间被替换")
            os.fchmod(stage_fd, 0o700)
            outer = _lstat_at(parent_fd, name)
            if not stat.S_ISDIR(outer.st_mode) or not _same_object(outer, opened):
                raise RuntimeError("私有暂存目录在创建期间被替换")
            return name, stage_fd
        except Exception:
            identity = opened or created
            try:
                current = _lstat_at(parent_fd, name)
                empty = stage_fd is None or not os.listdir(stage_fd)
                if (identity is not None and empty and stat.S_ISDIR(current.st_mode)
                        and _same_object(identity, current)):
                    os.rmdir(name, dir_fd=parent_fd)
            except (FileNotFoundError, OSError):
                pass
            if stage_fd is not None:
                os.close(stage_fd)
            raise
    raise FileExistsError("无法创建唯一的私有暂存目录")


def _remove_staging_dir(parent_fd, stage_name, stage_fd):
    """只在外层名字仍对应已打开的空暂存目录时移除它。"""
    try:
        if os.listdir(stage_fd):
            return False
        outer = _lstat_at(parent_fd, stage_name)
        if not stat.S_ISDIR(outer.st_mode) or not _same_object(outer, os.fstat(stage_fd)):
            return False
        os.rmdir(stage_name, dir_fd=parent_fd)
        return True
    except OSError:
        return False


def secure_makedirs(root, relative):
    """在 root 内创建目录，且不跟随任一相对路径符号链接。"""
    fd = _open_dir_fd(root, relative, create=True)
    try:
        parent = "/".join(_relative_parts(relative))
        _assert_parent_stable(root, parent, fd)
    finally:
        os.close(fd)


def secure_write_text(root, relative, text, encoding="utf-8", create_parent=False):
    """从私有暂存目录原子写入文本，拒绝目录或临时载荷替换。"""
    parent_fd, name, parent_rel = _open_parent_fd(root, relative, create=create_parent)
    stage_name = None
    stage_fd = None
    file_fd = None
    staged = False
    committed = False
    verified = False
    created_stat = None
    existing_mode = None
    try:
        _assert_parent_stable(root, parent_rel, parent_fd)
        existing_fd = None
        try:
            existing = _lstat_at(parent_fd, name)
            if not stat.S_ISREG(existing.st_mode):
                raise ValueError(f"拒绝覆盖非普通文件: {relative!r}")
            existing_fd = _open_metadata_fd(parent_fd, name)
            opened_existing = os.fstat(existing_fd)
            if not _same_object(existing, opened_existing):
                raise RuntimeError("现有目标在读取权限期间被替换")
            existing_mode = stat.S_IMODE(opened_existing.st_mode)
        except FileNotFoundError:
            pass
        finally:
            if existing_fd is not None:
                os.close(existing_fd)
        stage_name, stage_fd = _create_staging_dir(parent_fd)
        flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                 | getattr(os, "O_CLOEXEC", 0))
        file_fd = os.open(_STAGE_PAYLOAD, flags, 0o666, dir_fd=stage_fd)
        staged = True
        if existing_mode is not None:
            os.fchmod(file_fd, existing_mode)
        payload = str(text).encode(encoding)
        view = memoryview(payload)
        while view:
            written = os.write(file_fd, view)
            if written <= 0:
                raise OSError("写入临时文件失败")
            view = view[written:]
        os.fsync(file_fd)
        created_stat = os.fstat(file_fd)
        _assert_parent_stable(root, parent_rel, parent_fd)
        staged_stat = _lstat_at(stage_fd, _STAGE_PAYLOAD)
        if not stat.S_ISREG(staged_stat.st_mode) or not _same_object(created_stat, staged_stat):
            raise RuntimeError("私有暂存载荷身份不一致")
        os.rename(_STAGE_PAYLOAD, name, src_dir_fd=stage_fd, dst_dir_fd=parent_fd)
        staged = False
        committed = True
        named_stat = _lstat_at(parent_fd, name)
        if not stat.S_ISREG(named_stat.st_mode) or not _same_object(created_stat, named_stat):
            raise RuntimeError("原子写入后的目标身份不一致")
        _assert_parent_stable(root, parent_rel, parent_fd)
        verified = True
        _remove_staging_dir(parent_fd, stage_name, stage_fd)
    except Exception:
        if staged and stage_fd is not None:
            try:
                current = _lstat_at(stage_fd, _STAGE_PAYLOAD)
                if created_stat is None or _same_object(created_stat, current):
                    os.unlink(_STAGE_PAYLOAD, dir_fd=stage_fd)
            except FileNotFoundError:
                pass
        if committed and not verified:
            try:
                current = _lstat_at(parent_fd, name)
                if created_stat is not None and _same_object(created_stat, current):
                    os.unlink(name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        if stage_fd is not None:
            _remove_staging_dir(parent_fd, stage_name, stage_fd)
        raise
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if stage_fd is not None:
            os.close(stage_fd)
        os.close(parent_fd)


def secure_read_text(root, relative, encoding="utf-8", errors="strict"):
    """通过父目录句柄读取普通文件，不跟随末级或中间符号链接。"""
    parent_fd, name, parent_rel = _open_parent_fd(root, relative, create=False)
    file_fd = None
    try:
        _assert_parent_stable(root, parent_rel, parent_fd)
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        file_fd = os.open(name, flags, dir_fd=parent_fd)
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"目标不是普通文件: {relative!r}")
        _assert_parent_stable(root, parent_rel, parent_fd)
        chunks = []
        while True:
            chunk = os.read(file_fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        _assert_parent_stable(root, parent_rel, parent_fd)
        return b"".join(chunks).decode(encoding, errors)
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(parent_fd)


def secure_file_stat(root, relative):
    """返回 root 内普通文件的 fstat 结果。"""
    parent_fd, name, parent_rel = _open_parent_fd(root, relative, create=False)
    file_fd = None
    try:
        _assert_parent_stable(root, parent_rel, parent_fd)
        file_fd = _open_metadata_fd(parent_fd, name)
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"目标不是普通文件: {relative!r}")
        _assert_parent_stable(root, parent_rel, parent_fd)
        return info
    finally:
        if file_fd is not None:
            os.close(file_fd)
        os.close(parent_fd)


def secure_file_size(root, relative):
    return secure_file_stat(root, relative).st_size


def secure_exists(root, relative):
    """仅在 root 内普通文件安全存在时返回 True；符号链接仍作为错误拒绝。"""
    try:
        secure_file_stat(root, relative)
        return True
    except (FileNotFoundError, NotADirectoryError):
        return False


def secure_is_dir(root, relative):
    try:
        fd = _open_dir_fd(root, relative, create=False)
    except (FileNotFoundError, NotADirectoryError):
        return False
    try:
        _assert_parent_stable(root, "/".join(_relative_parts(relative)), fd)
        return True
    finally:
        os.close(fd)


def secure_listdir(root, relative=""):
    """列出安全打开的目录；目录路径发生替换时拒绝返回结果。"""
    fd = _open_dir_fd(root, relative, create=False)
    try:
        normalized = "/".join(_relative_parts(relative, allow_empty=True))
        _assert_parent_stable(root, normalized, fd)
        names = os.listdir(fd)
        _assert_parent_stable(root, normalized, fd)
        return names
    finally:
        os.close(fd)


def _restore_staged_payload(parent_fd, stage_fd, name, expected):
    try:
        current = _lstat_at(stage_fd, _STAGE_PAYLOAD)
        try:
            _lstat_at(parent_fd, name)
            return False
        except FileNotFoundError:
            pass
        if _same_object(current, expected):
            os.rename(_STAGE_PAYLOAD, name, src_dir_fd=stage_fd, dst_dir_fd=parent_fd)
            return True
    except OSError:
        return False
    return False


def _clear_directory_fd(directory_fd):
    """只通过已打开的目录句柄清空其内容，不重新解析目录根路径。"""
    for name in os.listdir(directory_fd):
        info = _lstat_at(directory_fd, name)
        if stat.S_ISDIR(info.st_mode):
            child_fd = os.open(name, _dir_flags(), dir_fd=directory_fd)
            try:
                child_info = os.fstat(child_fd)
                if not _same_object(info, child_info):
                    raise RuntimeError(f"子目录在打开期间被替换: {name!r}")
                _clear_directory_fd(child_fd)
                current = _lstat_at(directory_fd, name)
                if not stat.S_ISDIR(current.st_mode) or not _same_object(child_info, current):
                    raise RuntimeError(f"子目录在清理期间被替换: {name!r}")
                os.rmdir(name, dir_fd=directory_fd)
            finally:
                os.close(child_fd)
        else:
            # 符号链接和其他非目录条目只删除目录项，不跟随到目标。
            os.unlink(name, dir_fd=directory_fd)


def secure_rmtree(root, relative, missing_ok=True):
    """删除 root 内指定目录，目录内容始终锚定在已验证的目标 fd 上。"""
    try:
        parent_fd, name, parent_rel = _open_parent_fd(root, relative, create=False)
    except (FileNotFoundError, NotADirectoryError):
        if missing_ok:
            return False
        raise
    target_fd = None
    stage_name = None
    stage_fd = None
    moved = False
    target_stat = None
    original_mode = None
    try:
        _assert_parent_stable(root, parent_rel, parent_fd)
        try:
            initial = _lstat_at(parent_fd, name)
        except FileNotFoundError:
            if missing_ok:
                return False
            raise
        if not stat.S_ISDIR(initial.st_mode) or stat.S_ISLNK(initial.st_mode):
            raise ValueError(f"拒绝删除非普通目录: {relative!r}")
        target_fd = os.open(name, _dir_flags(), dir_fd=parent_fd)
        target_stat = os.fstat(target_fd)
        if not _same_object(initial, target_stat):
            raise RuntimeError("待删目录在打开期间被替换")
        original_mode = stat.S_IMODE(target_stat.st_mode)
        stage_name, stage_fd = _create_staging_dir(parent_fd)
        _assert_parent_stable(root, parent_rel, parent_fd)
        os.rename(name, _STAGE_PAYLOAD, src_dir_fd=parent_fd, dst_dir_fd=stage_fd)
        moved = True
        staged = _lstat_at(stage_fd, _STAGE_PAYLOAD)
        if not stat.S_ISDIR(staged.st_mode) or not _same_object(target_stat, staged):
            raise RuntimeError("待删目录在隔离期间被替换")
        os.fchmod(target_fd, 0o700)
        _clear_directory_fd(target_fd)
        staged = _lstat_at(stage_fd, _STAGE_PAYLOAD)
        if not stat.S_ISDIR(staged.st_mode) or not _same_object(target_stat, staged):
            raise RuntimeError("待删目录在最终移除前被替换")
        os.rmdir(_STAGE_PAYLOAD, dir_fd=stage_fd)
        moved = False
        _remove_staging_dir(parent_fd, stage_name, stage_fd)
        return True
    except Exception:
        if moved and target_stat is not None and stage_fd is not None:
            if original_mode is not None and target_fd is not None:
                try:
                    os.fchmod(target_fd, original_mode)
                except OSError:
                    pass
            _restore_staged_payload(parent_fd, stage_fd, name, target_stat)
        if stage_fd is not None:
            _remove_staging_dir(parent_fd, stage_name, stage_fd)
        raise
    finally:
        if target_fd is not None:
            os.close(target_fd)
        if stage_fd is not None:
            os.close(stage_fd)
        os.close(parent_fd)


def secure_unlink(root, relative, expected=None):
    """删除 root 内指定普通文件，可用先前 fstat 约束文件身份。"""
    parent_fd, name, parent_rel = _open_parent_fd(root, relative, create=False)
    file_fd = None
    stage_name = None
    stage_fd = None
    moved = False
    target_stat = None
    try:
        _assert_parent_stable(root, parent_rel, parent_fd)
        initial = _lstat_at(parent_fd, name)
        if not stat.S_ISREG(initial.st_mode):
            raise ValueError(f"拒绝删除非普通文件: {relative!r}")
        file_fd = _open_metadata_fd(parent_fd, name)
        target_stat = os.fstat(file_fd)
        if not _same_object(initial, target_stat):
            raise RuntimeError("待删文件在打开期间被替换")
        if expected is not None and not _same_snapshot(expected, target_stat):
            raise RuntimeError("待删文件与预检时的身份或内容不一致")
        stage_name, stage_fd = _create_staging_dir(parent_fd)
        _assert_parent_stable(root, parent_rel, parent_fd)
        os.rename(name, _STAGE_PAYLOAD, src_dir_fd=parent_fd, dst_dir_fd=stage_fd)
        moved = True
        staged = _lstat_at(stage_fd, _STAGE_PAYLOAD)
        if not stat.S_ISREG(staged.st_mode) or not _same_object(target_stat, staged):
            raise RuntimeError("待删文件在隔离期间被替换")
        os.unlink(_STAGE_PAYLOAD, dir_fd=stage_fd)
        moved = False
        remaining_links = os.fstat(file_fd).st_nlink
        if remaining_links != max(0, target_stat.st_nlink - 1):
            raise RuntimeError("最终删除的目录项不是已验证的待删文件")
        _remove_staging_dir(parent_fd, stage_name, stage_fd)
        return target_stat.st_size if remaining_links == 0 else 0
    except Exception:
        if moved and target_stat is not None and stage_fd is not None:
            _restore_staged_payload(parent_fd, stage_fd, name, target_stat)
        if stage_fd is not None:
            _remove_staging_dir(parent_fd, stage_name, stage_fd)
        raise
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if stage_fd is not None:
            os.close(stage_fd)
        os.close(parent_fd)

def safe_md(rec):
    """生成不会因相对路径撞名的 .md 文件名。

    顶层新记录保持现有名称，嵌套路径加可读的压平前缀和短哈希。
    老记录(无 rel 且历史库已按旧规则命名)继续保持旧名。
    """
    rel = rec.get("rel") if isinstance(rec, dict) else None
    normalized_rel = rel.replace("\\", "/") if rel else None
    raw_name = rec["name"] if isinstance(rec, dict) else rec
    name = flat_name(normalized_rel) if normalized_rel and "/" in normalized_rel else os.path.basename(
        str(raw_name).replace("\\", "/")
    )
    base, ext = os.path.splitext(name)
    base = base.replace("/", "／")
    if isinstance(rec, dict) and not rel:
        return bounded_filename(base, ".md", raw_name)          # v0.1 老库兼容
    stem = f"{base}.{ext.lstrip('.')}" if ext else base
    if normalized_rel and "/" in normalized_rel:
        digest = hashlib.sha256(normalized_rel.encode("utf-8")).hexdigest()[:10]
        stem = f"{stem}.{digest}"
    return bounded_filename(stem, ".md", normalized_rel or raw_name)

# ---------- manifest 读写与增量合并 ----------
def load_manifest(out_dir):
    if not secure_exists(out_dir, "manifest.json"):
        return []
    return json.loads(secure_read_text(out_dir, "manifest.json"))

def save_manifest(out_dir, manifest):
    secure_write_text(
        out_dir,
        "manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=1),
        create_parent=True,
    )

def manifest_index(manifest):
    """key -> 记录 的索引,用于增量合并。"""
    return {rec_key(r): r for r in manifest}

# 这些质量态代表"上次没成功/没处理",重跑 extract 时值得再试一次
RETRYABLE = {"failed", "unsupported", "needs_conversion"}
# 这些状态是后续阶段(OCR/转换/修复)辛苦挣来的,增量重跑绝不能覆盖
def is_settled(rec, out_dir):
    """记录是否已妥善处理过: 提取物在库里且质量态不属于可重试。"""
    q = rec.get("quality")
    if q in RETRYABLE or q is None:
        return False
    if q in ("text", "sparse"):
        rp = rec.get("raw")
        return bool(rp) and secure_exists(out_dir, rp)
    return True   # image / skip_duplicate 等判定型状态,无需重算

# ---------- front matter 安全值 ----------
_FM_UNSAFE = re.compile(r'[:#\[\]{}"\'\n|>&%@`*!,]')
def fm_value(v):
    """YAML front matter 值转义: 含特殊字符就用 JSON 字符串(合法 YAML 双引号形式)。"""
    s = str(v)
    if s == "" or _FM_UNSAFE.search(s) or s.strip() != s:
        return json.dumps(s, ensure_ascii=False)
    return s

# ---------- 摘要与关键词(零 token,给粗筛层用) ----------
_STOP_CH = set("的了是在和有不我你他她它们个这那与就都而及等或被把对从到于会能可要也很更最还只")
_STOP_W2 = {"如何", "因为", "所以", "什么", "时候", "已经", "现在", "知道", "觉得", "没有",
            "然后", "但是", "如果", "这样", "那样", "一一", "一个", "自己", "东西", "地方",
            "开始", "起来", "出来", "进行", "通过", "以及", "其中", "其实", "当时", "今天"}
_HAN2 = re.compile(r"[一-鿿]{2}")

def auto_excerpt(text, limit=80):
    """取正文开头第一段有信息量的文字做摘要片段。"""
    for line in text.splitlines():
        t = line.strip()
        if len(re.sub(r"[\W\d_]", "", t)) >= 8:
            t = re.sub(r"\s+", " ", t)
            return t[:limit]
    return ""

def auto_keywords(text, top=6, min_freq=4):
    """词频法抽中文二字词做粗筛关键词。糙,但零成本、够 grep 用。"""
    from collections import Counter
    cnt = Counter()
    for i in range(len(text) - 1):
        pair = text[i:i+2]
        if (_HAN2.fullmatch(pair) and pair not in _STOP_W2
                and pair[0] not in _STOP_CH and pair[1] not in _STOP_CH):
            cnt[pair] += 1
    picked, used = [], set()
    for w, n in cnt.most_common(top * 4):
        if n < min_freq:
            break
        if any(w[0] in p or w[1] in p for p in used):
            continue
        picked.append(w); used.add(w)
        if len(picked) >= top:
            break
    return picked

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
