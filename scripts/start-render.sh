#!/usr/bin/env bash
set -euo pipefail
export DJANGO_SETTINGS_MODULE=esquema_multiempresa.production
# Comprobación explícita del despliegue temporal; desactivada por defecto.
if [[ "${SS_VERIFICAR_PRODUCCION:-False}" == "True" ]]; then
  python manage.py verificar_produccion --probar-archivos
fi
exec gunicorn esquema_multiempresa.wsgi:application \
  --bind "0.0.0.0:${PORT:-10000}" --workers 1 --threads 4 --timeout 60
