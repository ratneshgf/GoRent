from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase
from django.test import override_settings

from .database import database_from_url


class DatabaseUrlTests(SimpleTestCase):
    def test_supabase_session_pooler_url_decodes_password_and_requires_ssl(self):
        config = database_from_url(
            "postgresql://postgres.gorentref:p%40ss%23word@aws-0-ap-south-1.pooler.supabase.com:5432/postgres?sslmode=require",
            "gorentref",
        )
        self.assertEqual(config["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(config["USER"], "postgres.gorentref")
        self.assertEqual(config["PASSWORD"], "p@ss#word")
        self.assertEqual(config["OPTIONS"]["sslmode"], "require")

    def test_other_supabase_project_and_insecure_url_are_rejected(self):
        url = "postgresql://postgres.otherref:secret@aws-0-ap-south-1.pooler.supabase.com:5432/postgres"
        with self.assertRaises(ImproperlyConfigured):
            database_from_url(url, "gorentref")
        with self.assertRaises(ImproperlyConfigured):
            database_from_url(url + "?sslmode=disable", "otherref")
        with self.assertRaises(ImproperlyConfigured):
            database_from_url("not-a-postgres-url", "gorentref")
        with self.assertRaises(ImproperlyConfigured):
            database_from_url("postgresql://postgres:secret@other.example.com:5432/postgres", "gorentref")


class DeploymentCorsTests(SimpleTestCase):
    @override_settings(CORS_ALLOWED_ORIGINS=["https://gorent.vercel.app"])
    def test_only_configured_frontend_origin_receives_api_cors_headers(self):
        accepted = self.client.options(
            "/api/health/",
            HTTP_ORIGIN="https://gorent.vercel.app",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
        )
        rejected = self.client.options(
            "/api/health/",
            HTTP_ORIGIN="https://unrelated.example",
            HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
        )
        self.assertEqual(accepted["Access-Control-Allow-Origin"], "https://gorent.vercel.app")
        self.assertNotIn("Access-Control-Allow-Origin", rejected)
