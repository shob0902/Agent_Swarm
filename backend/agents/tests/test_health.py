# Tests for the public /api/health/ endpoint used to check a deployment's database.
from unittest import mock
from django.db.utils import OperationalError
from django.test import TestCase
class HealthTests(TestCase):
    # Healthy when the DB answers and is fully migrated; otherwise a 503 with a short reason and no secrets.
    def test_migrated_database_is_healthy(self):
        # The test database is fully migrated.
        response = self.client.get("/api/health/", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["pending_migrations"], 0)
    def test_pending_migrations_reported(self):
        # Unapplied migrations make the deployment unhealthy, with the fix spelled out.
        with mock.patch("orchestrator.health.MigrationExecutor") as executor:
            executor.return_value.migration_plan.return_value = [object()] * 3
            response = self.client.get("/api/health/", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["pending_migrations"], 3)
        self.assertIn("migrate", response.json()["hint"])
    def test_database_error_reports_class_only(self):
        # Connection failures name the error type, never the host or credentials in the message.
        with mock.patch("orchestrator.health.MigrationExecutor", side_effect=OperationalError("could not connect to server at db.secret-host:5432 password=hunter2")):
            response = self.client.get("/api/health/", HTTP_HOST="localhost")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["database"], "error: OperationalError")
        self.assertNotIn("secret-host", response.content.decode())
