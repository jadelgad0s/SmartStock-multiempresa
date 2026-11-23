"""Entrada del servidor público multiempresa."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'esquema_multiempresa.production')
application = get_wsgi_application()
