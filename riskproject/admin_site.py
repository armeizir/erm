from django.contrib.admin import AdminSite
from django.contrib.auth.models import Group, User
from django.urls import reverse
from monthly_report.models import MonthlyRiskReport

from risk.models import (
    KontrakManajemen,
    BagianKontrakManajemen,
    ItemKontrakManajemen,
    RKAPItem,
    RKMSummary,
    RKMItem,
    ReAssessmentSummary,
    ReAssessmentItem,
    KPMRSummary,
    KPMRItem,
    ProfilRisikoKorporatSummary,
    ProfilRisikoKorporatItem,
    ProfilRisikoKorporatSumber,
    KategoriRisiko,
    MasterJenisExistingControl,
    MasterEfektivitasKontrol,
    MasterKategoriDampak,
    MasterJenisProgramRKAP,
    MasterJenisRencanaPerlakuanRisiko,
    MasterLevelRisiko,
    MasterOpsiPerlakuanRisiko,
    MasterPosAnggaran,
    MasterSkalaDampak,
    MasterSkalaProbabilitas,
    RiskMatrix,
    SasaranKBUMN,
    TaksonomiT3,
)


class RiskAdminSite(AdminSite):
    site_header = "Manajemen Risiko PLN Batam"
    site_title = "Manajemen Risiko PLN Batam"
    index_title = "Dashboard Enterprise"

    def index(self, request, extra_context=None):
        extra_context = extra_context or {}

        stats = {
            "rkap": RKAPItem.objects.count(),
            "corporate": ProfilRisikoKorporatSummary.objects.count(),
            "km": KontrakManajemen.objects.count(),
            "rkm": RKMSummary.objects.count(),
            "reassessment": ReAssessmentSummary.objects.count(),
            "kpmr": KPMRSummary.objects.count(),
            "monthly_report": MonthlyRiskReport.objects.count(),
            "users": User.objects.count(),
            "units": Group.objects.count(),
            "masters": (
                KategoriRisiko.objects.count()
                + MasterJenisExistingControl.objects.count()
                + MasterEfektivitasKontrol.objects.count()
                + MasterKategoriDampak.objects.count()
                + MasterJenisProgramRKAP.objects.count()
                + MasterJenisRencanaPerlakuanRisiko.objects.count()
                + MasterLevelRisiko.objects.count()
                + MasterOpsiPerlakuanRisiko.objects.count()
                + MasterPosAnggaran.objects.count()
                + MasterSkalaDampak.objects.count()
                + MasterSkalaProbabilitas.objects.count()
                + RiskMatrix.objects.count()
                + SasaranKBUMN.objects.count()
                + TaksonomiT3.objects.count()
            ),
        }

        sections = [
            {
                "title": "RKAP",
                "color": "teal",
                "count": stats["rkap"],
                "items": [
                    {"label": "RKAP Item", "url": "/admin/risk/rkapitem/"},
                ],
            },
            {
                "title": "Profil Risiko Korporat",
                "color": "corporate",
                "count": stats["corporate"],
                "items": [
                    {"label": "Profil Risiko Korporat", "url": "/admin/risk/profilrisikokorporatsummary/"},
                    {"label": "Item Risiko Korporat", "url": "/admin/risk/profilrisikokorporatitem/"},
                    {"label": "Sumber Risiko Korporat", "url": "/admin/risk/profilrisikokorporatsumber/"},
                ],
            },
            {
                "title": "Kontrak Manajemen (KM)",
                "color": "km",
                "count": stats["km"],
                "items": [
                    {"label": "Kontrak Manajemen", "url": "/admin/risk/kontrakmanajemen/"},
                    {"label": "Bagian Kontrak Manajemen", "url": "/admin/risk/bagiankontrakmanajemen/"},
                    {"label": "Item Kontrak Manajemen", "url": "/admin/risk/itemkontrakmanajemen/"},
                ],
            },
            {
                "title": "Rencana Kerja Manajemen (RKM)",
                "color": "rkm",
                "count": stats["rkm"],
                "items": [
                    {"label": "RKM Unit/Bidang", "url": "/admin/risk/rkmsummary/"},
                    {"label": "Item RKM", "url": "/admin/risk/rkmitem/"},
                ],
            },
            {
                "title": "Profil Risiko Bidang/Unit Bisnis",
                "color": "reassessment",
                "count": stats["reassessment"],
                "items": [
                    {"label": "Profil Risiko Unit/Bidang", "url": "/admin/risk/reassessmentsummary/"},
                    {"label": "Item Risiko Unit/Bidang", "url": "/admin/risk/reassessmentitem/"},
                ],
            },
            {
                "title": "Laporan Risiko Bulanan",
                "color": "orange",
                "count": stats["monthly_report"],
                "items": [
                    {
                        "label": "Laporan Risiko Bulanan",
                        "url": reverse("risk_admin:monthly_report_monthlyriskreport_changelist"),
                    },
                    {
                        "label": "Item Laporan Risiko",
                        "url": reverse("risk_admin:monthly_report_monthlyriskreportitem_changelist"),
                    },
                    {
                        "label": "Kesesuaian KM",
                        "url": reverse("risk_admin:monthly_report_monthlyriskreportkmalignment_changelist"),
                    },
                ],
            },
            {
                "title": "KPMR",
                "color": "kpmr",
                "count": stats["kpmr"],
                "items": [
                    {"label": "KPMR Unit/Bidang", "url": "/admin/risk/kpmrsummary/"},
                    {"label": "Item KPMR", "url": "/admin/risk/kpmritem/"},
                ],
            },
            {
                "title": "Master Data Risiko",
                "color": "master",
                "count": stats["masters"],
                "items": [
                    {"label": "Taksonomi T3", "url": "/admin/risk/taksonomit3/"},
                    {"label": "Kategori Risiko", "url": "/admin/risk/kategoririsiko/"},
                    {"label": "Sasaran KBUMN", "url": "/admin/risk/sasarankbumn/"},
                    {"label": "Jenis Existing Control", "url": "/admin/risk/masterjenisexistingcontrol/"},
                    {"label": "Penilaian Efektivitas Kontrol", "url": "/admin/risk/masterefektivitaskontrol/"},
                    {"label": "Kategori Dampak", "url": "/admin/risk/masterkategoridampak/"},
                    {"label": "Skala Dampak", "url": "/admin/risk/masterskaladampak/"},
                    {"label": "Skala Probabilitas", "url": "/admin/risk/masterskalaprobabilitas/"},
                    {"label": "Level Risiko", "url": "/admin/risk/masterlevelrisiko/"},
                    {"label": "Matriks Risiko", "url": "/admin/risk/riskmatrix/"},
                    {"label": "Opsi Perlakuan Risiko", "url": "/admin/risk/masteropsiperlakuanrisiko/"},
                    {"label": "Jenis Rencana Perlakuan Risiko", "url": "/admin/risk/masterjenisrencanaperlakuanrisiko/"},
                    {"label": "Pos Anggaran", "url": "/admin/risk/masterposanggaran/"},
                    {"label": "Jenis Program Dalam RKAP", "url": "/admin/risk/masterjenisprogramrkap/"},
                ],
            },
            {
                "title": "Authentication and Authorization",
                "color": "auth",
                "count": stats["users"],
                "items": [
                    {"label": "Bidang / Unit Bisnis", "url": "/admin/auth/group/"},
                    {"label": "Users", "url": "/admin/auth/user/"},
                ],
            },
        ]

        extra_context["dashboard_stats"] = stats
        extra_context["dashboard_sections"] = sections
        return super().index(request, extra_context=extra_context)


risk_admin_site = RiskAdminSite(name="risk_admin")