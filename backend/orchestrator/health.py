# Public health check: is the database reachable and fully migrated? Reports status only, never connection details.
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.migrations.executor import MigrationExecutor
from django.http import JsonResponse
def health(request):
    # 200 when the database answers and has no pending migrations, 503 otherwise, with a short reason.
    report = {"database": "ok", "pending_migrations": None}
    try:
        connection = connections[DEFAULT_DB_ALIAS]
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        executor = MigrationExecutor(connection)
        report["pending_migrations"] = len(executor.migration_plan(executor.loader.graph.leaf_nodes()))
    except Exception as exc:  # noqa: BLE001 -- the class name is enough to diagnose without leaking hosts or credentials
        report["database"] = f"error: {type(exc).__name__}"
    report["database_engine"] = connections[DEFAULT_DB_ALIAS].vendor
    healthy = report["database"] == "ok" and report["pending_migrations"] == 0
    if report["pending_migrations"]:
        report["hint"] = "Run `python manage.py migrate` (add it to the start command)."
    return JsonResponse({"status": "ok" if healthy else "unhealthy", **report}, status=200 if healthy else 503)
