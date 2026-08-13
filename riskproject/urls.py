from django.conf import settings
from django.conf.urls.static import static
from django.urls import path, include

from risk.views import dashboard, export_rcc_excel, kpmr_review_view, kpmr_update_item
from riskproject.admin_site import risk_admin_site

from risk.bod_phase2 import bod_phase2_api

urlpatterns = [
    path("api/bod-phase2/", bod_phase2_api, name="bod_phase2_api"),
    path("", dashboard, name="dashboard"),

    path("rcc/", dashboard, name="rcc_dashboard"),
    path("rcc/export/excel/", export_rcc_excel, name="rcc_export_excel"),

    path("kpmr/review/<int:summary_id>/", kpmr_review_view, name="kpmr_review"),
    path("kpmr/update-item/", kpmr_update_item, name="kpmr_update_item"),

    path("admin/", risk_admin_site.urls),

    # ✅ PENTING: kasih prefix
    path("montecarlo/", include("corporate_risk.urls")),


    path("corporate-risk/", include("corporate_risk.urls")),
    path("awareness/", include("awareness.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
