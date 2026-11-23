#!/usr/bin/env bash
set -euo pipefail
export DJANGO_SETTINGS_MODULE=esquema_multiempresa.production
exec gunicorn esquema_multiempresa.wsgi:application \
  --bind "0.0.0.0:${PORT:-10000}" --workers 1 --threads 4 --timeout 60
