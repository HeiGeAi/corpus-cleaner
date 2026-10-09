"""Synthetic lifecycle regressions for INT9-001; no real corpus or converters."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import cleanup
import common
import convert_legacy
import extract
import fix_garble
import ocr_books
import verify


class ArchiveIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = Path(self.tmp.name) / 'src'
        self.out = Path(self.tmp.name) / 'out'
        self.src.mkdir()

    def epub(self, text='Original archived text ' * 30):
        with zipfile.ZipFile(self.src / 'book.epub', 'w') as z:
            z.writestr('chapter.xhtml', '<p>' + text + '</p>')

    def run_script(self, module, *extra):
        args = ['script', '--out', str(self.out)]
        if module not in (fix_garble, verify):
            args += ['--src', str(self.src)]
        with mock.patch.object(sys, 'argv', args + list(extra)), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            module.main()
        return output.getvalue()

    def records(self):
        return common.load_manifest(self.out)

    def raw(self):
        return self.out / self.records()[0]['raw']

    def assert_fingerprints(self, rec):
        self.assertEqual(rec.get('raw_sha256'), hashlib.sha256((self.out / rec['raw']).read_bytes()).hexdigest())
        self.assertEqual(rec.get('source_sha256'), hashlib.sha256((self.src / common.rec_key(rec)).read_bytes()).hexdigest())

    def test_extraction_records_exact_utf8_archive_hash(self):
        self.epub('中文资料\r\n原始文本 ' * 30)
        self.run_script(extract)
        self.assert_fingerprints(self.records()[0])

    def test_nonempty_corrupted_archive_preserves_source(self):
        self.epub()
        self.run_script(extract)
        self.raw().write_text('CORRUPTED ARCHIVE CONTENT WITHOUT ORIGINAL TEXT')
        self.run_script(cleanup, '--apply')
        self.assertTrue((self.src / 'book.epub').exists())
        self.assertFalse(self.records()[0].get('original_deleted'))

    def test_same_size_archive_replacement_preserves_source_and_duplicate(self):
        self.epub()
        (self.src / 'book.mobi').write_bytes(b'synthetic alternate book')
        self.run_script(extract)
        raw = self.raw()
        replacement = raw.with_suffix('.replacement')
        replacement.write_bytes(b'X' * len(raw.read_bytes()))
        replacement.replace(raw)
        self.run_script(cleanup, '--apply')
        self.assertTrue((self.src / 'book.epub').exists())
        self.assertTrue((self.src / 'book.mobi').exists())

    def test_legacy_missing_or_invalid_archive_hash_preserves_source(self):
        for value in (None, '', 'invalid', '0' * 64):
            with self.subTest(value=value):
                self.epub()
                self.run_script(extract, '--force')
                records = self.records()
                records[0]['raw_sha256'] = value
                common.save_manifest(self.out, records)
                self.run_script(cleanup, '--apply')
                self.assertTrue((self.src / 'book.epub').exists())

    def test_unreadable_archive_preserves_source(self):
        self.epub()
        self.run_script(extract)
        original_hash = common.secure_sha256
        def fail_archive(root, rel):
            if str(rel).startswith('_raw/'):
                raise PermissionError('synthetic unreadable archive')
            return original_hash(root, rel)
        with mock.patch.object(cleanup, 'secure_sha256', side_effect=fail_archive):
            self.run_script(cleanup, '--apply')
        self.assertTrue((self.src / 'book.epub').exists())

    def test_archive_is_rechecked_after_cleanup_selection(self):
        self.epub()
        self.run_script(extract)
        original_hash = common.secure_sha256
        changed = False
        def change_after_first_archive_check(root, rel):
            nonlocal changed
            digest = original_hash(root, rel)
            if str(rel).startswith('_raw/') and not changed:
                changed = True
                (self.out / rel).write_text('CHANGED AFTER SELECTION ' * 10)
            return digest
        with mock.patch.object(cleanup, 'secure_sha256', side_effect=change_after_first_archive_check):
            with self.assertRaises(RuntimeError):
                self.run_script(cleanup, '--apply')
        self.assertTrue(changed)
        self.assertTrue((self.src / 'book.epub').exists())

    def test_valid_text_repair_updates_hash_and_stays_incremental(self):
        self.epub('⽂学文案素材' * 40)
        self.run_script(extract)
        before = self.records()[0].get('raw_sha256')
        self.run_script(fix_garble)
        repaired = self.records()[0]
        self.assertTrue(repaired.get('garble_fixed'))
        self.assertNotEqual(repaired.get('raw_sha256'), before)
        self.assert_fingerprints(repaired)
        self.run_script(extract)
        self.assertEqual(self.records()[0], repaired)
        self.run_script(cleanup, '--apply')
        self.assertFalse((self.src / 'book.epub').exists())

    def test_text_repair_does_not_adopt_unknown_or_corrupted_archive(self):
        for case in ('legacy', 'corrupt'):
            with self.subTest(case=case):
                self.epub('⽂学文案素材' * 40)
                self.run_script(extract, '--force')
                if case == 'legacy':
                    records = self.records()
                    records[0].pop('raw_sha256', None)
                    common.save_manifest(self.out, records)
                else:
                    self.raw().write_text('⽂档替换内容' * 50)
                old_raw = self.raw().read_bytes()
                old_record = self.records()[0]
                self.run_script(fix_garble)
                self.assertEqual(self.raw().read_bytes(), old_raw)
                self.assertEqual(self.records()[0], old_record)
                self.run_script(cleanup, '--apply')
                self.assertTrue((self.src / 'book.epub').exists())

    def test_interrupted_repair_manifest_commit_preserves_source(self):
        self.epub('⽂学文案素材' * 40)
        self.run_script(extract)
        before = (self.out / 'manifest.json').read_bytes()
        with mock.patch.object(fix_garble, 'save_manifest', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):
                self.run_script(fix_garble)
        self.assertEqual((self.out / 'manifest.json').read_bytes(), before)
        self.run_script(cleanup, '--apply')
        self.assertTrue((self.src / 'book.epub').exists())

    def test_interrupted_extraction_manifest_commit_preserves_source(self):
        self.epub()
        self.run_script(extract)
        self.epub('Updated source text ' * 40)
        with mock.patch.object(extract, 'save_manifest', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):
                self.run_script(extract)
        self.run_script(cleanup, '--apply')
        self.assertTrue((self.src / 'book.epub').exists())

    def test_incremental_repairs_known_corruption_but_keeps_legacy_unverified(self):
        self.epub()
        self.run_script(extract)
        original = self.raw().read_bytes()
        self.raw().write_text('CORRUPTED ARCHIVE CONTENT')
        self.run_script(extract)
        self.assertEqual(self.raw().read_bytes(), original)
        self.assert_fingerprints(self.records()[0])
        records = self.records()
        records[0].pop('raw_sha256', None)
        records[0]['ocr'] = True
        common.save_manifest(self.out, records)
        self.raw().write_text('Legacy manually reviewed output')
        self.run_script(extract)
        self.assertEqual(self.raw().read_text(), 'Legacy manually reviewed output')
        self.assertNotIn('raw_sha256', self.records()[0])
        self.run_script(cleanup, '--apply')
        self.assertTrue((self.src / 'book.epub').exists())
        self.run_script(extract, '--force')
        self.assert_fingerprints(self.records()[0])
        self.run_script(cleanup, '--apply')
        self.assertFalse((self.src / 'book.epub').exists())

    def setup_ocr(self):
        (self.src / 'book.pdf').write_bytes(b'synthetic scanned PDF')
        common.save_manifest(self.out, [{'name': 'book.pdf', 'rel': 'book.pdf', 'ext': '.pdf', 'quality': 'image'}])
        return types.SimpleNamespace(open=lambda path: types.SimpleNamespace(page_count=1, close=lambda: None))

    def test_ocr_records_source_and_archive_fingerprints(self):
        with mock.patch.dict(sys.modules, {'fitz': self.setup_ocr()}), \
                mock.patch.object(ocr_books, 'require_tool'), \
                mock.patch.object(ocr_books, 'ocr_page', return_value='Recovered OCR text ' * 30):
            self.run_script(ocr_books)
        self.assertTrue(self.records()[0]['ocr'])
        self.assert_fingerprints(self.records()[0])
        self.run_script(cleanup, '--apply')
        self.assertFalse((self.src / 'book.pdf').exists())

    def test_source_changed_during_ocr_does_not_certify_archive(self):
        calls = 0
        def change_on_full(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                (self.src / 'book.pdf').write_bytes(b'changed synthetic PDF')
            return 'Recovered OCR text ' * 30
        with mock.patch.dict(sys.modules, {'fitz': self.setup_ocr()}), \
                mock.patch.object(ocr_books, 'require_tool'), \
                mock.patch.object(ocr_books, 'ocr_page', side_effect=change_on_full):
            with self.assertRaises(SystemExit):
                self.run_script(ocr_books)
        self.assertEqual(self.records()[0]['quality'], 'image')
        self.assertNotIn('raw_sha256', self.records()[0])
        self.assertTrue((self.src / 'book.pdf').exists())

    def test_conversion_records_source_and_archive_fingerprints(self):
        (self.src / 'book.ppt').write_bytes(b'synthetic legacy presentation')
        self.run_script(extract)
        def conversion(args, **kwargs):
            (Path(args[args.index('--outdir') + 1]) / 'book.pptx').write_bytes(b'synthetic converted output')
            return subprocess.CompletedProcess(args, 0)
        with mock.patch.object(convert_legacy.subprocess, 'run', side_effect=conversion), \
                mock.patch.object(convert_legacy, 'extract_pptx', return_value=('Converted text ' * 30, 1, 450, 'text')):
            self.run_script(convert_legacy, '--soffice', sys.executable)
        self.assert_fingerprints(self.records()[0])
        self.run_script(cleanup, '--apply')
        self.assertFalse((self.src / 'book.ppt').exists())

    def test_conversion_does_not_certify_source_changed_during_conversion(self):
        (self.src / 'book.ppt').write_bytes(b'synthetic legacy presentation')
        self.run_script(extract)
        def conversion(args, **kwargs):
            (Path(args[args.index('--outdir') + 1]) / 'book.pptx').write_bytes(b'synthetic converted output')
            (self.src / 'book.ppt').write_bytes(b'changed legacy presentation')
            return subprocess.CompletedProcess(args, 0)
        with mock.patch.object(convert_legacy.subprocess, 'run', side_effect=conversion), \
                mock.patch.object(convert_legacy, 'extract_pptx', return_value=('Converted text ' * 30, 1, 450, 'text')):
            self.run_script(convert_legacy, '--soffice', sys.executable)
        self.assertEqual(self.records()[0]['quality'], 'failed')
        self.assertNotIn('raw_sha256', self.records()[0])
        self.run_script(cleanup, '--apply')
        self.assertTrue((self.src / 'book.ppt').exists())

    def test_ocr_refreshes_source_fingerprint_from_actual_input(self):
        fake_fitz = self.setup_ocr()
        records = self.records()
        records[0]['source_sha256'] = hashlib.sha256(b'older scanned PDF').hexdigest()
        common.save_manifest(self.out, records)
        with mock.patch.dict(sys.modules, {'fitz': fake_fitz}), \
                mock.patch.object(ocr_books, 'require_tool'), \
                mock.patch.object(ocr_books, 'ocr_page', return_value='Recovered OCR text ' * 30):
            self.run_script(ocr_books)
        self.assert_fingerprints(self.records()[0])
        self.run_script(cleanup, '--apply')
        self.assertFalse((self.src / 'book.pdf').exists())

    def test_interrupted_ocr_manifest_commit_keeps_original(self):
        fake_fitz = self.setup_ocr()
        before = (self.out / 'manifest.json').read_bytes()
        with mock.patch.dict(sys.modules, {'fitz': fake_fitz}), \
                mock.patch.object(ocr_books, 'require_tool'), \
                mock.patch.object(ocr_books, 'ocr_page', return_value='Recovered OCR text ' * 30), \
                mock.patch.object(ocr_books, 'save_manifest', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):
                self.run_script(ocr_books)
        self.assertEqual((self.out / 'manifest.json').read_bytes(), before)
        self.run_script(cleanup, '--apply')
        self.assertTrue((self.src / 'book.pdf').exists())
        self.assertNotIn('raw_sha256', self.records()[0])

    def test_archive_fingerprint_is_not_adopted_from_later_disk_content(self):
        self.epub()
        real_write = common.secure_write_text
        def replace_after_write(root, rel, text, **kwargs):
            real_write(root, rel, text, **kwargs)
            if str(rel).startswith('_raw/'):
                (self.out / rel).write_text('UNRELATED CONTENT AFTER WRITE')
        with mock.patch.object(common, 'secure_write_text', side_effect=replace_after_write):
            self.run_script(extract)
        self.assertNotEqual(self.records()[0].get('raw_sha256'), hashlib.sha256(self.raw().read_bytes()).hexdigest())
        self.run_script(cleanup, '--apply')
        self.assertTrue((self.src / 'book.epub').exists())

    def test_missing_source_cannot_upgrade_legacy_archive(self):
        self.epub()
        self.run_script(extract)
        records = self.records()
        records[0].pop('raw_sha256', None)
        common.save_manifest(self.out, records)
        (self.src / 'book.epub').unlink()  # Temporary fixture only.
        self.run_script(extract, '--force')
        self.run_script(fix_garble)
        self.assertNotIn('raw_sha256', self.records()[0])

    def test_verify_reports_archive_integrity_failure(self):
        self.epub()
        self.run_script(extract)
        self.raw().write_text('Nonempty unrelated archive ' * 20)
        output = self.run_script(verify)
        self.assertIn('留档未验证', output)
        self.assertNotIn('✓ 文字类无异常', output)


if __name__ == '__main__':
    unittest.main()
