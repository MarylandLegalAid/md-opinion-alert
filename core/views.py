from django.apps import apps
from django.db import connection
from django.http import JsonResponse


def healthz(request):
    """Health check: DB connectivity + age of the last successful ingestion.

    Returns 503 only on DB failure — a stale ingestion is surfaced in the
    payload for external monitors to alert on, but does not take the web
    service out of rotation.
    """
    payload = {"status": "ok", "database": "ok", "last_ingestion_at": None}

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception:
        payload["status"] = "error"
        payload["database"] = "error"
        return JsonResponse(payload, status=503)

    try:
        ingestion_run = apps.get_model("ingestion", "IngestionRun")
    except LookupError:
        ingestion_run = None
    if ingestion_run is not None:
        last = (
            ingestion_run.objects.filter(status="success")
            .order_by("-finished_at")
            .values_list("finished_at", flat=True)
            .first()
        )
        payload["last_ingestion_at"] = last.isoformat() if last else None

    return JsonResponse(payload)
