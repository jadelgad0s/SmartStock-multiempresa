from django.urls import path
from django.views.generic import RedirectView, TemplateView

from apps.usuarios.views_auth import logout_web
from apps.usuarios.views_recuperacion import (
    RecuperacionEnviadaView, EstablecerNuevaClaveView, ClaveActualizadaView,
)
from .admin_central import sitio_sistema
from .login import LoginCentralView, login_central
from .recuperacion_central import SolicitarRecuperacionCentralView


urlpatterns = [
    path('', login_central, name='login_page'),
    path('api/v1/auth/login-web/', LoginCentralView.as_view(), name='login_web'),
    path('contacto/', TemplateView.as_view(template_name='usuarios/contacto.html'), name='contacto_page'),
    path('cerrar-sesion/', logout_web, name='logout_web'),
    path('recuperar-clave/', SolicitarRecuperacionCentralView.as_view(), name='recuperar_clave'),
    path('recuperacion-enviada/', RecuperacionEnviadaView.as_view(), name='recuperacion_enviada'),
    path('restablecer-clave/<uidb64>/<token>/', EstablecerNuevaClaveView.as_view(), name='establecer_nueva_clave'),
    path('clave-actualizada/', ClaveActualizadaView.as_view(), name='clave_actualizada'),
    path('sistema/', sitio_sistema.urls),
    path('admin/', RedirectView.as_view(url='/sistema/', permanent=False)),
]
