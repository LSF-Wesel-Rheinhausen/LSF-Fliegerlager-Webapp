import secrets
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse


class SecurityHeadersMiddleware:
    """Attach application-wide browser security headers to dynamic and static responses."""

    permissions_policy = "camera=(), geolocation=(), microphone=(), payment=()"

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request.csp_nonce = secrets.token_urlsafe(16)  # type: ignore[attr-defined]
        response = self.get_response(request)
        response.setdefault("Content-Security-Policy", self.content_security_policy(request.csp_nonce))  # type: ignore[attr-defined]
        response.setdefault("Cross-Origin-Embedder-Policy", "require-corp")
        response.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.setdefault("Cross-Origin-Resource-Policy", "same-origin")
        response.setdefault("Permissions-Policy", self.permissions_policy)
        return response

    def content_security_policy(self, nonce: str) -> str:
        """Return the CSP value for a request-scoped nonce."""
        directives: dict[str, tuple[str, ...]] = {
            "default-src": ("'self'",),
            "script-src": ("'self'", f"'nonce-{nonce}'"),
            "script-src-attr": ("'unsafe-inline'",),
            "style-src": ("'self'", f"'nonce-{nonce}'"),
            "style-src-attr": ("'unsafe-inline'",),
            "img-src": ("'self'", "data:"),
            "font-src": ("'self'",),
            "connect-src": ("'self'",),
            "frame-ancestors": ("'none'",),
            "base-uri": ("'self'",),
            "form-action": ("'self'",),
        }
        return "; ".join(f"{name} {' '.join(values)}" for name, values in directives.items())
