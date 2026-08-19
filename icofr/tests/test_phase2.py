import tempfile
from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from masterdata.models import OrganizationUnit, OrganizationUnitUserAssignment

from icofr.models import (
    CSAEvidence,
    CSAIneffectivenessCategory,
    CSAAssessment,
    CSAAssessmentReviewLog,
    CSASample,
    ICoFRPeriod,
    ICoFRQuestion,
    ICoFRSchedule,
    ICoFRScheduleUnit,
    ICoFRStage,
    ICoFRWorkItem,
    QuestionnaireSubmission,
    RCMControl,
    RCMControlAttribute,
    RCMEntry,
    RCMMapping,
    RCMRisk,
    RCMSet,
    RCMSupportingDocument,
)
from icofr.services.phase2 import distribute_schedule_stage, ensure_sample_attributes


User = get_user_model()


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="icofr-phase2-tests-"))
class Phase2WorkflowTests(TestCase):
    def setUp(self):
        self.preparer = User.objects.create_user("prep", password="x", is_staff=True)
        self.reviewer = User.objects.create_user("review", password="x", is_staff=True)
        self.admin_user = User.objects.create_user("ico", password="x", is_staff=True)
        self.org = OrganizationUnit.objects.create(code="KP-MRK", name="Kantor Pusat - MRK")
        for user, primary in ((self.preparer, True), (self.reviewer, False)):
            OrganizationUnitUserAssignment.objects.create(
                user=user,
                organization_unit=self.org,
                utama=primary,
                aktif=True,
                tanggal_mulai=date(2026, 1, 1),
            )

        self.rcm = RCMSet.objects.create(rcm_type="TLC", version="P2-TEST")
        self.risk = RCMRisk.objects.create(rcm_set=self.rcm, reference="R.01", description="Risk")
        self.control = RCMControl.objects.create(
            rcm_set=self.rcm,
            reference="C.01",
            objective="Control objective",
            description="Control description",
        )
        self.entry = RCMEntry.objects.create(
            rcm_set=self.rcm,
            risk=self.risk,
            control=self.control,
            source_row_number=1,
            preparer_position="PREPARER",
            reviewer_position="REVIEWER",
            segment="Biaya Operasi",
        )
        self.attribute = RCMControlAttribute.objects.create(entry=self.entry, sequence=1, text="Dokumen ditandatangani")
        self.required_doc = RCMSupportingDocument.objects.create(entry=self.entry, sequence=1, text="BAST")
        self.rcm.finalize(self.admin_user)

        self.mapping = RCMMapping.objects.create(
            entry=self.entry,
            preparer_user=self.preparer,
            reviewer_user=self.reviewer,
            status=RCMMapping.Status.MAPPED,
            mapped_by=self.admin_user,
        )
        self.period = ICoFRPeriod.objects.create(
            year=2026,
            name="Triwulan I s.d. II",
            rcm_type="TLC",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 6, 30),
        )
        self.schedule = ICoFRSchedule.objects.create(
            period=self.period,
            rcm_set=self.rcm,
            questionnaire_active=True,
            questionnaire_start=date(2026, 1, 5),
            questionnaire_end=date(2026, 1, 31),
            line1_active=True,
            line1_start=date(2026, 2, 1),
            line1_end=date(2026, 3, 31),
            created_by=self.admin_user,
        )
        ICoFRScheduleUnit.objects.create(
            schedule=self.schedule,
            organization_unit=self.org,
            questionnaire_active=True,
            line1_active=True,
        )
        self.q1 = ICoFRQuestion.objects.create(
            rcm_type="TLC", sequence=1, question="Apakah terdapat perubahan pada dokumen pendukung?"
        )
        self.q2 = ICoFRQuestion.objects.create(
            rcm_type="TLC", sequence=2, question="Apakah terdapat perubahan pada atribut control?"
        )

    def test_schedule_rejects_mismatched_rcm_type(self):
        elc_period = ICoFRPeriod.objects.create(year=2026, name="ELC Test", rcm_type="ELC")
        schedule = ICoFRSchedule(period=elc_period, rcm_set=self.rcm)
        with self.assertRaises(ValidationError):
            schedule.full_clean()

    def test_questionnaire_distribution_creates_assignment_and_answers(self):
        batch = distribute_schedule_stage(self.schedule, ICoFRStage.QUESTIONNAIRE, user=self.admin_user)
        self.assertEqual(batch.distributed_count, 1)
        self.assertEqual(batch.skipped_count, 0)
        item = ICoFRWorkItem.objects.get(schedule=self.schedule, stage=ICoFRStage.QUESTIONNAIRE)
        self.assertEqual(item.preparer_user, self.preparer)
        self.assertEqual(item.organization_unit, self.org)
        submission = item.questionnaire_submission
        self.assertEqual(submission.answers.count(), 2)

        # Distribution is idempotent.
        distribute_schedule_stage(self.schedule, ICoFRStage.QUESTIONNAIRE, user=self.admin_user)
        self.assertEqual(ICoFRWorkItem.objects.filter(schedule=self.schedule, stage=ICoFRStage.QUESTIONNAIRE).count(), 1)

    def test_questionnaire_without_change_finishes(self):
        distribute_schedule_stage(self.schedule, ICoFRStage.QUESTIONNAIRE, user=self.admin_user)
        submission = QuestionnaireSubmission.objects.get()
        submission.answers.update(answer=False)
        submission.submit()
        submission.refresh_from_db()
        self.assertEqual(submission.status, QuestionnaireSubmission.Status.FINISH)
        self.assertEqual(submission.work_item.status, ICoFRWorkItem.Status.FINISHED)

    def test_questionnaire_change_becomes_requested_then_approved(self):
        distribute_schedule_stage(self.schedule, ICoFRStage.QUESTIONNAIRE, user=self.admin_user)
        submission = QuestionnaireSubmission.objects.get()
        first, second = list(submission.answers.order_by("question__sequence"))
        first.answer = True
        first.change_description = "Dokumen pendukung berubah menjadi BAST digital."
        first.save()
        second.answer = False
        second.save()
        submission.submit()
        submission.refresh_from_db()
        self.assertEqual(submission.status, QuestionnaireSubmission.Status.REQUESTED)
        submission.approve(self.admin_user)
        submission.refresh_from_db()
        self.assertEqual(submission.status, QuestionnaireSubmission.Status.APPROVED)

    def _line1_assessment(self):
        batch = distribute_schedule_stage(self.schedule, ICoFRStage.LINE1, user=self.admin_user)
        self.assertEqual(batch.distributed_count, 1)
        return CSAAssessment.objects.get()

    def test_line1_distribution_creates_csa_foundation(self):
        assessment = self._line1_assessment()
        self.assertEqual(assessment.status, CSAAssessment.Status.READY)
        self.assertEqual(assessment.work_item.preparer_user, self.preparer)
        self.assertEqual(assessment.work_item.reviewer_user, self.reviewer)

    def test_effective_csa_requires_sample_attributes_and_required_evidence(self):
        assessment = self._line1_assessment()
        assessment.result = CSAAssessment.Result.EFFECTIVE
        assessment.save()
        sample = CSASample.objects.create(
            assessment=assessment,
            description="Transaksi 001",
            result=CSASample.Result.EFFECTIVE,
        )
        ensure_sample_attributes(sample)
        result = sample.attribute_results.get()
        result.is_met = True
        result.save()
        with self.assertRaises(ValidationError):
            assessment.submit()

        CSAEvidence.objects.create(
            assessment=assessment,
            sample=sample,
            supporting_document=self.required_doc,
            evidence_type=CSAEvidence.EvidenceType.SUPPORTING,
            file=SimpleUploadedFile("bast.pdf", b"dummy", content_type="application/pdf"),
            uploaded_by=self.preparer,
        )
        assessment.submit()
        assessment.refresh_from_db()
        self.assertEqual(assessment.status, CSAAssessment.Status.SUBMITTED)
        assessment.approve(self.reviewer)
        assessment.refresh_from_db()
        self.assertEqual(assessment.status, CSAAssessment.Status.APPROVED)

    def test_tat_requires_tat_evidence(self):
        assessment = self._line1_assessment()
        assessment.result = CSAAssessment.Result.TAT
        assessment.save()
        with self.assertRaises(ValidationError):
            assessment.submit()
        CSAEvidence.objects.create(
            assessment=assessment,
            evidence_type=CSAEvidence.EvidenceType.TAT,
            file=SimpleUploadedFile("tat.pdf", b"tat", content_type="application/pdf"),
            uploaded_by=self.preparer,
        )
        assessment.submit()
        assessment.refresh_from_db()
        self.assertEqual(assessment.status, CSAAssessment.Status.SUBMITTED)

    def test_ineffective_csa_requires_category_and_explanation(self):
        assessment = self._line1_assessment()
        assessment.result = CSAAssessment.Result.INEFFECTIVE
        assessment.save()
        sample = CSASample.objects.create(
            assessment=assessment,
            description="Transaksi 002",
            result=CSASample.Result.INEFFECTIVE,
        )
        ensure_sample_attributes(sample)
        attr = sample.attribute_results.get()
        attr.is_met = False
        attr.save()
        CSAEvidence.objects.create(
            assessment=assessment,
            sample=sample,
            supporting_document=self.required_doc,
            file=SimpleUploadedFile("bast-bad.pdf", b"bad", content_type="application/pdf"),
            uploaded_by=self.preparer,
        )
        with self.assertRaises(ValidationError):
            assessment.submit()
        category = CSAIneffectivenessCategory.objects.create(rcm_type="TLC", name="Implementasi")
        assessment.ineffectiveness_category = category
        assessment.ineffectiveness_explanation = "Tanda tangan reviewer belum tersedia."
        assessment.save()
        assessment.submit()
        assessment.refresh_from_db()
        self.assertEqual(assessment.status, CSAAssessment.Status.SUBMITTED)

    def test_line1_distribution_rejects_same_preparer_reviewer(self):
        self.mapping.reviewer_user = self.preparer
        self.mapping.status = RCMMapping.Status.MAPPED
        self.mapping.save(update_fields=("reviewer_user", "status"))
        batch = distribute_schedule_stage(self.schedule, ICoFRStage.LINE1, user=self.admin_user)
        self.assertEqual(batch.distributed_count, 0)
        self.assertEqual(batch.skipped_count, 1)
        self.assertEqual(batch.summary["skip_reasons"].get("Preparer dan Reviewer sama (SoD)"), 1)

    def test_csa_review_round_keeps_immutable_history(self):
        assessment = self._line1_assessment()
        assessment.result = CSAAssessment.Result.TAT
        assessment.save()
        CSAEvidence.objects.create(
            assessment=assessment,
            evidence_type=CSAEvidence.EvidenceType.TAT,
            file=SimpleUploadedFile("tat-round1.pdf", b"tat", content_type="application/pdf"),
            uploaded_by=self.preparer,
        )
        assessment.submit(user=self.preparer)
        assessment.refresh_from_db()
        self.assertEqual(assessment.review_round, 1)
        self.assertEqual(assessment.review_logs.filter(action=CSAAssessmentReviewLog.Action.SUBMIT).count(), 1)

        assessment.reject(self.reviewer, "Dokumen TAT belum ditandatangani.")
        assessment.refresh_from_db()
        self.assertEqual(assessment.status, CSAAssessment.Status.REJECTED)
        self.assertEqual(assessment.review_logs.filter(action=CSAAssessmentReviewLog.Action.REJECT).count(), 1)

        assessment.submit(user=self.preparer)
        assessment.refresh_from_db()
        self.assertEqual(assessment.review_round, 2)
        self.assertEqual(assessment.reviewer_note, "")
        self.assertIsNone(assessment.reviewed_by)
        self.assertEqual(assessment.review_logs.filter(action=CSAAssessmentReviewLog.Action.RESUBMIT).count(), 1)

        assessment.approve(self.reviewer, "Evidence sudah sesuai.")
        assessment.refresh_from_db()
        self.assertEqual(assessment.status, CSAAssessment.Status.APPROVED)
        self.assertEqual(assessment.review_logs.filter(action=CSAAssessmentReviewLog.Action.APPROVE).count(), 1)
        self.assertEqual(assessment.review_logs.count(), 4)

    def test_wrong_reviewer_cannot_approve_or_reject(self):
        other = User.objects.create_user("other-reviewer", password="x", is_staff=True)
        assessment = self._line1_assessment()
        assessment.result = CSAAssessment.Result.TAT
        assessment.save()
        CSAEvidence.objects.create(
            assessment=assessment,
            evidence_type=CSAEvidence.EvidenceType.TAT,
            file=SimpleUploadedFile("tat-auth.pdf", b"tat", content_type="application/pdf"),
            uploaded_by=self.preparer,
        )
        assessment.submit(user=self.preparer)
        with self.assertRaises(ValidationError):
            assessment.approve(other)
        with self.assertRaises(ValidationError):
            assessment.reject(other, "Tidak berwenang")

    def test_work_item_open_routes_preparer_to_csa_form_and_reviewer_to_review(self):
        assessment = self._line1_assessment()
        item = assessment.work_item

        self.client.force_login(self.preparer)
        response = self.client.get(reverse("risk_admin:icofr_workitem_open", args=[item.pk]))
        self.assertRedirects(
            response,
            reverse("risk_admin:icofr_csaassessment_change", args=[assessment.pk]),
            fetch_redirect_response=False,
        )

        assessment.result = CSAAssessment.Result.TAT
        assessment.save(update_fields=("result", "updated_at"))
        CSAEvidence.objects.create(
            assessment=assessment,
            evidence_type=CSAEvidence.EvidenceType.TAT,
            file=SimpleUploadedFile("tat-open.pdf", b"tat", content_type="application/pdf"),
            uploaded_by=self.preparer,
        )
        assessment.submit(user=self.preparer)

        self.client.force_login(self.reviewer)
        response = self.client.get(reverse("risk_admin:icofr_workitem_open", args=[item.pk]))
        self.assertRedirects(
            response,
            reverse("risk_admin:icofr_csa_review", args=[assessment.pk]),
            fetch_redirect_response=False,
        )

    def test_preparer_change_form_is_workflow_oriented(self):
        assessment = self._line1_assessment()
        self.preparer.is_superuser = True
        self.preparer.save(update_fields=("is_superuser",))
        self.client.force_login(self.preparer)
        response = self.client.get(reverse("risk_admin:icofr_csaassessment_change", args=[assessment.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Informasi Kontrol")
        self.assertContains(response, "Simpan Draft")
        self.assertContains(response, "Simpan & Kirim ke Reviewer")
        self.assertNotContains(response, "Save and add another")

    def test_distribution_preview_is_side_effect_free_and_matches_readiness(self):
        from icofr.services.phase2 import preview_schedule_stage

        preview = preview_schedule_stage(self.schedule, ICoFRStage.LINE1)
        self.assertEqual(preview["total_entries"], 1)
        self.assertEqual(preview["ready_count"], 1)
        self.assertEqual(preview["to_create_count"], 1)
        self.assertEqual(preview["skipped_count"], 0)
        self.assertFalse(ICoFRWorkItem.objects.filter(schedule=self.schedule, stage=ICoFRStage.LINE1).exists())

    def test_schedule_form_rejects_shortening_existing_window(self):
        from icofr.forms import ICoFRScheduleForm

        data = {
            "period": self.period.pk,
            "rcm_set": self.rcm.pk,
            "questionnaire_active": True,
            "questionnaire_start": "2026-01-05",
            "questionnaire_end": "2026-01-20",
            "line1_active": True,
            "line1_start": "2026-02-01",
            "line1_end": "2026-03-31",
            "notes": "",
        }
        form = ICoFRScheduleForm(data=data, instance=self.schedule)
        self.assertFalse(form.is_valid())
        self.assertIn("questionnaire_end", form.errors)

    def test_distribution_preview_page_then_post_redirects_to_work_items(self):
        self.admin_user.is_superuser = True
        self.admin_user.is_staff = True
        self.admin_user.save(update_fields=("is_superuser", "is_staff"))
        self.client.force_login(self.admin_user)
        url = reverse("risk_admin:icofr_schedule_distribute", args=[self.schedule.pk, ICoFRStage.LINE1])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Pre-flight Distribusi")
        self.assertContains(response, "Akan Dibuat")
        self.assertFalse(ICoFRWorkItem.objects.filter(schedule=self.schedule, stage=ICoFRStage.LINE1).exists())

        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("schedule__id__exact", response["Location"])
        self.assertTrue(ICoFRWorkItem.objects.filter(schedule=self.schedule, stage=ICoFRStage.LINE1).exists())
