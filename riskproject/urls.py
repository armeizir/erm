from django.urls import path
from riskproject.admin_site import risk_admin_site

urlpatterns = [
    path("admin/", risk_admin_site.urls),
]