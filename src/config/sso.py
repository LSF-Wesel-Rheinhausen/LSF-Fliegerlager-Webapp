import re

from django.core.exceptions import ImproperlyConfigured

HTTP_HEADER_NAME_PATTERN = re.compile(r"^[!#$%&'*+\-.^_`|~0-9A-Za-z]+$")


def validate_authelia_email_header(value: str) -> str:
    """Return a trusted-header name after validating HTTP field-name syntax."""
    header_name = value.strip()
    if not header_name or HTTP_HEADER_NAME_PATTERN.fullmatch(header_name) is None:
        raise ImproperlyConfigured(
            "AUTHELIA_SSO_EMAIL_HEADER must be a non-empty valid HTTP header name when Authelia SSO is enabled."
        )
    return header_name
