from django.template.loader import render_to_string
from django.test import TestCase

from risk.models import KnowledgeBaseArticle, KnowledgeBaseCategory

from corporate_risk.history_notifications import (
    metric_history_notification_tutorial,
)
from corporate_risk.views import (
    metric_history_input_tutorial,
    youtube_embed_url,
)


class MetricHistoryTutorialTests(TestCase):
    def setUp(self):
        self.category = KnowledgeBaseCategory.objects.create(
            nama="Tutorial Risk Metric",
            urutan=1,
            aktif=True,
        )

    def test_youtube_embed_url_supports_common_url_formats(self):
        expected = (
            "https://www.youtube-nocookie.com/embed/"
            "p0DswNBQqr4?rel=0"
        )

        self.assertEqual(
            youtube_embed_url(
                "https://youtu.be/p0DswNBQqr4"
            ),
            expected,
        )
        self.assertEqual(
            youtube_embed_url(
                "https://www.youtube.com/watch?v=p0DswNBQqr4"
            ),
            expected,
        )
        self.assertEqual(
            youtube_embed_url(
                "https://www.youtube.com/shorts/p0DswNBQqr4"
            ),
            expected,
        )

    def test_youtube_embed_url_rejects_non_youtube_url(self):
        self.assertEqual(
            youtube_embed_url(
                "https://example.com/video/p0DswNBQqr4"
            ),
            "",
        )

    def test_resolver_returns_published_metric_history_tutorial(self):
        KnowledgeBaseArticle.objects.create(
            kategori=self.category,
            judul="Draft Tutorial",
            konten="Draft",
            status=KnowledgeBaseArticle.STATUS_DRAFT,
            tutorial_placement=(
                KnowledgeBaseArticle
                .TUTORIAL_PLACEMENT_METRIC_HISTORY_INPUT
            ),
            video_youtube_url=(
                "https://youtu.be/aaaaaaaaaaa"
            ),
        )
        published = KnowledgeBaseArticle.objects.create(
            kategori=self.category,
            judul="Tutorial Input Histori Risiko",
            ringkasan="Panduan memperbarui nilai aktual dan target.",
            konten="Langkah-langkah pengisian.",
            status=KnowledgeBaseArticle.STATUS_PUBLISHED,
            tutorial_placement=(
                KnowledgeBaseArticle
                .TUTORIAL_PLACEMENT_METRIC_HISTORY_INPUT
            ),
            video_youtube_url=(
                "https://youtu.be/p0DswNBQqr4"
            ),
        )

        self.assertEqual(
            metric_history_input_tutorial(),
            published,
        )

    def test_notification_resolver_returns_same_published_tutorial(self):
        published = KnowledgeBaseArticle.objects.create(
            kategori=self.category,
            judul="Tutorial Email Histori Risiko",
            ringkasan="Panduan singkat pengisian histori risiko.",
            konten="Langkah-langkah pengisian.",
            status=KnowledgeBaseArticle.STATUS_PUBLISHED,
            tutorial_placement=(
                KnowledgeBaseArticle
                .TUTORIAL_PLACEMENT_METRIC_HISTORY_INPUT
            ),
            video_youtube_url=(
                "https://youtu.be/p0DswNBQqr4"
            ),
        )

        self.assertEqual(
            metric_history_notification_tutorial(),
            published,
        )

    def test_email_templates_include_tutorial(self):
        tutorial = KnowledgeBaseArticle.objects.create(
            kategori=self.category,
            judul="Tutorial Input Histori Risiko",
            ringkasan="Panduan memperbarui nilai aktual dan target.",
            konten="Langkah-langkah pengisian.",
            status=KnowledgeBaseArticle.STATUS_PUBLISHED,
            tutorial_placement=(
                KnowledgeBaseArticle
                .TUTORIAL_PLACEMENT_METRIC_HISTORY_INPUT
            ),
            video_youtube_url=(
                "https://youtu.be/p0DswNBQqr4"
            ),
        )
        context = {
            "tutorial": tutorial,
            "input_url": "https://erm.example.test/input/1/",
        }

        html = render_to_string(
            "corporate_risk/email/metric_history_assignment.html",
            context,
        )
        text = render_to_string(
            "corporate_risk/email/metric_history_assignment.txt",
            context,
        )

        self.assertIn("PANDUAN PENGISIAN", html)
        self.assertIn(tutorial.judul, html)
        self.assertIn(tutorial.video_youtube_url, html)
        self.assertIn("Video tutorial:", text)
        self.assertIn(tutorial.video_youtube_url, text)

