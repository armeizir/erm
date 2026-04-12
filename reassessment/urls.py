from django.urls import path
from . import views

app_name = "reassessment"

urlpatterns = [
    path("<int:pk>/submit/", views.submit_reassessment),
    path("<int:pk>/start-rkm-review/", views.start_rkm_review),
    path("<int:pk>/approve-rkm/", views.approve_rkm),
    path("<int:pk>/reject-rkm/", views.reject_rkm),
    path("<int:pk>/start-km-review/", views.start_km_review),
    path("<int:pk>/approve-km/", views.approve_km),
    path("<int:pk>/reject-km/", views.reject_km),
    path("<int:pk>/lock/", views.lock_reassessment),
]