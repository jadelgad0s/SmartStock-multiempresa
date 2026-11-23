"""Comprobación de vida del proceso sin sesiones, escrituras ni consultas a Neon."""
from django.http import HttpResponseNotAllowed, JsonResponse


class SaludMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path_info != '/salud/':
            return self.get_response(request)
        request.get_host()  # Aplica ALLOWED_HOSTS también en la comprobación.
        if request.method not in ('GET', 'HEAD'):
            return HttpResponseNotAllowed(['GET', 'HEAD'])
        respuesta = JsonResponse({'estado': 'ok'})
        respuesta['Cache-Control'] = 'no-store'
        return respuesta
