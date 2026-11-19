from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.urls import include, path, re_path
from django.views.static import serve


@login_required(login_url='/')
def archivo_empresa(request, path):
    return serve(request, path, document_root=default_storage.location)


urlpatterns = [
    re_path(r'^media/(?P<path>.*)$', archivo_empresa),
    path('', include('config.urls')),
]
