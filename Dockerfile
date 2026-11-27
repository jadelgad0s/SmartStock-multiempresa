FROM python:3.13.7-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=esquema_multiempresa.docker

WORKDIR /app

COPY requirements-web.txt ./
RUN python -m pip install --no-cache-dir -r requirements-web.txt \
    && groupadd --system --gid 10001 smartstock \
    && useradd --system --uid 10001 --gid smartstock --home-dir /app smartstock

COPY --chown=smartstock:smartstock . .
RUN mkdir -p /app/media /app/staticfiles \
    && chown smartstock:smartstock /app/media /app/staticfiles

USER smartstock
EXPOSE 8000

ENTRYPOINT ["sh", "/app/infra/docker/start.sh"]
CMD ["gunicorn", "esquema_multiempresa.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "4", "--timeout", "60", "--access-logfile", "-", "--error-logfile", "-"]
