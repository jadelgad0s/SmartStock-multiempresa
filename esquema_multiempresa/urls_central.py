from django.urls import path
from django.views.generic import TemplateView

from apps.usuarios.views_auth import logout_web
from apps.usuarios.views_recuperacion import (
    RecuperacionEnviadaView, EstablecerNuevaClaveView, ClaveActualizadaView,
)
from .admin_central import sitio_sistema
from .contacto import bandeja, conexion_contacto, cuenta_contacto, detalle_mensaje, mi_cuenta_contacto, sincronizar
from .login import LoginCentralView, login_central
from .recuperacion_central import SolicitarRecuperacionCentralView
from .consultas_sistema import consulta_sistema, inventario_sistema
from .notificaciones import leer_notificacion, leer_todas, listar_notificaciones
from .sistema import (
    abrir_configuracion, auditoria_sistema, cuentas_sistema, editar_cuenta_tecnica,
    editar_empresa, editar_usuario_empresa, empresas_sistema, ficha_empresa, inicio_sistema, mi_cuenta, usuarios_sistema,
)


urlpatterns = [
    path('', login_central, name='login_page'),
    path('api/v1/auth/login-web/', LoginCentralView.as_view(), name='login_web'),
    path('contacto/', TemplateView.as_view(template_name='usuarios/contacto.html'), name='contacto_page'),
    path('contacto/bandeja/', bandeja, name='contacto_bandeja'),
    path('contacto/sincronizar/', sincronizar, name='contacto_sincronizar'),
    path('contacto/mensajes/<int:mensaje_id>/', detalle_mensaje, name='contacto_mensaje'),
    path('contacto/mi-cuenta/', mi_cuenta_contacto, name='contacto_mi_cuenta'),
    path('cerrar-sesion/', logout_web, name='logout_web'),
    path('recuperar-clave/', SolicitarRecuperacionCentralView.as_view(), name='recuperar_clave'),
    path('recuperacion-enviada/', RecuperacionEnviadaView.as_view(), name='recuperacion_enviada'),
    path('restablecer-clave/<uidb64>/<token>/', EstablecerNuevaClaveView.as_view(), name='establecer_nueva_clave'),
    path('clave-actualizada/', ClaveActualizadaView.as_view(), name='clave_actualizada'),
    path('sistema/', inicio_sistema, name='sistema_inicio'),
    path('sistema/empresas/', empresas_sistema, name='sistema_empresas'),
    path('sistema/empresas/nueva/', editar_empresa, name='sistema_nueva_empresa'),
    path('sistema/empresas/<slug:codigo>/', ficha_empresa, name='sistema_ficha_empresa'),
    path('sistema/empresas/<slug:codigo>/editar/', editar_empresa, name='sistema_editar_empresa'),
    path('sistema/usuarios/', usuarios_sistema, name='sistema_usuarios'),
    path('sistema/empresas/<slug:codigo>/usuarios/nuevo/', editar_usuario_empresa, name='sistema_nuevo_usuario_empresa'),
    path('sistema/empresas/<slug:codigo>/usuarios/<int:usuario_id>/', editar_usuario_empresa, name='sistema_editar_usuario_empresa'),
    path('sistema/cuentas/', cuentas_sistema, name='sistema_cuentas'),
    path('sistema/contacto/cuenta/', cuenta_contacto, name='sistema_cuenta_contacto'),
    path('sistema/contacto/conexion/', conexion_contacto, name='sistema_conexion_contacto'),
    path('sistema/cuentas/nueva/', editar_cuenta_tecnica, name='sistema_nueva_cuenta'),
    path('sistema/cuentas/<int:usuario_id>/', editar_cuenta_tecnica, name='sistema_editar_cuenta'),
    path('sistema/mi-cuenta/', mi_cuenta, name='sistema_mi_cuenta'),
    path('sistema/notificaciones/', listar_notificaciones, name='sistema_notificaciones'),
    path('sistema/notificaciones/leer-todas/', leer_todas, name='sistema_notificaciones_leer_todas'),
    path('sistema/notificaciones/<uuid:identificador>/leer/', leer_notificacion, name='sistema_notificacion_leer'),
    path('sistema/auditoria/', auditoria_sistema, name='sistema_auditoria'),
    path('sistema/inventario/', inventario_sistema, name='sistema_inventario'),
    path('sistema/catalogo/', consulta_sistema, {'modulo': 'catalogo'}, name='sistema_catalogo'),
    path('sistema/bodegas/', consulta_sistema, {'modulo': 'bodegas'}, name='sistema_bodegas'),
    path('sistema/movimientos/', consulta_sistema, {'modulo': 'movimientos'}, name='sistema_movimientos'),
    path('sistema/transferencias/', consulta_sistema, {'modulo': 'transferencias'}, name='sistema_transferencias'),
    path('sistema/mermas/', consulta_sistema, {'modulo': 'mermas'}, name='sistema_mermas'),
    path('sistema/reportes/', consulta_sistema, {'modulo': 'reportes'}, name='sistema_reportes'),
    path('sistema/alertas-sms/', consulta_sistema, {'modulo': 'sms'}, name='sistema_sms'),
    path('sistema/configuracion/', sitio_sistema.urls),
    path('admin/', abrir_configuracion),
]
