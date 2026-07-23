from django.urls import path

from .views import download_evidence


urlpatterns = [
    path("evidence/<path:file_name>", download_evidence, name="monthly_report_evidence_download"),
]
