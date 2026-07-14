#!/usr/bin/env python3
"""Regression tests for the deterministic archive pipeline."""

import json
import importlib
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "scripts" / "build.py"
EXTRACT = ROOT / "scripts" / "extract.py"
CLEANUP = ROOT / "scripts" / "cleanup.py"
FIX_GARBLE = ROOT / "scripts" / "fix_garble.py"
VERIFY = ROOT / "scripts" / "verify.py"
CONVERT_LEGACY = ROOT / "scripts" / "convert_legacy.py"
OCR_BOOKS = ROOT / "scripts" / "ocr_books.py"
REQUIREMENTS = ROOT / "requirements.txt"


class ArchivePipelineTests(unittest.TestCase):
    @staticmethod
    def _write_epub(path, marker):
        path.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("chapter.xhtml", "<html><body>%s</body></html>" % (marker * 100))

    def test_same_basename_in_different_paths_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            raw_dir = out / "_raw" / "all"
            raw_dir.mkdir(parents=True)

            records = []
            fixtures = [
                ("a/report.docx", "a__report.docx.txt", "甲方案"),
                ("b/report.docx", "b__report.docx.txt", "乙方案"),
                ("a__report.docx", "top__report.docx.txt", "丙方案"),
            ]
            for rel, raw_name, marker in fixtures:
                raw = raw_dir / raw_name
                raw.write_text(marker * 100, encoding="utf-8")
                records.append({
                    "name": "report.docx" if "/" in rel else rel,
                    "rel": rel,
                    "ext": ".docx",
                    "size": 100,
                    "quality": "text",
                    "category": "其他",
                    "raw": str(raw.relative_to(out)),
                    "unit": "paragraphs",
                    "count": 1,
                    "chars": 300,
                })

            (out / "manifest.json").write_text(
                json.dumps(records, ensure_ascii=False),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [sys.executable, str(BUILD), "--out", str(out)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

            archived = sorted((out / "其他").glob("*.md"))
            self.assertEqual(len(archived), len(fixtures), proc.stdout)
            bodies = "\n".join(path.read_text(encoding="utf-8") for path in archived)
            for _, _, marker in fixtures:
                self.assertIn(marker, bodies)

    def test_incremental_flat_name_collision_keeps_both_raw_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "src"
            out = root / "out"
            self._write_epub(src / "a" / "book.epub", "甲资料")

            first = subprocess.run(
                [sys.executable, str(EXTRACT), "--src", str(src), "--out", str(out)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)

            self._write_epub(src / "a__book.epub", "乙资料")
            second = subprocess.run(
                [sys.executable, str(EXTRACT), "--src", str(src), "--out", str(out)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)

            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            raw_paths = [record["raw"] for record in manifest]
            self.assertEqual(len(set(raw_paths)), 2, second.stdout)
            bodies = [
                (out / raw_path).read_text(encoding="utf-8")
                for raw_path in raw_paths
            ]
            self.assertTrue(any("甲资料" in body for body in bodies))
            self.assertTrue(any("乙资料" in body for body in bodies))

    def test_full_epub_pipeline_rebuilds_and_safely_cleans_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "src"
            out = root / "out"
            source = src / "book.epub"
            self._write_epub(source, "完整流程资料")

            commands = [
                [sys.executable, str(EXTRACT), "--src", str(src), "--out", str(out)],
                [sys.executable, str(BUILD), "--out", str(out)],
                [sys.executable, str(BUILD), "--out", str(out)],
                [sys.executable, str(VERIFY), "--out", str(out)],
            ]
            for command in commands:
                proc = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)

            # cleanup 只需要元数据与父目录写权限，不应要求源文件可读。
            source.chmod(0o200)
            cleanup_proc = subprocess.run(
                [
                    sys.executable,
                    str(CLEANUP),
                    "--src",
                    str(src),
                    "--out",
                    str(out),
                    "--apply",
                ],
                capture_output=True,
                text=True,
            )
            self.assertEqual(cleanup_proc.returncode, 0, cleanup_proc.stdout + cleanup_proc.stderr)

            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest[0]["original_deleted"])
            self.assertFalse(source.exists())
            self.assertTrue((out / manifest[0]["raw"]).is_file())
            self.assertEqual(len(list((out / "其他").glob("*.md"))), 1)

    def test_build_rejects_category_that_escapes_output_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "library"
            raw = out / "_raw" / "all" / "record.txt"
            raw.parent.mkdir(parents=True)
            raw.write_text("安全内容" * 100, encoding="utf-8")
            sentinel = root / "must-survive.txt"
            sentinel.write_text("sentinel", encoding="utf-8")
            record = {
                "name": "record.docx",
                "rel": "record.docx",
                "ext": ".docx",
                "quality": "text",
                "category": "..",
                "raw": str(raw.relative_to(out)),
                "chars": 400,
            }
            (out / "manifest.json").write_text(
                json.dumps([record], ensure_ascii=False),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [sys.executable, str(BUILD), "--out", str(out)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertTrue(sentinel.is_file(), proc.stdout + proc.stderr)

    def test_build_rejects_windows_absolute_category_on_any_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "library"
            raw = out / "_raw" / "all" / "record.txt"
            raw.parent.mkdir(parents=True)
            raw.write_text("安全内容" * 100, encoding="utf-8")
            record = {
                "name": "record.docx",
                "rel": "record.docx",
                "ext": ".docx",
                "quality": "text",
                "category": r"C:\outside",
                "raw": str(raw.relative_to(out)),
                "chars": 400,
            }
            (out / "manifest.json").write_text(
                json.dumps([record], ensure_ascii=False),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [sys.executable, str(BUILD), "--out", str(out)],
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_build_rejects_case_variant_of_reserved_raw_category(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "library"
            raw = out / "_raw" / "all" / "record.txt"
            raw.parent.mkdir(parents=True)
            raw.write_text("必须保留" * 100, encoding="utf-8")
            record = {
                "name": "record.docx",
                "rel": "record.docx",
                "ext": ".docx",
                "quality": "text",
                "category": "_RAW",
                "raw": "_raw/all/record.txt",
                "chars": 400,
            }
            (out / "manifest.json").write_text(
                json.dumps([record], ensure_ascii=False),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [sys.executable, str(BUILD), "--out", str(out)],
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertTrue(raw.is_file(), proc.stdout + proc.stderr)

    def test_cleanup_is_idempotent_when_source_root_is_already_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "missing-source"
            out = root / "library"
            out.mkdir()
            record = {
                "name": "gone.docx",
                "rel": "gone.docx",
                "ext": ".docx",
                "quality": "text",
                "raw": "_raw/all/gone.txt",
                "original_deleted": True,
            }
            (out / "manifest.json").write_text(
                json.dumps([record], ensure_ascii=False),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [
                    sys.executable,
                    str(CLEANUP),
                    "--src",
                    str(src),
                    "--out",
                    str(out),
                    "--apply",
                ],
                capture_output=True,
                text=True,
            )

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("已删 0 个", proc.stdout)

    def test_verify_rejects_unsafe_category_even_before_archive_is_built(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "library"
            raw = out / "_raw" / "all" / "record.txt"
            raw.parent.mkdir(parents=True)
            raw.write_text("安全内容" * 100, encoding="utf-8")
            record = {
                "name": "record.docx",
                "rel": "record.docx",
                "ext": ".docx",
                "quality": "text",
                "category": "../outside",
                "raw": str(raw.relative_to(out)),
                "chars": 400,
            }
            (out / "manifest.json").write_text(
                json.dumps([record], ensure_ascii=False),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [sys.executable, str(VERIFY), "--out", str(out)],
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_cleanup_rejects_source_path_that_escapes_source_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "source"
            out = root / "library"
            src.mkdir()
            raw = out / "_raw" / "all" / "victim.txt"
            raw.parent.mkdir(parents=True)
            raw.write_text("已归档内容" * 20, encoding="utf-8")
            victim = root / "victim.docx"
            victim.write_text("不应被删除", encoding="utf-8")
            record = {
                "name": "victim.docx",
                "rel": "../victim.docx",
                "ext": ".docx",
                "quality": "text",
                "raw": str(raw.relative_to(out)),
            }
            (out / "manifest.json").write_text(
                json.dumps([record], ensure_ascii=False),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [
                    sys.executable,
                    str(CLEANUP),
                    "--src",
                    str(src),
                    "--out",
                    str(out),
                    "--apply",
                ],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertTrue(victim.is_file(), proc.stdout + proc.stderr)

    def test_fix_garble_rejects_raw_path_that_escapes_output_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "library"
            out.mkdir()
            victim = root / "outside.txt"
            original = "错" * 120
            victim.write_text(original, encoding="utf-8")
            record = {
                "name": "outside.pdf",
                "rel": "outside.pdf",
                "ext": ".pdf",
                "quality": "text",
                "raw": "../outside.txt",
            }
            (out / "manifest.json").write_text(
                json.dumps([record], ensure_ascii=False),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [sys.executable, str(FIX_GARBLE), "--out", str(out), "--rad", "0", "--dup", "0"],
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertEqual(victim.read_text(encoding="utf-8"), original)

    def test_extract_migrates_a_legacy_colliding_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "src"
            out = root / "out"
            self._write_epub(src / "a" / "book.epub", "甲资料")
            self._write_epub(src / "a__book.epub", "乙资料")
            raw = out / "_raw" / "all" / "a__book.epub.txt"
            raw.parent.mkdir(parents=True)
            raw.write_text("碰撞后的错误旧内容" * 20, encoding="utf-8")
            records = [
                {
                    "name": "book.epub",
                    "rel": "a/book.epub",
                    "ext": ".epub",
                    "size": 100,
                    "quality": "text",
                    "category": "其他",
                    "raw": str(raw.relative_to(out)),
                },
                {
                    "name": "a__book.epub",
                    "rel": "a__book.epub",
                    "ext": ".epub",
                    "size": 100,
                    "quality": "text",
                    "category": "其他",
                    "raw": str(raw.relative_to(out)),
                },
            ]
            (out / "manifest.json").write_text(
                json.dumps(records, ensure_ascii=False),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [sys.executable, str(EXTRACT), "--src", str(src), "--out", str(out)],
                capture_output=True,
                text=True,
            )

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            raw_paths = [record["raw"] for record in manifest]
            self.assertEqual(len(set(raw_paths)), 2, proc.stdout)
            bodies = [(out / raw_path).read_text(encoding="utf-8") for raw_path in raw_paths]
            self.assertTrue(any("甲资料" in body for body in bodies))
            self.assertTrue(any("乙资料" in body for body in bodies))

    def test_extract_rejects_raw_directory_symlink_outside_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "src"
            out = root / "out"
            outside = root / "outside"
            self._write_epub(src / "book.epub", "安全资料")
            out.mkdir()
            outside.mkdir()
            (out / "_raw").symlink_to(outside, target_is_directory=True)

            proc = subprocess.run(
                [sys.executable, str(EXTRACT), "--src", str(src), "--out", str(out)],
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("拒绝不安全", proc.stdout + proc.stderr)
            self.assertEqual(list(outside.rglob("*")), [])

    def test_convert_rejects_raw_directory_symlink_before_tool_or_manifest_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "src"
            out = root / "out"
            outside = root / "outside"
            src.mkdir()
            out.mkdir()
            outside.mkdir()
            (out / "_raw").symlink_to(outside, target_is_directory=True)

            proc = subprocess.run(
                [
                    sys.executable,
                    str(CONVERT_LEGACY),
                    "--src",
                    str(src),
                    "--out",
                    str(out),
                    "--soffice",
                    sys.executable,
                ],
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("拒绝不安全", proc.stdout + proc.stderr)
            self.assertEqual(list(outside.rglob("*")), [])

    def test_ocr_rejects_raw_directory_symlink_before_optional_dependencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "src"
            out = root / "out"
            outside = root / "outside"
            src.mkdir()
            out.mkdir()
            outside.mkdir()
            (out / "_raw").symlink_to(outside, target_is_directory=True)

            proc = subprocess.run(
                [sys.executable, str(OCR_BOOKS), "--src", str(src), "--out", str(out)],
                capture_output=True,
                text=True,
            )

            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("拒绝不安全", proc.stdout + proc.stderr)
            self.assertEqual(list(outside.rglob("*")), [])

    @staticmethod
    def _common_module():
        scripts = str(ROOT / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        return importlib.import_module("common")

    @classmethod
    def _script_module(cls, name):
        cls._common_module()
        return importlib.import_module(name)

    def test_extract_integration_refuses_raw_parent_replacement(self):
        common = self._common_module()
        extract = self._script_module("extract")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "src"
            out = root / "out"
            raw = out / "_raw" / "all"
            parked = out / "_raw" / "all-parked"
            outside = root / "outside"
            self._write_epub(src / "book.epub", "安全资料")
            outside.mkdir()
            original = common._open_parent_fd
            fired = False

            def replace_raw_parent(base, relative, create=False):
                nonlocal fired
                result = original(base, relative, create=create)
                if not fired and str(relative).replace("\\", "/").startswith("_raw/all/"):
                    fired = True
                    raw.rename(parked)
                    raw.symlink_to(outside, target_is_directory=True)
                return result

            argv = ["extract.py", "--src", str(src), "--out", str(out)]
            with mock.patch.object(common, "_open_parent_fd", replace_raw_parent):
                with mock.patch.object(sys, "argv", argv):
                    extract.main()

            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(fired)
            self.assertEqual(manifest[0]["quality"], "failed")
            self.assertEqual(list(outside.iterdir()), [])
            self.assertEqual(list(parked.iterdir()), [])

    def test_build_integration_refuses_category_replacement(self):
        common = self._common_module()
        build = self._script_module("build")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            category = out / "category"
            parked = out / "category-parked"
            outside = root / "outside"
            raw = out / "_raw" / "all" / "record.txt"
            raw.parent.mkdir(parents=True)
            raw.write_text("正文" * 100, encoding="utf-8")
            category.mkdir()
            (category / "inside.txt").write_text("inside", encoding="utf-8")
            outside.mkdir()
            (outside / "keep.txt").write_text("keep", encoding="utf-8")
            records = [{
                "name": "record.docx",
                "rel": "record.docx",
                "ext": ".docx",
                "quality": "text",
                "category": "category",
                "raw": "_raw/all/record.txt",
                "chars": 200,
            }]
            (out / "manifest.json").write_text(json.dumps(records), encoding="utf-8")
            original = common._open_parent_fd
            fired = False

            def replace_category(base, relative, create=False):
                nonlocal fired
                result = original(base, relative, create=create)
                if not fired and str(relative) == "category":
                    fired = True
                    category.rename(parked)
                    category.symlink_to(outside, target_is_directory=True)
                return result

            with mock.patch.object(common, "_open_parent_fd", replace_category):
                with mock.patch.object(sys, "argv", ["build.py", "--out", str(out)]):
                    with self.assertRaises((OSError, RuntimeError, ValueError)):
                        build.main()

            self.assertTrue(fired)
            self.assertEqual((outside / "keep.txt").read_text(encoding="utf-8"), "keep")
            self.assertTrue((parked / "inside.txt").is_file())

    def test_cleanup_integration_refuses_source_parent_replacement(self):
        common = self._common_module()
        cleanup = self._script_module("cleanup")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "src"
            nested = src / "nested"
            parked = src / "nested-parked"
            out = root / "out"
            outside = root / "outside"
            nested.mkdir(parents=True)
            (nested / "victim.docx").write_text("inside", encoding="utf-8")
            outside.mkdir()
            (outside / "victim.docx").write_text("outside", encoding="utf-8")
            raw = out / "_raw" / "all" / "record.txt"
            raw.parent.mkdir(parents=True)
            raw.write_text("已归档内容" * 20, encoding="utf-8")
            records = [{
                "name": "victim.docx",
                "rel": "nested/victim.docx",
                "ext": ".docx",
                "quality": "text",
                "raw": "_raw/all/record.txt",
            }]
            (out / "manifest.json").write_text(json.dumps(records), encoding="utf-8")
            original = common._open_parent_fd
            source_opens = 0

            def replace_on_delete(base, relative, create=False):
                nonlocal source_opens
                result = original(base, relative, create=create)
                if (os.path.realpath(base) == os.path.realpath(src)
                        and str(relative).replace("\\", "/") == "nested/victim.docx"):
                    source_opens += 1
                    if source_opens == 2:
                        nested.rename(parked)
                        nested.symlink_to(outside, target_is_directory=True)
                return result

            argv = ["cleanup.py", "--src", str(src), "--out", str(out), "--apply"]
            with mock.patch.object(common, "_open_parent_fd", replace_on_delete):
                with mock.patch.object(sys, "argv", argv):
                    with self.assertRaises((OSError, RuntimeError, ValueError)):
                        cleanup.main()

            self.assertEqual(source_opens, 2)
            self.assertEqual((outside / "victim.docx").read_text(encoding="utf-8"), "outside")
            self.assertEqual((parked / "victim.docx").read_text(encoding="utf-8"), "inside")

    def test_secure_write_detects_parent_replacement_after_fd_open(self):
        common = self._common_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            raw = out / "_raw" / "all"
            parked = out / "_raw" / "all-parked"
            outside = root / "outside"
            raw.mkdir(parents=True)
            outside.mkdir()
            original = common._open_parent_fd

            def replace_after_open(base, relative, create=False):
                result = original(base, relative, create=create)
                raw.rename(parked)
                raw.symlink_to(outside, target_is_directory=True)
                return result

            with mock.patch.object(common, "_open_parent_fd", replace_after_open):
                with self.assertRaises((OSError, RuntimeError, ValueError)):
                    common.secure_write_text(out, "_raw/all/book.txt", "内容", create_parent=True)

            self.assertFalse((outside / "book.txt").exists())
            self.assertFalse((parked / "book.txt").exists())

    def test_secure_rmtree_refuses_directory_replacement_after_fd_open(self):
        common = self._common_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "out"
            category = out / "category"
            parked = out / "category-parked"
            outside = root / "outside"
            category.mkdir(parents=True)
            (category / "inside.txt").write_text("inside", encoding="utf-8")
            outside.mkdir()
            (outside / "keep.txt").write_text("keep", encoding="utf-8")
            original = common._open_parent_fd

            def replace_after_open(base, relative, create=False):
                result = original(base, relative, create=create)
                category.rename(parked)
                category.symlink_to(outside, target_is_directory=True)
                return result

            with mock.patch.object(common, "_open_parent_fd", replace_after_open):
                with self.assertRaises((OSError, RuntimeError, ValueError)):
                    common.secure_rmtree(out, "category")

            self.assertEqual((outside / "keep.txt").read_text(encoding="utf-8"), "keep")
            self.assertTrue((parked / "inside.txt").is_file())

    def test_secure_unlink_detects_parent_replacement_after_fd_open(self):
        common = self._common_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "src"
            nested = src / "nested"
            parked = src / "nested-parked"
            outside = root / "outside"
            nested.mkdir(parents=True)
            (nested / "victim.txt").write_text("inside", encoding="utf-8")
            outside.mkdir()
            (outside / "victim.txt").write_text("outside", encoding="utf-8")
            original = common._open_parent_fd

            def replace_after_open(base, relative, create=False):
                result = original(base, relative, create=create)
                nested.rename(parked)
                nested.symlink_to(outside, target_is_directory=True)
                return result

            with mock.patch.object(common, "_open_parent_fd", replace_after_open):
                with self.assertRaises((OSError, RuntimeError, ValueError)):
                    common.secure_unlink(src, "nested/victim.txt")

            self.assertEqual((outside / "victim.txt").read_text(encoding="utf-8"), "outside")
            self.assertEqual((parked / "victim.txt").read_text(encoding="utf-8"), "inside")

    def test_secure_write_hides_payload_in_private_staging_directory(self):
        common = self._common_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            final = root / "final.txt"
            final.write_text("OLD-MUST-BE-REPLACED", encoding="utf-8")
            original = common._assert_parent_stable
            checks = 0
            stage_modes = []

            def attack_old_parent_temp(base, relative, parent_fd):
                nonlocal checks
                original(base, relative, parent_fd)
                checks += 1
                if checks == 2:
                    old_temps = list(root.glob(".final.txt.tmp-*"))
                    if old_temps:
                        old_temps[0].rename(root / "intended-temp-stash")
                        old_temps[0].write_text("ATTACKER-CONTENT", encoding="utf-8")
                    stages = list(root.glob(".corpus-stage-*"))
                    stage_modes.extend(path.stat().st_mode & 0o777 for path in stages)

            with mock.patch.object(common, "_assert_parent_stable", attack_old_parent_temp):
                common.secure_write_text(root, "final.txt", "GOOD-CONTENT")

            self.assertEqual(final.read_text(encoding="utf-8"), "GOOD-CONTENT")
            self.assertFalse((root / "intended-temp-stash").exists())
            self.assertEqual(stage_modes, [0o700])
            self.assertEqual(list(root.glob(".corpus-stage-*")), [])

    def test_secure_write_preserves_existing_file_mode(self):
        common = self._common_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "secret.txt"
            target.write_text("old", encoding="utf-8")
            target.chmod(0o600)

            common.secure_write_text(root, "secret.txt", "new")

            self.assertEqual(target.read_text(encoding="utf-8"), "new")
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_metadata_write_and_delete_support_write_only_files(self):
        common = self._common_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "write-only.txt"
            target.write_text("old", encoding="utf-8")
            target.chmod(0o200)

            before = common.secure_file_stat(root, "write-only.txt")
            self.assertEqual(before.st_mode & 0o777, 0o200)
            common.secure_write_text(root, "write-only.txt", "new")
            self.assertEqual(target.stat().st_mode & 0o777, 0o200)

            target.chmod(0o600)
            self.assertEqual(target.read_text(encoding="utf-8"), "new")
            target.chmod(0o200)
            snapshot = common.secure_file_stat(root, "write-only.txt")
            self.assertEqual(common.secure_unlink(root, "write-only.txt", expected=snapshot), 3)
            self.assertFalse(target.exists())

    def test_secure_unlink_has_no_parent_visible_quarantine_payload(self):
        common = self._common_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            victim = root / "victim.txt"
            decoy = root / "decoy.txt"
            victim.write_text("INTENDED", encoding="utf-8")
            decoy.write_text("DO-NOT-DELETE", encoding="utf-8")
            original = common._lstat_at

            def attack_old_quarantine(parent_fd, name):
                info = original(parent_fd, name)
                if name.startswith(".victim.txt.delete-"):
                    old = root / name
                    old.rename(root / "intended-stash")
                    decoy.rename(old)
                return info

            with mock.patch.object(common, "_lstat_at", attack_old_quarantine):
                common.secure_unlink(root, "victim.txt")

            self.assertFalse(victim.exists())
            self.assertEqual(decoy.read_text(encoding="utf-8"), "DO-NOT-DELETE")
            self.assertFalse((root / "intended-stash").exists())
            self.assertEqual(list(root.glob(".corpus-stage-*")), [])

    def test_secure_rmtree_has_no_parent_visible_quarantine_payload(self):
        common = self._common_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            category = root / "category"
            decoy = root / "decoy"
            category.mkdir()
            decoy.mkdir()
            (category / "intended.txt").write_text("INTENDED", encoding="utf-8")
            (decoy / "keep.txt").write_text("DO-NOT-DELETE", encoding="utf-8")
            original = common._lstat_at

            def attack_old_quarantine(parent_fd, name):
                info = original(parent_fd, name)
                if name.startswith(".category.delete-"):
                    old = root / name
                    old.rename(root / "intended-stash")
                    decoy.rename(old)
                return info

            with mock.patch.object(common, "_lstat_at", attack_old_quarantine):
                self.assertTrue(common.secure_rmtree(root, "category"))

            self.assertFalse(category.exists())
            self.assertEqual((decoy / "keep.txt").read_text(encoding="utf-8"), "DO-NOT-DELETE")
            self.assertFalse((root / "intended-stash").exists())
            self.assertEqual(list(root.glob(".corpus-stage-*")), [])

    def test_staging_creation_failure_closes_fd_and_removes_empty_directory(self):
        common = self._common_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            parent_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                before = len(os.listdir("/dev/fd"))
                with mock.patch.object(
                    common.os,
                    "fchmod",
                    side_effect=PermissionError("injected"),
                ):
                    with self.assertRaises(PermissionError):
                        common._create_staging_dir(parent_fd)
                after = len(os.listdir("/dev/fd"))
            finally:
                os.close(parent_fd)

            self.assertEqual(before, after)
            self.assertEqual(list(root.glob(".corpus-stage-*")), [])

    def test_build_bounds_archive_filename_for_a_very_long_nested_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "library"
            raw = out / "_raw" / "all" / "record.txt"
            raw.parent.mkdir(parents=True)
            raw.write_text("长路径内容" * 100, encoding="utf-8")
            long_rel = "/".join(["很长的目录" * 12, "更长的目录" * 12, "报告.docx"])
            record = {
                "name": "报告.docx",
                "rel": long_rel,
                "ext": ".docx",
                "quality": "text",
                "category": "其他",
                "raw": str(raw.relative_to(out)),
                "chars": 500,
            }
            (out / "manifest.json").write_text(
                json.dumps([record], ensure_ascii=False),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [sys.executable, str(BUILD), "--out", str(out)],
                capture_output=True,
                text=True,
            )

            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            archived = list((out / "其他").glob("*.md"))
            self.assertEqual(len(archived), 1)
            self.assertLessEqual(len(archived[0].name.encode("utf-8")), 255)


class DependencyFloorTests(unittest.TestCase):
    def test_known_vulnerable_dependency_versions_are_excluded(self):
        requirements = {
            line.strip().lower()
            for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertIn("pymupdf>=1.26.7", requirements)
        self.assertIn("pillow>=12.3.0", requirements)


if __name__ == "__main__":
    unittest.main()
