from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone


class AwarenessCampaign(models.Model):
    TOPIC_CHOICES = (
        ("manajemen_risiko", "Manajemen Risiko"),
        ("kpmr", "KPMR"),
        ("risiko_korporat", "Risiko Korporat"),
        ("risiko_operasional", "Risiko Operasional"),
        ("risiko_proyek", "Risiko Proyek"),
        ("kepatuhan", "Kepatuhan"),
        ("cyber_risk", "Cyber Risk"),
        ("business_continuity", "Business Continuity"),
    )

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    material_image = models.FileField(
        upload_to="awareness/materials/",
        blank=True,
        validators=[FileExtensionValidator(allowed_extensions=["jpg", "jpeg", "png", "webp"])],
        help_text="Upload gambar materi awareness yang dibaca user sebelum mulai kuis.",
    )
    topic = models.CharField(max_length=50, choices=TOPIC_CHOICES, default="manajemen_risiko")
    email_header_title = models.CharField(
        max_length=160,
        blank=True,
        default="",
        verbose_name="Judul Header Email",
        help_text="Contoh: Awareness Manajemen Risiko. Jika kosong, sistem memakai judul campaign.",
    )
    email_header_subtitle = models.CharField(
        max_length=160,
        blank=True,
        default="",
        verbose_name="Subjudul Header Email",
        help_text="Contoh: Manajemen Risiko. Jika kosong, sistem memakai topik campaign.",
    )
    notification_test_email = models.EmailField(
        blank=True,
        default="",
        verbose_name="Email Tujuan Report",
        help_text="Tujuan default tombol Kirim Report. Jika kosong, sistem memakai email admin yang login.",
    )
    start_date = models.DateField()
    end_date = models.DateField()
    passing_score = models.PositiveSmallIntegerField(default=70)
    max_attempts = models.PositiveSmallIntegerField(default=1, null=True, blank=True)
    time_limit_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_awareness_campaigns",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-start_date", "title")
        permissions = (
            ("view_campaign_report", "Can view awareness campaign report"),
            ("export_campaign_result", "Can export awareness campaign result"),
        )

    def __str__(self):
        return self.title

    @property
    def email_heading(self):
        return self.email_header_title or self.title

    @property
    def email_subheading(self):
        return self.email_header_subtitle or self.get_topic_display()

    @property
    def question_count(self):
        return self.questions.filter(is_active=True).count()

    def is_currently_active(self, at=None):
        at = at or timezone.localdate()
        return bool(self.is_active and self.start_date <= at <= self.end_date)

    def clean(self):
        errors = {}
        if self.end_date and self.start_date and self.end_date < self.start_date:
            errors["end_date"] = "Tanggal selesai tidak boleh lebih awal dari tanggal mulai."
        if self.passing_score > 100:
            errors["passing_score"] = "Passing score maksimal 100."
        if errors:
            raise ValidationError(errors)


class AwarenessUnitTarget(models.Model):
    campaign = models.ForeignKey(
        AwarenessCampaign,
        on_delete=models.CASCADE,
        related_name="unit_targets",
        verbose_name="Campaign",
    )
    unit_name = models.CharField(
        max_length=180,
        verbose_name="Bidang / Unit",
        help_text="Nama bidang/unit sesuai data jumlah pegawai.",
    )
    employee_count = models.PositiveIntegerField(
        default=0,
        verbose_name="Jumlah Pegawai",
    )
    order = models.PositiveIntegerField(default=1, verbose_name="Urutan")
    is_active = models.BooleanField(default=True, verbose_name="Aktif")

    class Meta:
        verbose_name = "Target Pegawai Awareness per Unit"
        verbose_name_plural = "Target Pegawai Awareness per Unit"
        ordering = ("campaign", "order", "unit_name")
        constraints = [
            models.UniqueConstraint(
                fields=("campaign", "unit_name"),
                name="awareness_unique_unit_target",
            )
        ]

    def __str__(self):
        return f"{self.campaign} - {self.unit_name}"


class AwarenessQuestion(models.Model):
    ANSWER_CHOICES = (
        ("A", "A"),
        ("B", "B"),
        ("C", "C"),
        ("D", "D"),
    )
    DIFFICULTY_CHOICES = (
        ("mudah", "Mudah"),
        ("sedang", "Sedang"),
        ("sulit", "Sulit"),
    )

    campaign = models.ForeignKey(AwarenessCampaign, on_delete=models.CASCADE, related_name="questions")
    question_text = models.TextField()
    option_a = models.CharField(max_length=500)
    option_b = models.CharField(max_length=500)
    option_c = models.CharField(max_length=500)
    option_d = models.CharField(max_length=500)
    correct_answer = models.CharField(max_length=1, choices=ANSWER_CHOICES)
    explanation = models.TextField(blank=True)
    difficulty = models.CharField(max_length=20, choices=DIFFICULTY_CHOICES, default="mudah")
    weight = models.PositiveSmallIntegerField(default=1)
    order = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("campaign", "order", "id")

    def __str__(self):
        return f"{self.campaign} - {self.order}"

    def option_text(self, answer):
        return {
            "A": self.option_a,
            "B": self.option_b,
            "C": self.option_c,
            "D": self.option_d,
        }.get(answer, "")


