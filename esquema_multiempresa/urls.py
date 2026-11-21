from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.urls import include, path, re_path
from django.views.static import serve

from .login import completar_acceso
from .soporte_empresa import soporte_empresa


@login_required(login_url='/')
def archivo_empresa(request, path):
    return serve(request, path, document_root=default_storage.location)


urlpatterns = [
    path('soporte/', soporte_empresa, name='soporte_empresa'),
    path('acceder/', completar_acceso, name='completar_acceso'),
    re_path(r'^media/(?P<path>.*)$', archivo_empresa),
    path('', include('config.urls')),
]
