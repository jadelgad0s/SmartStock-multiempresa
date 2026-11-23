import mimetypes

from django.contrib.auth.decorators import login_required
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.storage import default_storage
from django.http import FileResponse, Http404
from django.urls import include, path, re_path
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from .login import completar_acceso
from .soporte_empresa import soporte_empresa


@login_required(login_url='/')
@never_cache
@require_safe
def archivo_empresa(request, path):
    try:
        archivo = default_storage.open(path, 'rb')
    except (FileNotFoundError, IsADirectoryError, NotADirectoryError, SuspiciousFileOperation):
        raise Http404('Archivo no disponible.') from None
    tipo = mimetypes.guess_type(path)[0] or 'application/octet-stream'
    return FileResponse(archivo, content_type=tipo,
                        as_attachment=not tipo.startswith('image/'), filename=path.rsplit('/', 1)[-1])


urlpatterns = [
    path('soporte/', soporte_empresa, name='soporte_empresa'),
    path('acceder/', completar_acceso, name='completar_acceso'),
    re_path(r'^media/(?P<path>.*)$', archivo_empresa),
    path('', include('config.urls')),
]
