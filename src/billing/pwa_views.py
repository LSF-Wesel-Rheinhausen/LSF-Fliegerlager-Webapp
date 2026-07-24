from typing import Any

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.templatetags.static import static

PWA_CACHE_VERSION = 7

PWA_SURFACES: dict[str, dict[str, str]] = {
    "admin": {
        "name": "Fliegerlager Verwaltung",
        "short_name": "Verwaltung",
        "scope": "/",
        "start_url": "/camps/",
        "icon": "admin-icon",
    },
    "kiosk": {
        "name": "Fliegerlager",
        "short_name": "Fliegerlager",
        "scope": "/kiosk/",
        "start_url": "/kiosk/",
        "icon": "kiosk-icon",
    },
    "central": {
        "name": "Fliegerlager Kiosk",
        "short_name": "Kiosk",
        "scope": "/central/kiosk/",
        "start_url": "/central/kiosk/",
        "icon": "central-icon",
    },
}


def manifest(_request: HttpRequest, surface: str) -> JsonResponse:
    """Return a surface-specific web app manifest."""
    config = PWA_SURFACES[surface]
    icon = config["icon"]
    manifest_config = {key: value for key, value in config.items() if key != "icon"}
    icons = [
        {
            "src": static(f"billing/icons/{icon}-192.png"),
            "sizes": "192x192",
            "type": "image/png",
            "purpose": "any",
        },
        {
            "src": static(f"billing/icons/{icon}-512.png"),
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "any",
        },
        {
            "src": static(f"billing/icons/{icon}-512.png"),
            "sizes": "512x512",
            "type": "image/png",
            "purpose": "maskable",
        },
    ]
    return JsonResponse(
        {
            **manifest_config,
            "id": config["start_url"],
            "display": "standalone",
            "background_color": "#f7f7f5",
            "theme_color": "#1f5d42",
            "lang": "de",
            "icons": icons,
        },
        content_type="application/manifest+json",
    )


def service_worker(request: HttpRequest, surface: str) -> HttpResponse:
    """Serve the service worker at a URL matching its allowed scope."""
    config = PWA_SURFACES[surface]
    response = render(
        request,
        "billing/service_worker.js",
        {
            "cache_name": f"fliegerlager-{surface}-v{PWA_CACHE_VERSION}",
            "cache_prefix": f"fliegerlager-{surface}-",
            "offline_url": "/offline/",
            "static_assets": [
                "/offline/",
                static("billing/app-v8.css"),
                static("billing/theme.js"),
                static("billing/pwa.js"),
                static("billing/logo.jpg"),
                static(f"billing/icons/{config['icon']}-192.png"),
                static(f"billing/icons/{config['icon']}-512.png"),
            ],
        },
        content_type="application/javascript",
    )
    response["Service-Worker-Allowed"] = config["scope"]
    response["Cache-Control"] = "no-cache"
    return response


def offline(request: HttpRequest) -> HttpResponse:
    """Render a generic offline fallback without application data."""
    return render(request, "billing/offline.html")


def pwa_template_context(surface: str) -> dict[str, Any]:
    """Return manifest and service-worker URLs for a PWA surface."""
    from django.urls import reverse

    suffix = "kiosk" if surface == "kiosk" else surface
    return {
        "pwa_surface": surface,
        "pwa_manifest_url": reverse(f"pwa-manifest-{suffix}"),
        "pwa_worker_url": reverse(f"pwa-worker-{suffix}"),
        "pwa_worker_scope": PWA_SURFACES[surface]["scope"],
        "pwa_icon_url": static(f"billing/icons/{PWA_SURFACES[surface]['icon']}-192.png"),
    }
