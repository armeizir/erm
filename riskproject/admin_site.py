from django.contrib.admin import AdminSite
from django.contrib.auth.models import Group, User
from django.urls import reverse
from masterdata.models import (
    BusinessArea,
    CompanyCode,
    Directorate,
    Division,
    OrganizationUnit,
    PersonnelArea,
    PersonnelSubArea,
)
from monthly_report.models import (
    MonthlyRiskReport,
    MonthlyRiskReportChange,
    MonthlyRiskReportItem,
    MonthlyRiskReportKMAlignment,
    MonthlyRiskReportLossEvent,
    MonthlyRiskReportSubmissionLog,
)
from corporate_risk.models import (
    MonteCarloMetricHistory,
    MultiMetricAIInsightKorporat,
    MultiMetricMonteCarloResult,
    RiskMetric,
)

from risk.models import (
    AppSetting,
    KontrakManajemen,
    BagianKontrakManajemen,
    ItemKontrakManajemen,
    MasterTemplateKM,
    MasterBagianKM,
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

    def each_context(self, request):
        context = super().each_context(request)
        app_setting = AppSetting.get_solo()
        self.site_header = app_setting.nama_aplikasi
        self.site_title = app_setting.nama_aplikasi
        context["app_setting"] = app_setting
        context["sidebar_sections"] = self._sidebar_sections(request)
        return context

    def _sidebar_sections(self, request):
        allowed_urls = {
            model["admin_url"]
            for app in self.get_app_list(request)
            for model in app.get("models", [])
            if model.get("admin_url")
        }
        allowed_urls.add("/corporate-risk/metric-history-input/")

        def item(label, url):
            return {"label": label, "url": url}

        sections = [
            {
                "level": "Strategic Level",
                "groups": [
                    {
                        "title": "RKAP",
                        "items": [
                            item("RKAP Item", "/admin/risk/rkapitem/"),
                        ],
                    },
                    {
                        "title": "Profil Risiko Korporat",
                        "items": [
                            item("Profil Risiko Korporat", "/admin/risk/profilrisikokorporatsummary/"),
                            item("Item Risiko Korporat", "/admin/risk/profilrisikokorporatitem/"),
                            item("Sumber Risiko Korporat", "/admin/risk/profilrisikokorporatsumber/"),
                        ],
                    },
                    {
                        "title": "Monte Carlo Korporat",
                        "items": [
                            item("Input Histori / Upload Excel", "/corporate-risk/metric-history-input/"),
                            item("Risk Metrics", "/admin/corporate_risk/riskmetric/"),
                            item("Metric History", "/admin/corporate_risk/montecarlometrichistory/"),
                            item("Multi Metric Monte Carlo Results", "/admin/corporate_risk/multimetricmontecarloresult/"),
                            item("Multi Metric AI Insight", "/admin/corporate_risk/multimetricaiinsightkorporat/"),
                        ],
                    },
                ],
            },
            {
                "level": "Management Level",
                "groups": [
                    {
                        "title": "Kontrak Manajemen (KM)",
                        "items": [
                            item("Template KM", "/admin/risk/mastertemplatekm/"),
                            item("Kontrak Manajemen Unit/Bidang", "/admin/risk/kontrakmanajemen/"),
                            item("Item Kontrak Manajemen", "/admin/risk/itemkontrakmanajemen/"),
                        ],
                    },
                    {
                        "title": "Rencana Kerja Manajemen (RKM)",
                        "items": [
                            item("RKM Unit/Bidang", "/admin/risk/rkmsummary/"),
                            item("Item RKM", "/admin/risk/rkmitem/"),
                        ],
                    },
                ],
            },
            {
                "level": "Operational Level",
                "groups": [
                    {
                        "title": "Profil Risiko Bidang/Unit Bisnis",
                        "items": [
                            item("Profil Risiko Unit/Bidang", "/admin/risk/reassessmentsummary/"),
                            item("Item Risiko Unit/Bidang", "/admin/risk/reassessmentitem/"),
                        ],
                    },
                    {
                        "title": "Laporan Risiko Bulanan",
                        "items": [
                            item("Laporan Risiko Bulanan", reverse("risk_admin:monthly_report_monthlyriskreport_changelist")),
                            item("Item Laporan Risiko", reverse("risk_admin:monthly_report_monthlyriskreportitem_changelist")),
                            item("Kesesuaian KM", reverse("risk_admin:monthly_report_monthlyriskreportkmalignment_changelist")),
                            item("III.D - Perubahan Profil/Strategi", reverse("risk_admin:monthly_report_monthlyriskreportchange_changelist")),
                            item("III.E - Loss Event Database", reverse("risk_admin:monthly_report_monthlyriskreportlossevent_changelist")),
                            item("Log Submit/Approval", reverse("risk_admin:monthly_report_monthlyriskreportsubmissionlog_changelist")),
                        ],
                    },
                ],
            },
            {
                "level": "Evaluation Level",
                "groups": [
                    {
                        "title": "KPMR",
                        "items": [
                            item("KPMR Unit/Bidang", "/admin/risk/kpmrsummary/"),
                            item("Item KPMR", "/admin/risk/kpmritem/"),
                        ],
                    },
                ],
            },
            {
                "level": "Support Modules",
                "groups": [
                    {
                        "title": "Master Organisasi",
                        "items": [
                            item("Company Code", reverse("risk_admin:masterdata_companycode_changelist")),
                            item("Business Area", reverse("risk_admin:masterdata_businessarea_changelist")),
                            item("Personnel Area", reverse("risk_admin:masterdata_personnelarea_changelist")),
                            item("Personnel Sub Area", reverse("risk_admin:masterdata_personnelsubarea_changelist")),
                            item("Directorate", reverse("risk_admin:masterdata_directorate_changelist")),
                            item("Division", reverse("risk_admin:masterdata_division_changelist")),
                            item("Organization Unit", reverse("risk_admin:masterdata_organizationunit_changelist")),
                        ],
                    },
                    {
                        "title": "Master Data Risiko",
                        "items": [
                            item("Taksonomi T3", "/admin/risk/taksonomit3/"),
                            item("Kategori Risiko", "/admin/risk/kategoririsiko/"),
                            item("Sasaran KBUMN", "/admin/risk/sasarankbumn/"),
                            item("Jenis Existing Control", "/admin/risk/masterjenisexistingcontrol/"),
                            item("Penilaian Efektivitas Kontrol", "/admin/risk/masterefektivitaskontrol/"),
                            item("Kategori Dampak", "/admin/risk/masterkategoridampak/"),
                            item("Skala Dampak", "/admin/risk/masterskaladampak/"),
                            item("Skala Probabilitas", "/admin/risk/masterskalaprobabilitas/"),
                            item("Level Risiko", "/admin/risk/masterlevelrisiko/"),
                            item("Matriks Risiko", "/admin/risk/riskmatrix/"),
                            item("Opsi Perlakuan Risiko", "/admin/risk/masteropsiperlakuanrisiko/"),
                            item("Jenis Rencana Perlakuan Risiko", "/admin/risk/masterjenisrencanaperlakuanrisiko/"),
                            item("Pos Anggaran", "/admin/risk/masterposanggaran/"),
                            item("Jenis Program Dalam RKAP", "/admin/risk/masterjenisprogramrkap/"),
                        ],
                    },
                    {
                        "title": "Authentication and Authorization",
                        "items": [
                            item("Bidang / Unit Bisnis", "/admin/auth/group/"),
                            item("Users", "/admin/auth/user/"),
                        ],
                    },
                    {
                        "title": "Pengaturan Sistem",
                        "items": [
                            item("Pengaturan Aplikasi, Logo, LDAP & AI", reverse("risk_admin:risk_appsetting_changelist")),
                            item("Tahun Buku", reverse("risk_admin:masterdata_tahunbuku_changelist")),
                            item("Periode Laporan", reverse("risk_admin:masterdata_periodelaporan_changelist")),
                        ],
                    },
                ],
            },
        ]

        visible_sections = []
        for section in sections:
            visible_groups = []
            for group in section["groups"]:
                visible_items = [
                    nav_item
                    for nav_item in group["items"]
                    if nav_item["url"] in allowed_urls
                ]
                if visible_items:
                    visible_groups.append({**group, "items": visible_items})
            if visible_groups:
                visible_sections.append({**section, "groups": visible_groups})
        return visible_sections

    def index(self, request, extra_context=None):
        extra_context = extra_context or {}

        stats = {
            "rkap": RKAPItem.objects.count(),
            "corporate": ProfilRisikoKorporatSummary.objects.count(),
            "km": KontrakManajemen.objects.count(),
            "template_km": MasterTemplateKM.objects.count(),
            "rkm": RKMSummary.objects.count(),
            "reassessment": ReAssessmentSummary.objects.count(),
            "kpmr": KPMRSummary.objects.count(),
            "monthly_report": MonthlyRiskReport.objects.count(),
            "monthly_report_detail": (
                MonthlyRiskReportItem.objects.count()
                + MonthlyRiskReportKMAlignment.objects.count()
                + MonthlyRiskReportChange.objects.count()
                + MonthlyRiskReportLossEvent.objects.count()
                + MonthlyRiskReportSubmissionLog.objects.count()
            ),
            "organization": (
                CompanyCode.objects.count()
                + BusinessArea.objects.count()
                + PersonnelArea.objects.count()
                + PersonnelSubArea.objects.count()
                + Directorate.objects.count()
                + Division.objects.count()
                + OrganizationUnit.objects.count()
            ),
            "monte_carlo": (
                RiskMetric.objects.count()
                + MonteCarloMetricHistory.objects.count()
                + MultiMetricMonteCarloResult.objects.count()
                + MultiMetricAIInsightKorporat.objects.count()
            ),
            "users": User.objects.count(),
            "units": Group.objects.count(),
            "settings": AppSetting.objects.count(),
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
                "title": "Pengaturan Sistem",
                "color": "settings",
                "count": stats["settings"],
                "featured": True,
                "items": [
                    {
                        "label": "Pengaturan Aplikasi, Logo, LDAP & AI",
                        "url": reverse("risk_admin:risk_appsetting_changelist"),
                    },
                    {
                        "label": "Tahun Buku",
                        "url": reverse("risk_admin:masterdata_tahunbuku_changelist"),
                    },
                    {
                        "label": "Periode Laporan",
                        "url": reverse("risk_admin:masterdata_periodelaporan_changelist"),
                    },
                ],
            },
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
                "title": "Monte Carlo Korporat",
                "color": "montecarlo",
                "count": stats["monte_carlo"],
                "items": [
                    {"label": "Input Histori / Upload Excel", "url": "/corporate-risk/metric-history-input/"},
                    {"label": "Risk Metrics", "url": "/admin/corporate_risk/riskmetric/"},
                    {"label": "Metric History", "url": "/admin/corporate_risk/montecarlometrichistory/"},
                    {"label": "Multi Metric Monte Carlo Results", "url": "/admin/corporate_risk/multimetricmontecarloresult/"},
                    {"label": "Multi Metric AI Insight", "url": "/admin/corporate_risk/multimetricaiinsightkorporat/"},
                ],
            },
            {
                "title": "Kontrak Manajemen (KM)",
                "color": "km",
                "count": stats["km"],
                "items": [
                    {"label": "Template KM", "url": "/admin/risk/mastertemplatekm/"},
                    {"label": "Kontrak Manajemen Unit/Bidang", "url": "/admin/risk/kontrakmanajemen/"},
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
                    {
                        "label": "III.D - Perubahan Profil/Strategi",
                        "url": reverse("risk_admin:monthly_report_monthlyriskreportchange_changelist"),
                    },
                    {
                        "label": "III.E - Loss Event Database",
                        "url": reverse("risk_admin:monthly_report_monthlyriskreportlossevent_changelist"),
                    },
                    {
                        "label": "Log Submit/Approval",
                        "url": reverse("risk_admin:monthly_report_monthlyriskreportsubmissionlog_changelist"),
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
                "title": "Master Organisasi",
                "color": "organization",
                "count": stats["organization"],
                "items": [
                    {
                        "label": "Company Code",
                        "url": reverse("risk_admin:masterdata_companycode_changelist"),
                    },
                    {
                        "label": "Business Area",
                        "url": reverse("risk_admin:masterdata_businessarea_changelist"),
                    },
                    {
                        "label": "Personnel Area",
                        "url": reverse("risk_admin:masterdata_personnelarea_changelist"),
                    },
                    {
                        "label": "Personnel Sub Area",
                        "url": reverse("risk_admin:masterdata_personnelsubarea_changelist"),
                    },
                    {
                        "label": "Directorate",
                        "url": reverse("risk_admin:masterdata_directorate_changelist"),
                    },
                    {
                        "label": "Division",
                        "url": reverse("risk_admin:masterdata_division_changelist"),
                    },
                    {
                        "label": "Organization Unit",
                        "url": reverse("risk_admin:masterdata_organizationunit_changelist"),
                    },
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
