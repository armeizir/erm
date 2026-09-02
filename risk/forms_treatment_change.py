from django import forms
from django.db.models import Q

from masterdata.models import OrganizationUnit

from risk.models import ReAssessmentItem
from risk.services.pic import (
    assignment_validation_error,
    effective_assignments,
    permitted_organization_units,
    profile_reference_date,
)


MONTHS = (
    (1, "Jan"),
    (2, "Feb"),
    (3, "Mar"),
    (4, "Apr"),
    (5, "Mei"),
    (6, "Jun"),
    (7, "Jul"),
    (8, "Agu"),
    (9, "Sep"),
    (10, "Okt"),
    (11, "Nov"),
    (12, "Des"),
)


class RiskTreatmentChangeProposalForm(forms.ModelForm):

    alasan_perubahan = forms.CharField(
        label="Alasan Perubahan",
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "placeholder": (
                    "Jelaskan alasan perubahan "
                    "Rencana Perlakuan Risiko."
                ),
            }
        ),
    )

    dampak_perubahan = forms.CharField(
        label="Dampak Perubahan",
        required=False,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": (
                    "Jelaskan dampak terhadap risiko, "
                    "jadwal, biaya, target, atau output."
                ),
            }
        ),
    )

    for _month, _label in MONTHS:
        locals()[f"timeline_{_month}"] = (
            forms.BooleanField(
                required=False,
                label=_label,
            )
        )

    class Meta:
        model = ReAssessmentItem

        fields = (
            "opsi_perlakuan_risiko",
            "jenis_rencana_perlakuan_risiko",
            "rencana_perlakuan_risiko",
            "output_perlakuan_risiko",
            "biaya_perlakuan_risiko",
            "pos_anggaran",
            "prk",
            "jenis_program_dalam_rkap",
            "pic",
            "pic_organization_unit",
            "pic_user_assignment",
            *(
                f"timeline_{month}"
                for month in range(1, 13)
            ),
        )

        widgets = {
            "rencana_perlakuan_risiko":
                forms.Textarea(attrs={"rows": 5}),
            "output_perlakuan_risiko":
                forms.Textarea(attrs={"rows": 4}),
            "pic":
                forms.TextInput(
                    attrs={
                        "placeholder":
                            "PIC legacy/keterangan PIC"
                    }
                ),
        }

    def __init__(
        self,
        *args,
        user=None,
        **kwargs,
    ):
        self.user = user
        super().__init__(*args, **kwargs)

        item = self.instance

        for month, _label in MONTHS:
            self.fields[
                f"timeline_{month}"
            ].initial = bool(
                getattr(
                    item,
                    f"timeline_{month}",
                    0,
                )
            )

        organization_field = self.fields.get(
            "pic_organization_unit"
        )

        if organization_field and user:
            allowed = permitted_organization_units(
                user
            )

            current_org_id = getattr(
                item,
                "pic_organization_unit_id",
                None,
            )

            if current_org_id:
                allowed = (
                    OrganizationUnit.objects
                    .filter(
                        Q(pk=current_org_id)
                        | Q(pk__in=allowed)
                    )
                )

            organization_field.queryset = (
                allowed
                .distinct()
                .order_by(
                    "name",
                    "code",
                )
            )

        selected_org_id = getattr(
            item,
            "pic_organization_unit_id",
            None,
        )

        if self.is_bound:
            selected_org_id = self.data.get(
                self.add_prefix(
                    "pic_organization_unit"
                )
            )

        assignment_field = self.fields.get(
            "pic_user_assignment"
        )

        if assignment_field:
            assignment_field.queryset = (
                assignment_field
                .queryset
                .none()
            )

            if selected_org_id:
                try:
                    organization = (
                        OrganizationUnit.objects
                        .get(pk=selected_org_id)
                    )
                except (
                    OrganizationUnit.DoesNotExist,
                    TypeError,
                    ValueError,
                ):
                    organization = None

                if organization:
                    current_assignment_id = getattr(
                        item,
                        "pic_user_assignment_id",
                        None,
                    )

                    assignment_field.queryset = (
                        effective_assignments(
                            organization,
                            on_date=(
                                profile_reference_date(
                                    item.summary
                                )
                            ),
                            include_assignment_ids=(
                                (
                                    current_assignment_id,
                                )
                                if current_assignment_id
                                else ()
                            ),
                        )
                    )

    def clean(self):
        cleaned = super().clean()

        organization = cleaned.get(
            "pic_organization_unit"
        )
        assignment = cleaned.get(
            "pic_user_assignment"
        )

        if assignment:
            current_assignment_id = getattr(
                self.instance,
                "pic_user_assignment_id",
                None,
            )

            validation_error = (
                assignment_validation_error(
                    assignment,
                    organization,
                    on_date=profile_reference_date(
                        self.instance.summary
                    ),
                    allow_historical=(
                        assignment.pk
                        == current_assignment_id
                    ),
                )
            )

            if validation_error:
                self.add_error(
                    "pic_user_assignment",
                    validation_error,
                )

        return cleaned

    def proposed_changes(self):
        data = self.cleaned_data

        return {
            "opsi_perlakuan_risiko_id":
                (
                    data[
                        "opsi_perlakuan_risiko"
                    ].pk
                    if data.get(
                        "opsi_perlakuan_risiko"
                    )
                    else None
                ),

            "jenis_rencana_perlakuan_risiko_ids":
                sorted(
                    obj.pk
                    for obj in data[
                        "jenis_rencana_perlakuan_risiko"
                    ]
                ),

            "rencana_perlakuan_risiko":
                data.get(
                    "rencana_perlakuan_risiko"
                ),

            "output_perlakuan_risiko":
                data.get(
                    "output_perlakuan_risiko"
                ),

            "biaya_perlakuan_risiko":
                (
                    str(
                        data[
                            "biaya_perlakuan_risiko"
                        ]
                    )
                    if data.get(
                        "biaya_perlakuan_risiko"
                    )
                    is not None
                    else None
                ),

            "pos_anggaran_id":
                (
                    data["pos_anggaran"].pk
                    if data.get("pos_anggaran")
                    else None
                ),

            "prk":
                data.get("prk"),

            "jenis_program_dalam_rkap_id":
                (
                    data[
                        "jenis_program_dalam_rkap"
                    ].pk
                    if data.get(
                        "jenis_program_dalam_rkap"
                    )
                    else None
                ),

            "pic":
                data.get("pic"),

            "pic_organization_unit_id":
                (
                    data[
                        "pic_organization_unit"
                    ].pk
                    if data.get(
                        "pic_organization_unit"
                    )
                    else None
                ),

            "pic_user_assignment_id":
                (
                    data[
                        "pic_user_assignment"
                    ].pk
                    if data.get(
                        "pic_user_assignment"
                    )
                    else None
                ),

            **{
                f"timeline_{month}":
                    (
                        1
                        if data.get(
                            f"timeline_{month}"
                        )
                        else 0
                    )
                for month in range(1, 13)
            },
        }
