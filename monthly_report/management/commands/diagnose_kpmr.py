from django.core.management.base import BaseCommand, CommandError

from monthly_report.models import MonthlyRiskReport
from risk.services.kpmr_automation import calculate_kpmr_for_report
from risk.services.kpmr_diagnostics import build_kpmr_diagnostics


class Command(BaseCommand):
    help = "Diagnose target/actual comparison and KPMR fallback for a monthly report."

    def add_arguments(self, parser):
        parser.add_argument("report_id", type=int)

    def handle(self, *args, **options):
        report_id = options["report_id"]
        try:
            report = MonthlyRiskReport.objects.select_related(
                "periode",
                "reassessment",
                "reassessment__unit_bisnis",
                "reassessment__risk_matrix",
            ).get(pk=report_id)
        except MonthlyRiskReport.DoesNotExist as exc:
            raise CommandError(f"MonthlyRiskReport ID {report_id} tidak ditemukan.") from exc

        quarter = ((report.periode.tanggal_mulai.month - 1) // 3) + 1
        diagnostics = build_kpmr_diagnostics(report, quarter=quarter)
        calculation = calculate_kpmr_for_report(report)

        self.stdout.write(f"REPORT: ID={report.pk}; status={report.status}")
        self.stdout.write(
            f"PROFIL: reassessment_id={report.reassessment_id}; "
            f"nama={report.reassessment}; unit={report.reassessment.unit_bisnis}; "
            f"periode={report.periode}; Q{quarter}; matrix={report.reassessment.risk_matrix}"
        )
        self.stdout.write(
            f"RISIKO: rows={len(diagnostics['rows'])}; "
            f"groups={diagnostics['group_count']}"
        )
        self.stdout.write("\nKELOMPOK NO_ITEM:")
        for group in diagnostics["exposure_groups"]:
            self.stdout.write(
                f"- no_item={group['no_item']}; jumlah_risiko={group['risk_count']}; "
                f"target_exposure={group['target']}; actual_exposure={group['actual']}; "
                f"target_source={group['target_source']}; "
                f"actual_source={group['actual_source']}; "
                f"missing={', '.join(group['missing']) or '-'}; "
                f"status={'lengkap' if group['is_complete'] else 'tidak lengkap'}; "
                f"assessable={group['assessable']}; reason={group['reason']}"
            )

        self.stdout.write("\nPER RISIKO:")
        for row in diagnostics["rows"]:
            target_l = row["target_likelihood"] or {}
            target_i = row["target_impact"] or {}
            actual_l = row["actual_likelihood"] or {}
            actual_i = row["actual_impact"] or {}
            self.stdout.write(
                f"- report_item={row['item_id']}; no_item={row['normalized_no_item']}; "
                f"no_risiko={row['no_risiko']}; event={row['event']}\n"
                f"  target: likelihood={target_l.get('label')} rank={target_l.get('rank')}; "
                f"impact={target_i.get('label')} rank={target_i.get('rank')}; "
                f"score={row['target_score']}\n"
                f"  aktual: likelihood={actual_l.get('label')} rank={actual_l.get('rank')}; "
                f"impact={actual_i.get('label')} rank={actual_i.get('rank')}; "
                f"score={row['actual_score']}\n"
                f"  comparison={row['comparison_label']}; complete={row['is_complete']}; "
                f"missing={', '.join(row['missing']) or '-'}; matrix={row['matrix']}\n"
                f"  source={row['source']}\n"
                f"  legacy ignored: target_residual_level="
                f"{row['legacy_target_residual_level']}; realisasi_skor_risiko="
                f"{row['legacy_actual_score']}"
            )

        counts = diagnostics["counts"]
        self.stdout.write("\nAGREGASI PERBANDINGAN:")
        self.stdout.write(
            f"below={counts['below']}; same={counts['same']}; "
            f"above={counts['above']}; incomplete={counts['incomplete']}"
        )
        self.stdout.write(
            f"complete_exposure_groups={diagnostics['complete_group_count']}/"
            f"{diagnostics['group_count']}; fallback_used={diagnostics['fallback_used']}; "
            f"reason={diagnostics['fallback_reason']}"
        )
        self.stdout.write("\nHASIL KPMR SETELAH AGREGASI:")
        for indicator in calculation.indicators:
            self.stdout.write(
                f"- {indicator['kode']}: answer={indicator['jawaban'] or '-'}; "
                f"raw={indicator['hasil']}; weighted={indicator['skor']}; "
                f"note={indicator['keterangan']}"
            )
        self.stdout.write(
            f"TOTAL={calculation.score_total}; rating={calculation.rating}; "
            f"data_status={calculation.data_status}"
        )
        self.stdout.write("\nKELENGKAPAN NILAI KPMR:")
        self.stdout.write(
            f"is_complete={calculation.is_complete}; "
            f"requires_verification={calculation.requires_verification}; "
            f"assessed_weight={calculation.assessed_weight}; "
            f"unassessed_weight={calculation.unassessed_weight}; "
            f"provisional_score={calculation.provisional_score}; "
            f"normalized_indicative_score={calculation.normalized_indicative_score}; "
            f"final_score_available={calculation.final_score is not None}; "
            f"final_score={calculation.final_score}; "
            f"final_rating_available={calculation.final_rating is not None}; "
            f"final_rating={calculation.final_rating}"
        )
