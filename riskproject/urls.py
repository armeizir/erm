from django.urls import path, include

from risk.views import dashboard, export_rcc_excel, kpmr_review_view, kpmr_update_item
from riskproject.admin_site import risk_admin_site

urlpatterns = [
    path("", dashboard, name="dashboard"),

    path("rcc/", dashboard, name="rcc_dashboard"),
    path("rcc/export/excel/", export_rcc_excel, name="rcc_export_excel"),

    path("kpmr/review/<int:summary_id>/", kpmr_review_view, name="kpmr_review"),
    path("kpmr/update-item/", kpmr_update_item, name="kpmr_update_item"),

    path("admin/", risk_admin_site.urls),

    # ✅ PENTING: kasih prefix
    path("montecarlo/", include("corporate_risk.urls")),
]
