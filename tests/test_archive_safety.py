"""Synthetic regression fixtures for INT-001/002/006/007."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import cleanup
import extract
import common


class ArchiveSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = Path(self.tmp.name) / 'src'
        self.out = Path(self.tmp.name) / 'out'
        self.src.mkdir()

    def epub(self, text='Original archived text ' * 20):
        with zipfile.ZipFile(self.src / 'book.epub', 'w') as z:
            z.writestr('chapter.xhtml', '<p>' + text + '</p>')

    def run_script(self, module, *extra):
        with mock.patch.object(sys, 'argv', ['script', '--src', str(self.src), '--out', str(self.out), *extra]):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                module.main()
        return output.getvalue()

    def records(self):
        return json.loads((self.out / 'manifest.json').read_text())

    def test_duplicate_requires_verified_epub_archive(self):
        for case in ('corrupt', 'empty', 'removed', 'archived', 'raw_missing', 'raw_empty'):
            with self.subTest(case=case):
                self.epub('' if case == 'empty' else 'Retain this book text ' * 20)
                if case == 'corrupt':
                    (self.src / 'book.epub').write_bytes(b'invalid zip')
                (self.src / 'book.mobi').write_bytes(b'only recoverable mobi book')
                self.run_script(extract, '--force')
                rec = next(r for r in self.records() if r['name'] == 'book.mobi')
                self.assertEqual(rec.get('duplicate_of'), 'book.epub')
                if case == 'removed':
                    (self.src / 'book.epub').unlink()
                if case in ('raw_missing', 'raw_empty'):
                    raw = self.out / next(r for r in self.records() if r['name'] == 'book.epub')['raw']
                    if case == 'raw_missing':
                        raw.unlink()
                    else:
                        raw.write_text('')
                self.run_script(cleanup, '--apply')
                self.assertEqual((self.src / 'book.mobi').exists(), case != 'archived')

    def test_changed_source_same_size_or_larger_is_retained_and_refreshed(self):
        for text in ('Changed! archived text ' * 20, 'Larger replacement text ' * 200):
            with self.subTest(text=text[:10]):
                self.epub()
                self.run_script(extract, '--force')
                previous = self.records()[0].get('source_sha256')
                self.epub(text)
                self.run_script(cleanup, '--apply')
                self.assertTrue((self.src / 'book.epub').exists())
                self.run_script(extract)
                self.assertNotEqual(self.records()[0]['source_sha256'], previous)
                self.run_script(cleanup, '--apply')
                self.assertFalse((self.src / 'book.epub').exists())

    def test_legacy_fingerprint_missing_is_retained(self):
        self.epub()
        self.run_script(extract)
        records = self.records()
        records[0].pop('source_sha256', None)
        (self.out / 'manifest.json').write_text(json.dumps(records))
        self.run_script(cleanup, '--apply')
        self.assertTrue((self.src / 'book.epub').exists())

    def test_unreadable_source_is_retained(self):
        self.epub()
        self.run_script(extract)
        with mock.patch.object(cleanup, 'secure_sha256', side_effect=PermissionError):
            self.run_script(cleanup, '--apply')
        self.assertTrue((self.src / 'book.epub').exists())

    def test_changed_duplicate_source_is_retained(self):
        self.epub()
        (self.src / 'book.mobi').write_bytes(b'old book')
        self.run_script(extract)
        (self.src / 'book.mobi').write_bytes(b'new book')
        self.run_script(cleanup, '--apply')
        self.assertTrue((self.src / 'book.mobi').exists())

    def test_escaped_text_and_numeric_entities_survive(self):
        self.epub('Keep &lt;important text&gt; &lt;code&gt; &#x4E2D; <script>evil()</script><style>bad</style>')
        text, _ = extract.extract_epub(self.src / 'book.epub')
        self.assertIn('<important text>', text)
        self.assertIn('<code> 中', text)
        self.assertNotIn('evil', text)
        self.assertNotIn('bad', text)
        self.assertNotIn('<p>', text)

    def test_failed_converters_and_timeout_are_retryable(self):
        (self.src / 'book.doc').write_bytes(b'synthetic doc')
        for error in (subprocess.CalledProcessError(1, 'textutil'), subprocess.TimeoutExpired('textutil', 60)):
            with self.subTest(error=type(error).__name__):
                with mock.patch.object(extract.sys, 'platform', 'darwin'), mock.patch.object(extract.shutil, 'which', return_value='/textutil'):
                    with mock.patch.object(extract.subprocess, 'run', side_effect=error):
                        self.run_script(extract, '--force')
                    self.assertEqual(self.records()[0]['quality'], 'failed')
                    with mock.patch.object(extract.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'recovered text ' * 20)) as run:
                        self.run_script(extract)
                        self.assertTrue(run.call_args.kwargs.get('check', False))
                    self.assertEqual(self.records()[0]['quality'], 'text')
                    self.assertIn('recovered', (self.out / self.records()[0]['raw']).read_text())

    def test_libreoffice_missing_output_is_failure(self):
        with mock.patch.object(extract.sys, 'platform', 'linux'), mock.patch.object(extract, 'find_soffice', return_value='/soffice'):
            with mock.patch.object(extract.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
                with self.assertRaisesRegex(RuntimeError, 'LibreOffice'):
                    extract.extract_doc(str(self.src / 'book.doc'))
                self.assertTrue(run.call_args.kwargs.get('check', False))

    def test_legacy_empty_sparse_is_not_settled(self):
        self.out.mkdir()
        (self.out / 'empty.txt').write_text('')
        self.assertFalse(common.is_settled({'quality': 'sparse', 'raw': 'empty.txt'}, self.out))
