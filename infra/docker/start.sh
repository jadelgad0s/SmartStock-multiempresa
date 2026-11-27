#!/bin/sh
set -eu

python manage.py preparar_docker
python manage.py collectstatic --noinput
exec "$@"
