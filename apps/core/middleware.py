"""
Middleware personalizado para SmartStock.
"""
from contextvars import ContextVar

_peticion = ContextVar('smartstock_peticion_auditoria', default=None)


def get_current_request():
    """Obtiene el request actual desde cualquier parte del código."""
    return _peticion.get()


def get_current_user():
    """Obtiene el usuario autenticado actual."""
    request = get_current_request()
    if request and hasattr(request, 'user') and request.user.is_authenticated:
        return request.user
    return None


class AuditMiddleware:
    """
    Middleware que hace disponible el request actual en cualquier
    parte del código. Necesario para que las señales de auditoría
    puedan capturar el usuario que realizó la acción.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        anterior = _peticion.set(request)
        try:
            return self.get_response(request)
        finally:
            _peticion.reset(anterior)


def get_client_ip(request):
    """Obtiene la IP real del cliente considerando proxies."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR', '')