class AwarenessAttempt(models.Model):
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_SUBMITTED = "submitted"
    STATUS_PASSED = "passed"
    STATUS_FAILED = "failed"
    STATUS_EXPIRED = "expired"

    STATUS_CHOICES = (
        (STATUS_IN_PROGRESS, "Sedang dikerjakan"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_PASSED, "Lulus"),
        (STATUS_FAILED, "Tidak lulus"),
        (STATUS_EXPIRED, "Expired"),
    )

    campaign = models.ForeignKey(AwarenessCampaign, on_delete=models.CASCADE, related_name="attempts")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="awareness_attempts")
    started_at = models.DateTimeField(default=timezone.now)
    submitted_at = models.DateTimeField(null=True, blank=True)
    score = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    total_questions = models.PositiveIntegerField(default=0)
    correct_count = models.PositiveIntegerField(default=0)
    wrong_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_IN_PROGRESS)
    attempt_number = models.PositiveIntegerField(default=1)
    duration_seconds = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-started_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("campaign", "user", "attempt_number"),
                name="awareness_unique_attempt_number",
            ),
        ]
        indexes = [
            models.Index(fields=("campaign", "user", "status")),
        ]

    def __str__(self):
        return f"{self.campaign} - {self.user} #{self.attempt_number}"

    @property
    def is_finished(self):
        return self.status in {self.STATUS_PASSED, self.STATUS_FAILED, self.STATUS_EXPIRED, self.STATUS_SUBMITTED}

    def is_expired(self, at=None):
        if not self.campaign.time_limit_minutes or self.status != self.STATUS_IN_PROGRESS:
            return False
        at = at or timezone.now()
        return at > self.started_at + timedelta(minutes=self.campaign.time_limit_minutes)

    def mark_expired_if_needed(self):
        if self.is_expired():
            self.status = self.STATUS_EXPIRED
            self.submitted_at = timezone.now()
            self.duration_seconds = int((self.submitted_at - self.started_at).total_seconds())
            self.save(update_fields=["status", "submitted_at", "duration_seconds", "updated_at"])
            return True
        return False

    def calculate_result(self):
        questions = list(self.campaign.questions.filter(is_active=True).order_by("order", "id"))
        answers = {
            answer.question_id: answer
            for answer in self.answers.select_related("question")
        }
        total_weight = sum(question.weight for question in questions) or 0
        correct_weight = 0
        correct_count = 0

        for question in questions:
            answer = answers.get(question.id)
            is_correct = bool(answer and answer.selected_answer == question.correct_answer)
            if answer and answer.is_correct != is_correct:
                answer.is_correct = is_correct
                answer.save(update_fields=["is_correct", "answered_at"])
            if is_correct:
                correct_weight += question.weight
                correct_count += 1

        score = Decimal("0")
        if total_weight:
            score = (Decimal(correct_weight) / Decimal(total_weight) * Decimal("100")).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )

        self.total_questions = len(questions)
        self.correct_count = correct_count
        self.wrong_count = max(len(questions) - correct_count, 0)
        self.score = score
        self.submitted_at = timezone.now()
        self.duration_seconds = int((self.submitted_at - self.started_at).total_seconds())
        self.status = self.STATUS_PASSED if score >= self.campaign.passing_score else self.STATUS_FAILED
        self.save(update_fields=[
            "total_questions",
            "correct_count",
            "wrong_count",
            "score",
            "submitted_at",
            "duration_seconds",
            "status",
            "updated_at",
        ])
        return self


class AwarenessAnswer(models.Model):
    ANSWER_CHOICES = AwarenessQuestion.ANSWER_CHOICES

    attempt = models.ForeignKey(AwarenessAttempt, on_delete=models.CASCADE, related_name="answers")
    question = models.ForeignKey(AwarenessQuestion, on_delete=models.CASCADE, related_name="answers")
    selected_answer = models.CharField(max_length=1, choices=ANSWER_CHOICES)
    is_correct = models.BooleanField(default=False)
    answered_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("attempt", "question")
        ordering = ("question__order", "question_id")

    def __str__(self):
        return f"{self.attempt} - {self.question_id}: {self.selected_answer}"
