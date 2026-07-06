FROM python:3.13-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt

FROM python:3.13-slim

ARG APP_VERSION=development
ARG APP_REVISION=unknown
ARG APP_BUILD_DATE=unknown
ARG APP_CHANGE="Unbekannter Build"

LABEL org.opencontainers.image.title="LSF Fliegerlager Webapp" \
      org.opencontainers.image.source="https://github.com/LSF-Wesel-Rheinhausen/LSF-Fliegerlager-Webapp" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${APP_REVISION}" \
      org.opencontainers.image.created="${APP_BUILD_DATE}" \
      io.lsf-fliegerlager.change="${APP_CHANGE}"

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_VERSION="${APP_VERSION}" \
    APP_REVISION="${APP_REVISION}" \
    APP_BUILD_DATE="${APP_BUILD_DATE}" \
    APP_CHANGE="${APP_CHANGE}"

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app app

COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=app:app src ./src
COPY --chown=app:app docker/app-entrypoint.sh /usr/local/bin/app-entrypoint

RUN chmod 0755 /usr/local/bin/app-entrypoint \
    && mkdir -p /app/src/media /app/src/staticfiles \
    && chown -R app:app /app

USER app
WORKDIR /app/src

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/app-entrypoint"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2", "--threads", "2", "--timeout", "60", "--access-logfile", "-"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz/', timeout=3)"
