import hashlib
import io
import tempfile
from types import SimpleNamespace
from unittest.mock import Mock
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from .evidence_storage import PrivateEvidenceStorage, validate_evidence_file, evidence_upload_path
from .evidence_services import assert_report_evidence_complete


class PrivateEvidenceTests(SimpleTestCase):
    def test_pdf_and_position(self):
        file = SimpleUploadedFile('bukti.pdf', b'%PDF-1.4\nexample')
        file.seek(3)
        validate_evidence_file(file)
        self.assertEqual(file.tell(), 3)

    def test_disguised_pdf_rejected(self):
        with self.assertRaises(ValidationError):
            validate_evidence_file(SimpleUploadedFile('bukti.pdf', b'not a PDF'))

    def test_executable_rejected(self):
        with self.assertRaises(ValidationError):
            validate_evidence_file(SimpleUploadedFile('bukti.exe', b'MZ'))

    def test_empty_rejected(self):
        with self.assertRaises(ValidationError):
            validate_evidence_file(SimpleUploadedFile('bukti.txt', b''))

    def test_oversize_rejected_without_reading(self):
        file = Mock(name='large')
        file.name = 'large.pdf'
        file.size = 20 * 1024 * 1024 + 1
        with self.assertRaises(ValidationError):
            validate_evidence_file(file)
        file.read.assert_not_called()

    def test_private_storage_has_no_public_url(self):
        with tempfile.TemporaryDirectory() as directory:
            with override_settings(PRIVATE_EVIDENCE_ROOT=directory, MEDIA_ROOT=''):
                storage = PrivateEvidenceStorage()
                with self.assertRaises(ValueError):
                    storage.url('file.pdf')

    def test_public_media_root_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with override_settings(PRIVATE_EVIDENCE_ROOT=directory + '/private', MEDIA_ROOT=directory):
                with self.assertRaises(ImproperlyConfigured):
                    PrivateEvidenceStorage()

    def test_upload_name_is_unique_and_scoped(self):
        report = SimpleNamespace(report_id=115)
        first = evidence_upload_path(report, '../../source.PDF')
        second = evidence_upload_path(report, '../../source.PDF')
        self.assertTrue(first.startswith('report_115/'))
        self.assertTrue(first.endswith('.pdf'))
        self.assertNotIn('..', first)
        self.assertNotEqual(first, second)

    def report_with(self, records):
        report = Mock()
        report.evidences.exclude.return_value.exclude.return_value = records
        return report

    def record(self, content=b'archive'):
        storage = Mock()
        storage.open.side_effect = lambda *args: io.BytesIO(content)
        return SimpleNamespace(pk=1, title='Bukti', file_size=7,
            sha256=hashlib.sha256(b'archive').hexdigest(),
            document=SimpleNamespace(name='report_115/file.pdf', storage=storage))

    def test_link_only_cannot_submit(self):
        with self.assertRaises(ValidationError):
            assert_report_evidence_complete(self.report_with([]))

    def test_intact_archive_can_submit(self):
        assert_report_evidence_complete(self.report_with([self.record()]))

    def test_changed_archive_blocks_submit(self):
        with self.assertRaises(ValidationError):
            assert_report_evidence_complete(self.report_with([self.record(b'changed')]))

    def test_missing_file_blocks_submit(self):
        record = self.record()
        record.document.storage.open.side_effect = FileNotFoundError()
        with self.assertRaises(ValidationError):
            assert_report_evidence_complete(self.report_with([record]))
