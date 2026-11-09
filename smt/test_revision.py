from datetime import date, timedelta
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from masterdata.models import OrganizationUnit
from .models import Document, Attachment
from .revision import create_revision, activate_revision

class RevisionTests(TestCase):
    def setUp(self):
        self.unit = OrganizationUnit.objects.create(code="SMT-REV-TEST", name="Unit SMT")
        self.source = Document.objects.create(jenis="PI", nomor="PI-REV-TEST", judul="Prosedur",
            unit_pemilik=self.unit, revisi="05", status="active", tanggal_berlaku=None,
            tujuan="<p>Isi final</p>", catatan_revisi="Catatan lama")
        self.user = get_user_model().objects.create_superuser("smt_revision_admin", "test@example.com", "test")
        self.client.force_login(self.user)

    def url(self, action, obj=None):
        return reverse("risk_admin:smt_prosedurintegrasi_" + action,
                       args=[(obj or self.source).pk])

    def test_duplicate_preserves_source_and_resets_new_fields(self):
        old = Document.objects.filter(pk=self.source.pk).values().get()
        target, created = create_revision(self.source.pk)
        self.assertTrue(created)
        self.assertEqual(target.revisi, "06")
        self.assertEqual(target.status, "draft")
        self.assertEqual(target.tujuan, self.source.tujuan)
        self.assertEqual(target.revisi_sebelumnya_id, self.source.pk)
        self.assertIsNone(target.tanggal_berlaku)
        self.assertEqual(target.catatan_revisi, "")
        self.assertEqual(old, Document.objects.filter(pk=self.source.pk).values().get())

    def test_repeated_click_reuses_same_draft(self):
        first, _ = create_revision(self.source.pk)
        second, created = create_revision(self.source.pk)
        self.assertFalse(created)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Document.objects.count(), 2)

    def test_final_attachments_are_not_copied(self):
        Attachment.objects.create(document=self.source, nama="Pengesahan", jenis="pengesahan", berkas="archive.pdf")
        target, _ = create_revision(self.source.pk)
        self.assertFalse(target.lampiran.exists())
        self.assertEqual(self.source.lampiran.get().berkas.name, "archive.pdf")

    def test_draft_cannot_be_duplicated(self):
        target, _ = create_revision(self.source.pk)
        with self.assertRaises(ValidationError): create_revision(target.pk)

    def test_nonnumeric_revision_rejected(self):
        Document.objects.filter(pk=self.source.pk).update(revisi="A")
        with self.assertRaises(ValidationError): create_revision(self.source.pk)
        self.assertEqual(Document.objects.count(), 1)

    def test_other_pending_revision_blocks_creation(self):
        Document.objects.create(jenis="PI", nomor=self.source.nomor, judul="Pending",
            unit_pemilik=self.unit, revisi="06")
        with self.assertRaises(ValidationError): create_revision(self.source.pk)

    def test_activate_retires_old_without_changing_content(self):
        target, _ = create_revision(self.source.pk)
        target, previous = activate_revision(target.pk, timezone.localdate())
        self.source.refresh_from_db()
        self.assertEqual(self.source.status, "retired")
        self.assertEqual(self.source.tujuan, "<p>Isi final</p>")
        self.assertIsNone(self.source.tanggal_berlaku)
        self.assertEqual(target.status, "active")
        self.assertEqual(previous.pk, self.source.pk)
        self.assertEqual(Document.objects.filter(nomor=self.source.nomor,status="active").count(), 1)
        third, _ = create_revision(target.pk)
        self.assertEqual(third.revisi, "07")

    def test_invalid_activation_rolls_back_retirement(self):
        target, _ = create_revision(self.source.pk)
        Document.objects.filter(pk=target.pk).update(judul="")
        with self.assertRaises(ValidationError): activate_revision(target.pk, timezone.localdate())
        self.source.refresh_from_db()
        self.assertEqual(self.source.status, "active")

    def test_future_date_rejected(self):
        target, _ = create_revision(self.source.pk)
        with self.assertRaises(ValidationError):
            activate_revision(target.pk, timezone.localdate()+timedelta(days=1))
        self.source.refresh_from_db()
        self.assertEqual(self.source.status, "active")

    def test_get_is_readonly_and_post_creates_with_audit(self):
        response=self.client.get(self.url("revision"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Document.objects.count(), 1)
        response=self.client.post(self.url("revision"))
        self.assertEqual(response.status_code, 302)
        from django.contrib.admin.models import LogEntry
        self.assertTrue(LogEntry.objects.filter(user=self.user, action_flag=1).exists())

    def test_view_only_cannot_duplicate_or_activate(self):
        target, _ = create_revision(self.source.pk)
        viewer=get_user_model().objects.create_user("smt_revision_viewer",is_staff=True)
        viewer.user_permissions.add(Permission.objects.get(content_type__app_label="smt",codename="view_prosedurintegrasi"))
        self.client.force_login(viewer)
        self.assertEqual(self.client.post(self.url("revision")).status_code,403)
        self.assertEqual(self.client.post(self.url("activate",target),{"tanggal_berlaku":"2026-01-01"}).status_code,403)

    def test_active_page_is_readonly_and_ik_route_rejects_pi(self):
        response=self.client.get(self.url("change"))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,"Buat Revisi Baru")
        self.assertNotContains(response,'name="_save"')
        wrong=reverse("risk_admin:smt_instruksikerja_revision",args=[self.source.pk])
        self.assertEqual(self.client.post(wrong).status_code,404)

    def test_activation_post_logs_both_versions(self):
        target, _ = create_revision(self.source.pk)
        response=self.client.post(self.url("activate",target),{"tanggal_berlaku":timezone.localdate().isoformat()})
        self.assertEqual(response.status_code,302)
        from django.contrib.admin.models import LogEntry
        self.assertEqual(LogEntry.objects.filter(user=self.user,action_flag=2).count(),2)

    def test_csrf_required(self):
        from django.test import Client
        client=Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(client.post(self.url("revision")).status_code,403)

    def test_renumbered_revision_retires_original_and_keeps_history(self):
        target, _ = create_revision(self.source.pk)
        target.nomor = "PI-MRK-TEST"
        target.save(update_fields=["nomor"])
        target, old = activate_revision(target.pk, timezone.localdate())
        self.source.refresh_from_db()
        self.assertEqual(self.source.nomor, "PI-REV-TEST")
        self.assertEqual(self.source.status, "retired")
        self.assertEqual(target.nomor, "PI-MRK-TEST")
        from .admin import ProsedurIntegrasiAdmin
        from .models import ProsedurIntegrasi
        from riskproject.admin_site import risk_admin_site
        history=ProsedurIntegrasiAdmin(ProsedurIntegrasi,risk_admin_site).riwayat_revisi(target)
        self.assertIn("PI-REV-TEST", history)
        self.assertIn("PI-MRK-TEST", history)
        next_draft, _=create_revision(target.pk)
        self.assertEqual(next_draft.revisi, "07")

    def test_renumbering_to_existing_active_number_is_rejected(self):
        target, _ = create_revision(self.source.pk)
        Document.objects.create(jenis="PI",nomor="PI-OTHER",revisi="01",judul="Other",
            unit_pemilik=self.unit,status="active",tanggal_berlaku=timezone.localdate())
        target.nomor="PI-OTHER"
        target.save(update_fields=["nomor"])
        with self.assertRaises(ValidationError): activate_revision(target.pk,timezone.localdate())
        self.source.refresh_from_db()
        self.assertEqual(self.source.status,"active")
