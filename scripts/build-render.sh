#!/usr/bin/env bash
set -euo pipefail
export DJANGO_SETTINGS_MODULE=esquema_multiempresa.production
python -m pip install -r requirements-web.txt
python manage.py check
python manage.py collectstatic --noinput
