from functools import wraps

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache


def es_personal_smartstock(usuario):
    return bool(usuario.is_authenticated and usuario.activo and usuario.is_staff
                and usuario._state.db == 'central')


def es_superusuario_smartstock(usuario):
    return es_personal_smartstock(usuario) and usuario.is_superuser


def requiere_personal(vista):
    @never_cache
    @wraps(vista)
    def protegida(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login_page')
        if not es_personal_smartstock(request.user):
            raise PermissionDenied
        return vista(request, *args, **kwargs)
    return protegida
