#!/usr/bin/env bash
set -euo pipefail
python manage.py migrate --noinput --database=central --settings=esquema_multiempresa.migracion_produccion
python manage.py migrate --noinput --database=ferreteria --settings=esquema_multiempresa.migracion_produccion
python manage.py migrate --noinput --database=repuestos --settings=esquema_multiempresa.migracion_produccion
