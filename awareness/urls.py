from django.urls import path

from . import views


app_name = "awareness"

urlpatterns = [
    path("", views.campaign_list, name="campaign_list"),
    path("<int:campaign_id>/start/", views.start_campaign, name="start_campaign"),
    path("attempt/<int:attempt_id>/", views.quiz_attempt, name="quiz_attempt"),
    path("attempt/<int:attempt_id>/submit/", views.submit_attempt, name="submit_attempt"),
    path("attempt/<int:attempt_id>/result/", views.attempt_result, name="attempt_result"),
]
