from datetime import date
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError, PermissionDenied
from django.test import TestCase, Client
from django.urls import reverse
from masterdata.models import TahunBuku, PeriodeLaporan
from .models import MonthlyRiskReport
from .nas_models import NASEvidence, NASEvidenceLocation, validate_nas_url
from .nas_services import review_evidence, has_verified_nas_evidence
from .evidence_services import assert_report_evidence_complete

class NASEvidenceTests(TestCase):
    def setUp(self):
        from .tests import MonthlyRiskReportAdminTests
        self.prepared_by=get_user_model().objects.create_user("nas_pic",is_staff=True)
        self.admin_user=get_user_model().objects.create_superuser("nas_admin","nas@example.com","test")
        self.tahun_buku=TahunBuku.objects.create(tahun=2026)
        self.periode=PeriodeLaporan.objects.create(tahun_buku=self.tahun_buku,kode_periode="2026-10",
            nama_periode="Oktober 2026",jenis_periode="bulanan",tanggal_mulai=date(2026,10,1),tanggal_selesai=date(2026,10,31))
        self.report=MonthlyRiskReportAdminTests._report(self,"BID NAS TEST")
        self.location=NASEvidenceLocation.objects.create(report=self.report,
            folder_path="/DIV MRK/3. Profil Risiko & Lap Risiko/2026/7. Bid. Bis/2026-10",
            upload_url="https://brightbox.plnbatam.com:5001/sharing/UploadTest")
    def evidence(self,**kw):
        data=dict(report=self.report,location=self.location,title="Eviden Oktober",
            read_url="https://brightbox.plnbatam.com:5001/sharing/ReadTest",
            relative_path="PIC/paket.zip",uploaded_by=self.prepared_by)
        data.update(kw)
        return NASEvidence.objects.create(**data)
    def url(self):
        return reverse("risk_admin:monthly_report_monthlyriskreport_nas_evidence",args=[self.report.pk])
    def test_only_https_brightbox_links(self):
        for url in ["http://brightbox.plnbatam.com/sharing/abc","https://example.com/sharing/abc",
            "https://user:password@brightbox.plnbatam.com/sharing/abc","https://brightbox.plnbatam.com:22/sharing/abc"]:
            with self.assertRaises(ValidationError): validate_nas_url(url)
    def test_month_folder_must_match(self):
        self.location.folder_path=self.location.folder_path.replace("2026-10","2026-09")
        with self.assertRaises(ValidationError): self.location.save()
    def test_upload_link_cannot_be_registered_as_read_link(self):
        with self.assertRaises(ValidationError): self.evidence(read_url=self.location.upload_url)
    def test_link_without_verification_blocks_submit(self):
        self.evidence()
        with self.assertRaises(ValidationError): assert_report_evidence_complete(self.report)
    def test_verified_nas_allows_evidence_requirement(self):
        e=self.evidence();review_evidence(e.pk,self.admin_user,"verify","Berkas dibuka dan sesuai Oktober.")
        self.assertTrue(has_verified_nas_evidence(self.report))
        assert_report_evidence_complete(self.report)
    def test_revocation_blocks_submit_and_preserves_history(self):
        e=self.evidence();review_evidence(e.pk,self.admin_user,"verify","Sesuai")
        review_evidence(e.pk,self.admin_user,"revoke","Berkas tidak lagi tersedia")
        self.assertEqual(e.reviews.count(),2)
        with self.assertRaises(ValidationError): assert_report_evidence_complete(self.report)
    def test_pic_cannot_self_verify_without_permission(self):
        e=self.evidence()
        with self.assertRaises(PermissionDenied): review_evidence(e.pk,self.prepared_by,"verify","Sesuai")
    def test_verified_flag_cannot_be_forged_on_create(self):
        with self.assertRaises(ValidationError): self.evidence(verified=True)
    def test_stored_record_is_immutable(self):
        e=self.evidence();e.read_url="https://brightbox.plnbatam.com/sharing/Changed"
        with self.assertRaises(ValidationError): e.save()
    def test_locked_report_rejects_creation_and_verification(self):
        e=self.evidence()
        MonthlyRiskReport.objects.filter(pk=self.report.pk).update(is_locked=True)
        with self.assertRaises(ValidationError): self.evidence()
        with self.assertRaises(ValidationError): review_evidence(e.pk,self.admin_user,"verify","Sesuai")
    def test_scope_change_invalidates_verified_evidence(self):
        e=self.evidence();review_evidence(e.pk,self.admin_user,"verify","Sesuai")
        self.assertTrue(has_verified_nas_evidence(self.report))
        self.report.periode_id=999999
        self.assertFalse(has_verified_nas_evidence(self.report))
    def test_integrity_failure_of_prisma_file_still_blocks_submit(self):
        from .test_private_evidence import PrivateEvidenceTests
        e=self.evidence();review_evidence(e.pk,self.admin_user,"verify","Sesuai")
        original=PrivateEvidenceTests().record(b"changed")
        from unittest.mock import Mock
        report=Mock();report.evidences.exclude.return_value.exclude.return_value=[original]
        with self.assertRaises(ValidationError): assert_report_evidence_complete(report)
    def test_get_page_does_not_change_evidence(self):
        self.client.force_login(self.admin_user)
        response=self.client.get(self.url())
        self.assertEqual(response.status_code,200)
        self.assertContains(response,"Unggah ke Brightbox")
        self.assertFalse(NASEvidence.objects.exists())
    def test_verify_requires_confirmation_and_csrf(self):
        e=self.evidence();self.client.force_login(self.admin_user)
        self.client.post(self.url(),{"action":"verify","evidence_id":e.pk,"note":"Sesuai"})
        e.refresh_from_db();self.assertFalse(e.verified)
        c=Client(enforce_csrf_checks=True);c.force_login(self.admin_user)
        self.assertEqual(c.post(self.url(),{"action":"verify","evidence_id":e.pk,"note":"Sesuai","confirmed":"yes"}).status_code,403)
    def test_admin_register_then_verify_through_page(self):
        self.client.force_login(self.admin_user)
        response=self.client.post(self.url(),{"action":"register","title":"Paket bukti",
            "read_url":"https://brightbox.plnbatam.com:5001/sharing/ReadTest",
            "relative_path":"PIC/file.zip","description":"Daftar berkas"})
        self.assertEqual(response.status_code,302)
        e=NASEvidence.objects.get()
        response=self.client.post(self.url(),{"action":"verify","evidence_id":e.pk,"note":"Isi telah diperiksa","confirmed":"yes"})
        self.assertEqual(response.status_code,302)
        e.refresh_from_db();self.assertTrue(e.verified)
    def test_submitted_report_rejects_new_evidence(self):
        MonthlyRiskReport.objects.filter(pk=self.report.pk).update(status="submitted")
        with self.assertRaises(ValidationError): self.evidence()

    def test_flag_without_review_is_not_sufficient(self):
        from django.utils import timezone
        e=self.evidence()
        NASEvidence.objects.filter(pk=e.pk).update(verified=True,verified_by=self.admin_user,verified_at=timezone.now())
        self.assertFalse(has_verified_nas_evidence(self.report))
    def test_missing_review_note_rejected(self):
        e=self.evidence()
        with self.assertRaises(ValidationError): review_evidence(e.pk,self.admin_user,"verify"," ")
    def test_nas_page_blocks_out_of_scope_access(self):
        self.client.force_login(self.admin_user)
        with patch("monthly_report.nas_admin.can_access_report",return_value=False):
            self.assertEqual(self.client.get(self.url()).status_code,403)
    def test_cross_report_location_is_rejected(self):
        from .tests import MonthlyRiskReportAdminTests
        other=MonthlyRiskReportAdminTests._report(self,"OTHER NAS")
        with self.assertRaises(ValidationError): self.evidence(report=other)
