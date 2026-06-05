from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def page_not_found(request: HttpRequest, exception: Exception | None = None) -> HttpResponse:
    """Render the custom page for unknown URLs."""
    return render(request, "404.html", status=404)
