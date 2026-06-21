from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from awareness.models import AwarenessCampaign, AwarenessQuestion


QUESTIONS = [
    ("Apa tujuan utama manajemen risiko?", "Menghilangkan seluruh risiko", "Mengidentifikasi, menilai, mengendalikan, dan memantau risiko", "Menghindari seluruh aktivitas bisnis", "Mengganti seluruh keputusan manajemen", "B", "Manajemen risiko bertujuan mengelola ketidakpastian agar tujuan perusahaan tetap tercapai."),
    ("Apa yang dimaksud risk appetite?", "Jumlah risiko yang bersedia diterima organisasi dalam mencapai tujuan", "Seluruh risiko yang harus dihindari", "Risiko yang pasti terjadi", "Kerugian aktual yang sudah terjadi", "A", "Risk appetite adalah tingkat risiko yang masih dapat diterima dalam pencapaian sasaran."),
    ("Apa perbedaan risiko inheren dan residual?", "Risiko inheren adalah risiko sebelum kontrol, residual setelah kontrol", "Risiko inheren adalah risiko kecil, residual risiko besar", "Risiko inheren hanya risiko keuangan", "Risiko residual tidak perlu dimonitor", "A", "Risiko residual adalah sisa risiko setelah kontrol dan mitigasi diterapkan."),
    ("Apa tujuan mitigasi risiko?", "Mengurangi kemungkinan dan/atau dampak risiko", "Menghapus semua kegiatan perusahaan", "Membuat risiko tidak perlu dilaporkan", "Mengganti seluruh prosedur kerja", "A", "Mitigasi dirancang untuk menurunkan kemungkinan, dampak, atau keduanya."),
    ("Apa arti KRI?", "Key Risk Indicator", "Key Revenue Income", "Knowledge Risk Input", "Key Review Instruction", "A", "KRI adalah indikator yang membantu memantau perubahan tingkat risiko."),
    ("Dalam three lines model, risk owner berada pada lini ke berapa?", "Lini pertama", "Lini kedua", "Lini ketiga", "Auditor eksternal", "A", "Risk owner berada pada lini pertama karena mengelola risiko dalam proses bisnis."),
    ("Apa fungsi unit manajemen risiko?", "Memberi kerangka, metodologi, fasilitasi, monitoring, dan pelaporan risiko", "Mengambil alih seluruh keputusan bisnis", "Menghilangkan tanggung jawab risk owner", "Menentukan seluruh keuntungan perusahaan", "A", "Unit manajemen risiko berperan sebagai lini kedua yang memfasilitasi dan memantau pengelolaan risiko."),
    ("Apa yang harus dilakukan jika risiko melebihi risk appetite?", "Dilakukan eskalasi dan rencana mitigasi", "Diabaikan sampai akhir tahun", "Dihapus dari daftar risiko", "Disembunyikan dari laporan", "A", "Risiko di atas appetite perlu dieskalasi dan dimitigasi secara terencana."),
    ("Apa manfaat risk register?", "Mendokumentasikan risiko, penyebab, dampak, kontrol, mitigasi, PIC, dan status", "Menggantikan laporan keuangan", "Menghapus kebutuhan audit", "Menentukan gaji pegawai", "A", "Risk register menjadi catatan utama untuk monitoring dan pelaporan risiko."),
    ("Apa arti kontrol risiko?", "Aktivitas atau mekanisme untuk mencegah, mendeteksi, atau mengurangi risiko", "Proses menghapus data risiko", "Kegiatan promosi perusahaan", "Perubahan struktur organisasi tanpa analisis", "A", "Kontrol risiko membantu menurunkan kemungkinan atau dampak risiko."),
]


class Command(BaseCommand):
    help = "Seed campaign dan soal awareness manajemen risiko dasar."

    def handle(self, *args, **options):
        today = timezone.localdate()
        user = get_user_model().objects.filter(is_superuser=True).first()
        campaign, _ = AwarenessCampaign.objects.update_or_create(
            title="Awareness Manajemen Risiko Dasar 2026",
            defaults={
                "description": "Pembelajaran singkat dan kuis dasar manajemen risiko untuk seluruh user.",
                "topic": "manajemen_risiko",
                "start_date": today,
                "end_date": today + timedelta(days=365),
                "passing_score": 70,
                "max_attempts": 2,
                "time_limit_minutes": 30,
                "is_active": True,
                "created_by": user,
            },
        )

        for index, row in enumerate(QUESTIONS, start=1):
            question, a, b, c, d, correct, explanation = row
            AwarenessQuestion.objects.update_or_create(
                campaign=campaign,
                order=index,
                defaults={
                    "question_text": question,
                    "option_a": a,
                    "option_b": b,
                    "option_c": c,
                    "option_d": d,
                    "correct_answer": correct,
                    "explanation": explanation,
                    "difficulty": "mudah",
                    "weight": 1,
                    "is_active": True,
                },
            )

        self.stdout.write(self.style.SUCCESS(
            f"Seed awareness selesai: {campaign.title} ({campaign.questions.count()} soal)."
        ))
