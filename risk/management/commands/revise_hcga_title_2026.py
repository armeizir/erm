"""One approved title correction. Dry run by default; apply only on local Mac."""
import json
import os
import sqlite3
from datetime import date, datetime
from pathlib import Path

from django.conf import settings
from django.contrib.admin.models import CHANGE, LogEntry
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from monthly_report.models import MonthlyRiskReportItem
from risk.models import ReAssessmentItem, RiskTreatmentChangeRequest

OLD = "Sinergi Tenaga Alih Daya dengan Anak Perusahaan tidak tercapai"
NEW = "Sinergi Anak Perusahaan Tidak Tercapai"
START, END, CUTOFF = date(2026, 10, 1), date(2026, 12, 31), date(2026, 9, 30)


def make_plan(source_id):
    old = ReAssessmentItem.objects.select_related("summary__unit_bisnis").get(pk=source_id)
    if (old.summary.tahun != 2026 or old.summary.unit_bisnis.name != "BID HCGA"
            or old.no_item != 10 or old.peristiwa_risiko.casefold() != OLD.casefold()):
        raise CommandError("Identitas sumber berbeda; tidak ada perubahan.")
    if old.valid_from and old.valid_from > CUTOFF:
        raise CommandError("Tanggal mulai sumber tidak sesuai.")
    if old.valid_to not in (None, CUTOFF):
        raise CommandError("Tanggal akhir sumber tidak sesuai.")
    siblings = ReAssessmentItem.objects.filter(
        summary_id=old.summary_id, no_item=old.no_item, no_risiko=old.no_risiko,
    ).exclude(pk=old.pk)
    versions = list(siblings)
    new = next((r for r in versions if r.peristiwa_risiko == NEW
                and r.valid_from == START and r.valid_to == END and r.is_active), None)
    if len(versions) > (1 if new else 0):
        raise CommandError("Ada versi lain pada identitas risiko ini; perlu pemeriksaan.")
    if not new and not old.is_active:
        raise CommandError("Sumber tidak aktif dan versi baru belum ditemukan.")
    if new and (old.is_active or old.valid_to != CUTOFF):
        raise CommandError("Metadata versi lama dan baru tidak konsisten.")
    if RiskTreatmentChangeRequest.objects.filter(
        reassessment_item=old,
        status__in=RiskTreatmentChangeRequest.OPEN_STATUSES,
    ).exists():
        raise CommandError("Masih ada usulan perlakuan terbuka pada sumber.")
    rows = list(MonthlyRiskReportItem.objects.filter(risk_event=old)
                .select_related("report__periode").order_by("pk"))
    targets = []
    for row in rows:
        report = row.report
        if report.reassessment_id != old.summary_id:
            raise CommandError("Ada laporan dengan profil sumber berbeda.")
        start = report.periode.tanggal_mulai
        end = report.periode.tanggal_selesai or start
        if start <= END and end >= START:
            if start < START or end > END:
                raise CommandError("Periode laporan melintasi batas revisi.")
            if report.status not in {"draft", "revision"} or report.is_locked:
                raise CommandError(f"Laporan #{report.pk} sudah terkunci/diproses; buka revisi resmi dahulu.")
            if new and report.items.filter(risk_event=new).exists():
                raise CommandError("Laporan memiliki kedua versi sekaligus.")
            targets.append(row)
        elif start > END:
            raise CommandError("Sumber dipakai setelah Desember 2026; perlu pemeriksaan.")
    return old, new, targets


