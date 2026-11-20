from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.urls import include, path, re_path
from django.views.static import serve

from .login import completar_acceso


@login_required(login_url='/')
def archivo_empresa(request, path):
    return serve(request, path, document_root=default_storage.location)


urlpatterns = [
    path('acceder/', completar_acceso, name='completar_acceso'),
    re_path(r'^media/(?P<path>.*)$', archivo_empresa),
    path('', include('config.urls')),
]
