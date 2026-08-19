from django import forms

from icofr.models import ICoFRSchedule, RCMSet


class RCMUploadForm(forms.Form):
    file = forms.FileField(
        label="File RCM Excel",
        help_text="Format .xlsx. Jenis RCM dan versi akan dideteksi dari workbook.",
    )

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        if not uploaded.name.lower().endswith(".xlsx"):
            raise forms.ValidationError("File harus berformat .xlsx.")
        if uploaded.size > 20 * 1024 * 1024:
            raise forms.ValidationError("Ukuran file maksimal 20 MB.")
        return uploaded


class ICoFRScheduleForm(forms.ModelForm):
    """Form operasional penjadwalan ICoFR.

    Penjadwalan hanya boleh menggunakan RCM yang sudah Final/Locked. Sesuai
    tata kelola ICoFR, jendela yang sudah dijadwalkan boleh diperpanjang tetapi
    tanggal akhirnya tidak boleh dimajukan menjadi lebih awal.
    """

    class Meta:
        model = ICoFRSchedule
        fields = "__all__"
        widgets = {
            "questionnaire_start": forms.DateInput(attrs={"type": "date"}),
            "questionnaire_end": forms.DateInput(attrs={"type": "date"}),
            "line1_start": forms.DateInput(attrs={"type": "date"}),
            "line1_end": forms.DateInput(attrs={"type": "date"}),
            "line2_start": forms.DateInput(attrs={"type": "date"}),
            "line2_end": forms.DateInput(attrs={"type": "date"}),
            "line3_start": forms.DateInput(attrs={"type": "date"}),
            "line3_end": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        final_qs = RCMSet.objects.filter(status=RCMSet.Status.FINAL).order_by("rcm_type", "-imported_at")
        # Existing schedule tetap dapat ditampilkan walaupun status historisnya berubah.
        if self.instance and self.instance.pk and self.instance.rcm_set_id:
            final_qs = RCMSet.objects.filter(pk=self.instance.rcm_set_id) | final_qs
        self.fields["rcm_set"].queryset = final_qs.distinct()

    def clean_rcm_set(self):
        rcm = self.cleaned_data.get("rcm_set")
        if rcm and rcm.status != RCMSet.Status.FINAL:
            raise forms.ValidationError("RCM harus berstatus Final / Locked sebelum dapat dijadwalkan.")
        return rcm

    def clean(self):
        cleaned = super().clean()
        if not self.instance or not self.instance.pk:
            return cleaned

        original = ICoFRSchedule.objects.filter(pk=self.instance.pk).first()
        if not original:
            return cleaned

        for stage, (_, _start_field, end_field) in ICoFRSchedule._STAGE_FIELDS.items():
            old_end = getattr(original, end_field)
            new_end = cleaned.get(end_field)
            if old_end and new_end and new_end < old_end:
                self.add_error(
                    end_field,
                    f"Tanggal akhir {stage.label} yang sudah dijadwalkan tidak boleh dipercepat. "
                    f"Tanggal sebelumnya {old_end:%d-%m-%Y}; jadwal hanya boleh diperpanjang.",
                )
        return cleaned
