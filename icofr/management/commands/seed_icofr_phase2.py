from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

from icofr.models import ICoFRQuestion, RCMType


DEFAULT_QUESTIONS = [
    "Apakah terdapat perubahan pada dokumen pendukung?",
    "Apakah terdapat penambahan terhadap kontrol kompensasi terkait control yang ada?",
    "Apakah terdapat perubahan pada atribut control?",
    "Apakah terdapat perubahan jabatan pada control reviewer?",
    "Apakah terdapat perubahan jabatan pada control preparer?",
    "Apakah terdapat perubahan pada aplikasi pendukung pada control yang ada?",
    "Apakah terdapat perubahan frekuensi pada control yang ada?",
    "Apakah terdapat perubahan deskripsi lokasi pada control yang ada?",
    "Apakah terdapat perubahan pada deskripsi control yang ada?",
    "Apakah terdapat perubahan pada proses bisnis yang ada?",
    "Apakah terdapat perubahan pada tujuan control yang ada?",
]


class Command(BaseCommand):
    help = "Create/update Phase 2 ICoFR roles and seed default questionnaire masters."

    def _permissions(self, codenames):
        return Permission.objects.filter(
            content_type__app_label="icofr",
            codename__in=codenames,
        )

    def handle(self, *args, **options):
        admin_group, _ = Group.objects.get_or_create(name="ROLE - ICOFR ADMIN")
        admin_permissions = Permission.objects.filter(content_type__app_label="icofr")
        admin_group.permissions.set(admin_permissions)

        preparer_group, _ = Group.objects.get_or_create(name="ROLE - ICOFR LINE 1 PREPARER")
        preparer_codes = {
            "view_icofrperiod",
            "view_rcmset", "view_rcmrisk", "view_rcmcontrol", "view_rcmentry",
            "view_icofrschedule", "view_icofrworkitem",
            "view_icofrquestion",
            "view_questionnairesubmission", "change_questionnairesubmission",
            "view_questionnaireanswer", "change_questionnaireanswer",
            "add_questionnaireevidence", "change_questionnaireevidence", "delete_questionnaireevidence", "view_questionnaireevidence",
            "view_csaineffectivenesscategory",
            "view_csaassessment", "change_csaassessment", "view_csaassessmentreviewlog",
            "add_csasample", "change_csasample", "delete_csasample", "view_csasample",
            "add_csasampleattributeresult", "change_csasampleattributeresult", "delete_csasampleattributeresult", "view_csasampleattributeresult",
            "add_csaevidence", "change_csaevidence", "delete_csaevidence", "view_csaevidence",
            "view_rcmcontrolattribute", "view_rcmsupportingdocument",
        }
        preparer_group.permissions.set(self._permissions(preparer_codes))

        reviewer_group, _ = Group.objects.get_or_create(name="ROLE - ICOFR LINE 1 REVIEWER")
        reviewer_codes = {
            "view_icofrperiod",
            "view_rcmset", "view_rcmrisk", "view_rcmcontrol", "view_rcmentry",
            "view_icofrschedule", "view_icofrworkitem",
            "view_csaineffectivenesscategory",
            "view_csaassessment", "change_csaassessment", "view_csaassessmentreviewlog",
            "view_csasample", "view_csasampleattributeresult", "view_csaevidence",
            "view_rcmcontrolattribute", "view_rcmsupportingdocument",
        }
        reviewer_group.permissions.set(self._permissions(reviewer_codes))

        created = 0
        for rcm_type in RCMType.values:
            for sequence, question in enumerate(DEFAULT_QUESTIONS, start=1):
                _, was_created = ICoFRQuestion.objects.get_or_create(
                    rcm_type=rcm_type,
                    sequence=sequence,
                    defaults={"question": question, "is_active": True},
                )
                created += int(was_created)

        self.stdout.write(
            self.style.SUCCESS(
                f"{admin_group.name}: {admin_permissions.count()} permissions; "
                f"{preparer_group.name}: {preparer_group.permissions.count()}; "
                f"{reviewer_group.name}: {reviewer_group.permissions.count()}; "
                f"default questionnaire created: {created}."
            )
        )
