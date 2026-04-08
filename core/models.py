# core/models.py
from django.conf import settings
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class WorkflowStatusMixin(models.Model):
    status = models.CharField(max_length=30, db_index=True)

    class Meta:
        abstract = True


class Attachment(TimeStampedModel):
    module_name = models.CharField(max_length=50)
    object_id = models.BigIntegerField()
    kategori_file = models.CharField(max_length=50)
    nama_file = models.CharField(max_length=255)
    file = models.FileField(upload_to="attachments/%Y/%m/")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="uploaded_attachments",
    )
    catatan = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "core_attachment"


class WorkflowLog(models.Model):
    module_name = models.CharField(max_length=50)
    object_id = models.BigIntegerField()
    status_from = models.CharField(max_length=50, blank=True, null=True)
    status_to = models.CharField(max_length=50)
    action_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="workflow_actions",
    )
    action_at = models.DateTimeField(auto_now_add=True)
    catatan = models.TextField(blank=True, null=True)

    class Meta:
        db_table = "core_workflow_log"
        ordering = ["-action_at"]