@transaction.atomic
def apply_revision(source_id, actor):
    ReAssessmentItem.objects.select_for_update().get(pk=source_id)
    old, new, targets = make_plan(source_id)
    # Lock report headers and items before a second validation.
    from monthly_report.models import MonthlyRiskReport
    report_ids = {row.report_id for row in targets}
    list(MonthlyRiskReport.objects.select_for_update().filter(pk__in=report_ids))
    list(MonthlyRiskReportItem.objects.select_for_update().filter(risk_event=old))
    old, new, targets = make_plan(source_id)
    if new is None:
        values = {f.attname: getattr(old, f.attname)
                  for f in old._meta.concrete_fields if not f.primary_key}
        values.update(peristiwa_risiko=NEW, valid_from=START, valid_to=END, is_active=True)
        m2m = {}
        for field in old._meta.many_to_many:
            if not field.remote_field.through._meta.auto_created:
                raise CommandError("Relasi M2M khusus memerlukan penyalinan terpisah.")
            m2m[field.name] = list(getattr(old, field.name).values_list("pk", flat=True))
        ReAssessmentItem.objects.filter(pk=old.pk).update(is_active=False, valid_to=CUTOFF)
        new = ReAssessmentItem(**values)
        # Preserve exact planning values: save() recalculates quarterly scores.
        ReAssessmentItem.objects.bulk_create([new])
        if new.pk is None:
            raise CommandError("Database tidak mengembalikan ID versi baru.")
        for name, ids in m2m.items():
            getattr(new, name).set(ids)
        new.refresh_from_db()
        for name, expected in values.items():
            if getattr(new, name) != expected:
                raise CommandError(f"Nilai hasil salinan berbeda: {name}")
        LogEntry.objects.create(
            user_id=actor.pk, content_type=ContentType.objects.get_for_model(new),
            object_id=str(new.pk), object_repr=str(new)[:200], action_flag=CHANGE,
            change_message=json.dumps({"operation": "hcga_title_revision_oct_dec_2026",
                                      "source_id": old.pk, "old_title": OLD,
                                      "new_title": NEW}),
        )
    changed = []
    for row in targets:
        before = {f.attname: getattr(row, f.attname) for f in row._meta.concrete_fields}
        count = MonthlyRiskReportItem.objects.filter(pk=row.pk, risk_event=old).update(risk_event=new)
        if count != 1:
            raise CommandError("Item berubah selama revisi; dibatalkan.")
        row.refresh_from_db()
        for name, expected in before.items():
            if name != "risk_event_id" and getattr(row, name) != expected:
                raise CommandError(f"Snapshot bulanan berubah: {name}")
        changed.append(row.pk)
    return {"operation": "hcga_title_revision_oct_dec_2026", "source_id": old.pk,
            "new_id": new.pk, "old_title": old.peristiwa_risiko, "new_title": NEW,
            "valid_from": str(START), "valid_to": str(END), "monthly_item_ids": changed}


class Command(BaseCommand):
    help = "Simulasi revisi judul HCGA No.10; --apply hanya untuk database lokal Mac."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--actor")

    def handle(self, *args, **options):
        candidates = list(ReAssessmentItem.objects.filter(
            summary__tahun=2026, summary__unit_bisnis__name="BID HCGA",
            no_item=10, peristiwa_risiko__iexact=OLD,
        ).values_list("pk", flat=True))
        if len(candidates) != 1:
            raise CommandError("Sumber harus tepat satu; ditemukan: " + str(candidates))
        old, new, targets = make_plan(candidates[0])
        self.stdout.write(f"SUMBER: {old.pk} | {old.peristiwa_risiko}")
        self.stdout.write(f"JUDUL BARU: {NEW} | {START} s.d. {END}")
        self.stdout.write(f"VERSI BARU SUDAH ADA: {new.pk if new else '-'}")
        for row in targets:
            self.stdout.write(f"LAPORAN: {row.report_id} | ITEM: {row.pk} | {row.report.status}")
        if not options["apply"]:
            self.stdout.write("SIMULASI: database tidak diubah.")
            return
        config = settings.DATABASES["default"]
        db = Path(config["NAME"]).resolve()
        local = Path("/Users/armeizir/risk_app/riskproject").resolve()
        if config["ENGINE"] != "django.db.backends.sqlite3" or not db.is_relative_to(local) or not db.is_file():
            raise CommandError("--apply paket ini hanya untuk SQLite proyek lokal Mac, bukan prod.")
        if not options["actor"]:
            raise CommandError("--actor wajib untuk pencatatan perubahan.")
        users = list(get_user_model().objects.filter(username__iexact=options["actor"], is_active=True, is_staff=True))
        if len(users) != 1:
            raise CommandError("Akun pencatat aktif/staff harus tepat satu.")
        if new and not targets:
            self.stdout.write("SUDAH TERPASANG: tidak ada perubahan ulang.")
            return
        folder = local / "backups"
        folder.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup = folder / f"before_hcga_title_{stamp}.sqlite3"
        fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as src, sqlite3.connect(backup) as dest:
            src.backup(dest)
            if dest.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise CommandError("Backup tidak lolos pemeriksaan.")
        self.stdout.write(f"BACKUP: {backup}")
        result = apply_revision(old.pk, users[0])
        audit = folder / f"hcga_title_result_{stamp}.json"
        with audit.open("x") as stream:
            os.chmod(audit, 0o600)
            json.dump(result, stream, indent=2, ensure_ascii=False)
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
        self.stdout.write("PASS: revisi lokal tersimpan. Laporan sebelum Oktober tetap memakai judul lama.")
