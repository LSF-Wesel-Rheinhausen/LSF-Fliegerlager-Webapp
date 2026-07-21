import logging

from django.db import DatabaseError, connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static

logger = logging.getLogger(__name__)


def healthcheck(request: HttpRequest) -> JsonResponse:
    """Report application readiness without exposing operational details."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except DatabaseError:
        logger.exception("Healthcheck database query failed")
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ok"})


def platform_icon(_request: HttpRequest) -> HttpResponse:
    """Redirect conventional platform icon paths to the installed app icon."""
    return redirect(static("billing/icons/icon-192.png"), permanent=True)


def page_not_found(request: HttpRequest, exception: Exception | None = None) -> HttpResponse:
    """Render the custom page for unknown URLs."""
    return render(request, "404.html", status=404)
