"""Autorización del cliente, vencimiento y separación del equipo interno."""
from datetime import timedelta
from io import StringIO
import re
from unittest.mock import patch

from django.core import mail
from django.core.cache import cache
from django.core.management import call_command
from django.db import connections
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.empresa import usar_empresa
from apps.core.models import Auditoria
from apps.productos.models import Bodega, Notificacion, Producto, StockBodega
from apps.usuarios.models import Rol, Usuario
from apps.usuarios.tokens import token_recuperacion
from .autorizacion_soporte import ALCANCES, LECTURAS
from .models import AccesoSoporte, AtencionSoporte, Empresa, NotificacionSistema
from .permisos import ADMINISTRADOR_PLATAFORMA, SOPORTE_TECNICO


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
                   EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class PermisosSoporteTests(TestCase):
    databases = {'central', 'ferreteria', 'repuestos'}
    clave = 'Cuenta-fixture-2026-Prueba!'

    @classmethod
    def setUpTestData(cls):
        for codigo, nombre in ((ADMINISTRADOR_PLATAFORMA, 'Administrador de plataforma'), (SOPORTE_TECNICO, 'Soporte técnico')):
            Rol.objects.using('central').get_or_create(codigo=codigo, defaults={'nombre': nombre, 'es_sistema': True})
        call_command('registrar_empresas_prueba', stdout=StringIO())
        cls.fragua = Empresa.objects.get(codigo='la-fragua')
        cls.motor = Empresa.objects.get(codigo='punto-motor')
        for empresa, cantidad in ((cls.fragua, 15), (cls.motor, 4)):
            empresa.contacto_email = 'titular@example.invalid'
            empresa.save(using='central')
            call_command('seed_empresa', empresa.codigo, sin_admin=True, stdout=StringIO())
            with usar_empresa(empresa):
                Usuario.objects.create_user(pk=90, email='cliente@example.invalid', password=cls.clave,
                    nombres=empresa.nombre, rol=Rol.objects.get(codigo='administrador'))
                Usuario.objects.create_user(pk=91, email='operador@example.invalid', password=cls.clave,
                    nombres='Operador', rol=Rol.objects.get(codigo='operador'))
                producto = Producto.objects.create(pk=10, sku='QA-001', nombre=empresa.nombre)
                bodega = Bodega.objects.create(pk=1, nombre='Bodega Central', direccion='Prueba')
                StockBodega.objects.create(producto=producto, bodega=bodega, cantidad_total=cantidad)
        cls.raiz = Usuario.objects.db_manager('central').create_superuser(
            pk=90, email='raiz@example.invalid', password=cls.clave, nombres='Raíz')
        cls.plataforma = Usuario.objects.db_manager('central').create_user(
            pk=91, email='plataforma@example.invalid', password=cls.clave, nombres='Plataforma', is_staff=True,
            rol=Rol.objects.using('central').get(codigo=ADMINISTRADOR_PLATAFORMA))
        cls.soporte = Usuario.objects.db_manager('central').create_user(
            pk=94, email='soporte@example.invalid', password=cls.clave, nombres='Soporte', is_staff=True,
            rol=Rol.objects.using('central').get(codigo=SOPORTE_TECNICO))

    def setUp(self):
        cache.clear()
        self.central = self.cliente(self.soporte)
        self.cliente_fragua = self.cliente_empresa(self.fragua)
        self.cliente_motor = self.cliente_empresa(self.motor)

    def cliente(self, usuario):
        cliente = APIClient(enforce_csrf_checks=True, HTTP_HOST='127.0.0.1:8000')
        cliente.force_login(usuario)
        cliente.get('/sistema/')
        return cliente

    def cliente_empresa(self, empresa, usuario_id=90):
        cliente = APIClient(enforce_csrf_checks=True, HTTP_HOST=empresa.codigo + '.localhost:8000')
        with usar_empresa(empresa):
            cliente.force_login(Usuario.objects.get(pk=usuario_id))
        cliente.get('/')
        cliente.get('/dashboard/')
        return cliente

    def post(self, cliente, ruta, datos):
        with self.captureOnCommitCallbacks(using='central', execute=True), \
                self.captureOnCommitCallbacks(using='ferreteria', execute=True), \
                self.captureOnCommitCallbacks(using='repuestos', execute=True):
            return cliente.post(ruta, datos, HTTP_X_CSRFTOKEN=cliente.cookies['csrftoken'].value)

    def caso(self, tecnico=None, empresa=None):
        return AtencionSoporte.objects.using('central').create(empresa=empresa or self.fragua,
            tecnico=tecnico or self.soporte, asunto='Revisar existencias', motivo='Incidencia reportada por el cliente')

    def solicitar(self, caso, cliente=None, alcances=None, **datos):
        respuesta = self.post(cliente or self.central, f'/sistema/atenciones/{caso.pk}/', {
            'accion': 'solicitar', 'alcances': alcances or ['catalogo'], 'minutos': '30',
            'motivo': 'Revisar las existencias solicitadas por el cliente', **datos})
        self.assertEqual(respuesta.status_code, 302)
        return AccesoSoporte.objects.using('central').get(atencion=caso, estado='pendiente')

    def aprobar(self, acceso, cliente=None, **datos):
        respuesta = self.post(cliente or self.cliente_fragua, '/soporte/', {
            'accion': 'aprobar', 'acceso': str(acceso.pk), **datos})
        self.assertEqual(respuesta.status_code, 302)
        acceso.refresh_from_db(using='central')
        self.assertEqual(acceso.estado, 'aprobado')
        return acceso

    def conceder(self, tecnico=None, empresa=None, alcances=None):
        tecnico, empresa = tecnico or self.soporte, empresa or self.fragua
        caso = self.caso(tecnico, empresa)
        acceso = self.solicitar(caso, self.cliente(tecnico), alcances)
        return self.aprobar(acceso, self.cliente_fragua if empresa.pk == self.fragua.pk else self.cliente_motor)

    def consultar(self, acceso, modulo='catalogo', cliente=None, **datos):
        return (cliente or self.central).get('/sistema/' + modulo + '/', {
            'empresa': acceso.atencion.empresa.codigo, 'atencion': str(acceso.atencion_id), **datos})

    def test_nadie_consulta_operaciones_por_defecto_incluido_superusuario(self):
        for usuario in (self.raiz, self.plataforma, self.soporte):
            cliente = self.cliente(usuario)
            panel = cliente.get('/sistema/')
            rutas = [e['url'] for s in panel.context['secciones_menu'] for e in s['enlaces']]
            self.assertFalse(any('/catalogo/' in ruta or '/inventario/' in ruta for ruta in rutas))
            for modulo in ('inventario', 'catalogo', 'bodegas', 'reportes', 'movimientos', 'transferencias', 'mermas', 'alertas-sms'):
                self.assertIn(cliente.get(f'/sistema/{modulo}/?empresa=la-fragua').status_code, (403, 404))
        self.assertEqual(self.central.get('/sistema/empresas/la-fragua/').status_code, 404)

    def test_solicitud_aprobacion_lectura_y_revocacion_del_cliente(self):
        caso = self.caso()
        acceso = self.solicitar(caso)
        self.assertEqual(self.consultar(acceso).status_code, 403)
        pagina = self.cliente_fragua.get('/soporte/')
        self.assertContains(pagina, acceso.motivo)
        self.assertContains(pagina, 'Consultar catálogo y stock')
        self.assertContains(pagina, self.soporte.nombre_completo)
        self.assertEqual(self.central.post('/sistema/atenciones/' + str(caso.pk) + '/', {'accion': 'solicitar'}).status_code, 403)
        self.aprobar(acceso)
        self.assertEqual(acceso.aprobador_id, 90)
        self.assertEqual(acceso.aprobador_email, 'cliente@example.invalid')
        self.assertEqual(acceso.expira_en - acceso.decidido_en, timedelta(minutes=30))
        pagina = self.consultar(acceso)
        self.assertEqual(pagina.status_code, 200)
        self.assertEqual(pagina.context['filas'][0]['celdas'][1:3], [self.fragua.nombre, 15])
        self.assertContains(pagina, 'Acceso temporal autorizado')
        self.assertEqual(self.consultar(acceso, 'movimientos').status_code, 403)
        self.assertEqual(self.post(self.cliente_fragua, '/soporte/', {'accion': 'revocar', 'acceso': str(acceso.pk)}).status_code, 302)
        self.assertEqual(self.consultar(acceso).status_code, 403)

    def test_permisos_y_duracion_no_se_amplian_al_aprobar_o_repetir(self):
        acceso = self.solicitar(self.caso())
        self.aprobar(acceso, alcances=['catalogo', 'exportar'], minutos='9999', expira_en='2099-01-01')
        self.assertEqual(acceso.alcances, ['catalogo'])
        self.assertEqual(acceso.minutos, 30)
        vencimiento = acceso.expira_en
        respuesta = self.post(self.cliente_fragua, '/soporte/', {'accion': 'aprobar', 'acceso': str(acceso.pk)})
        self.assertContains(respuesta, 'Esta solicitud ya fue resuelta')
        acceso.refresh_from_db(using='central')
        self.assertEqual(acceso.expira_en, vencimiento)

    def test_renovar_reemplaza_permisos_previos_y_revocar_no_recupera_una_autorizacion_anterior(self):
        anterior = self.conceder()
        actual = self.solicitar(anterior.atencion, alcances=['bodegas'])
        self.aprobar(actual)
        anterior.refresh_from_db(using='central')
        self.assertEqual(anterior.estado, 'revocado')
        self.assertEqual(self.consultar(actual).status_code, 403)
        self.assertEqual(self.consultar(actual, 'bodegas').status_code, 200)
        self.assertEqual(self.post(self.cliente_fragua, '/soporte/', {'accion': 'revocar', 'acceso': str(actual.pk)}).status_code, 302)
        self.assertEqual(self.consultar(anterior).status_code, 403)
        self.assertEqual(self.consultar(actual, 'bodegas').status_code, 403)

    def test_otra_empresa_operador_o_usuario_central_no_pueden_aprobar(self):
        acceso = self.solicitar(self.caso())
        self.assertEqual(self.post(self.cliente_motor, '/soporte/', {'accion': 'aprobar', 'acceso': str(acceso.pk)}).status_code, 403)
        operador = self.cliente_empresa(self.fragua, 91)
        self.assertEqual(operador.get('/soporte/').status_code, 403)
        self.assertEqual(self.post(operador, '/soporte/', {'accion': 'aprobar', 'acceso': str(acceso.pk)}).status_code, 403)
        self.assertEqual(self.cliente(self.raiz).get('/soporte/').status_code, 404)
        acceso.refresh_from_db(using='central')
        self.assertEqual(acceso.estado, 'pendiente')
        self.assertEqual(self.cliente_fragua.post('/soporte/', {'accion': 'aprobar', 'acceso': str(acceso.pk)}).status_code, 403)

    def test_cliente_puede_rechazar_y_no_sustituye_la_solicitud_por_un_uuid_falso(self):
        acceso = self.solicitar(self.caso())
        self.assertEqual(self.post(self.cliente_fragua, '/soporte/', {'accion': 'rechazar', 'acceso': str(acceso.pk)}).status_code, 302)
        self.assertEqual(self.consultar(acceso).status_code, 403)
        self.assertContains(self.post(self.cliente_fragua, '/soporte/', {'accion': 'aprobar', 'acceso': 'invalido'}), 'no es un UUID válido')

    def test_ambito_fijo_no_se_cambia_con_empresa_o_id_de_otra_atencion(self):
        acceso = self.conceder()
        self.assertEqual(self.consultar(acceso, empresa='punto-motor').status_code, 404)
        ajena = self.caso(self.plataforma, self.motor)
        self.assertEqual(self.consultar(acceso, atencion=str(ajena.pk)).status_code, 403)
        self.assertEqual(self.consultar(acceso, atencion='incorrecta').status_code, 403)
        otro = self.conceder(empresa=self.motor)
        pagina = self.consultar(otro)
        self.assertEqual(pagina.context['filas'][0]['celdas'][1:3], [self.motor.nombre, 4])
        self.assertEqual(self.consultar(acceso).context['filas'][0]['celdas'][2], 15)

    def test_vencimiento_bloquea_lectura_y_menu_en_la_siguiente_peticion(self):
        acceso = self.conceder()
        AccesoSoporte.objects.using('central').filter(pk=acceso.pk).update(
            decidido_en=timezone.now() - timedelta(hours=2), expira_en=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.consultar(acceso).status_code, 403)
        pagina = self.central.get(f'/sistema/atenciones/{acceso.atencion_id}/')
        self.assertContains(pagina, 'Vencido')
        self.assertNotContains(pagina, 'href="/sistema/catalogo/')

    def test_reasignar_revoca_incluso_si_se_asigna_despues_al_mismo_tecnico(self):
        acceso = self.conceder()
        caso = acceso.atencion
        gestor = self.cliente(self.plataforma)
        for tecnico in (self.plataforma, self.soporte):
            respuesta = self.post(gestor, f'/sistema/atenciones/{caso.pk}/', {'accion': 'asignar',
                'empresa': self.fragua.pk, 'tecnico': tecnico.pk, 'asunto': caso.asunto, 'motivo': caso.motivo})
            self.assertEqual(respuesta.status_code, 302)
        acceso.refresh_from_db(using='central')
        self.assertEqual(acceso.estado, 'revocado')
        self.assertEqual(self.consultar(acceso).status_code, 403)

    def test_cerrar_por_tecnico_o_por_cliente_revoca(self):
        for quien in ('tecnico', 'cliente'):
            acceso = self.conceder()
            if quien == 'tecnico':
                respuesta = self.post(self.central, f'/sistema/atenciones/{acceso.atencion_id}/',
                    {'accion': 'cerrar', 'resolucion': 'Se resolvió la incidencia con el cliente'})
            else:
                respuesta = self.post(self.cliente_fragua, '/soporte/', {'accion': 'cerrar', 'atencion': str(acceso.atencion_id)})
            self.assertEqual(respuesta.status_code, 302)
            acceso.refresh_from_db(using='central')
            self.assertEqual(acceso.estado, 'revocado')
            self.assertEqual(self.consultar(acceso).status_code, 404)

    def test_cuenta_o_rol_desactivados_y_empresa_suspendida_bloquean_permiso(self):
        acceso = self.conceder()
        Usuario.objects.using('central').filter(pk=self.soporte.pk).update(activo=False)
        self.assertEqual(self.consultar(acceso).status_code, 403)
        Usuario.objects.using('central').filter(pk=self.soporte.pk).update(activo=True)
        Rol.objects.using('central').filter(pk=self.soporte.rol_id).update(activo=False)
        self.assertEqual(self.consultar(acceso).status_code, 403)
        Rol.objects.using('central').filter(pk=self.soporte.rol_id).update(activo=True)
        Empresa.objects.using('central').filter(pk=self.fragua.pk).update(activa=False)
        self.assertEqual(self.consultar(acceso).status_code, 403)

    def test_suspension_desde_ficha_revoca_sin_rehabilitar_al_reactivar(self):
        acceso = self.conceder()
        gestor = self.cliente(self.plataforma)
        for activa in ('', 'on'):
            self.assertEqual(self.post(gestor, '/sistema/empresas/la-fragua/editar/',
                {'nombre': self.fragua.nombre, 'codigo': 'la-fragua', 'activa': activa}).status_code, 302)
        acceso.refresh_from_db(using='central')
        self.assertEqual(acceso.estado, 'revocado')
        self.assertEqual(self.consultar(acceso).status_code, 403)

    def test_suspension_en_configuracion_avanzada_tambien_revoca(self):
        acceso = self.conceder()
        raiz = self.cliente(self.raiz)
        ruta = f'/sistema/configuracion/empresas/empresa/{self.fragua.pk}/change/'
        datos = {'nombre': self.fragua.nombre, 'codigo': 'la-fragua', 'alias_bd': 'ferreteria'}
        self.assertEqual(self.post(raiz, ruta, datos).status_code, 302)
        acceso.refresh_from_db(using='central')
        self.assertEqual(acceso.estado, 'revocado')

    def test_soporte_no_solicita_ni_utiliza_permisos_de_gestion_o_exportacion(self):
        caso = self.caso()
        for alcances in (['reportes', 'exportar'], ['usuarios', 'gestionar_usuarios'], ['catalogo', 'desconocido']):
            respuesta = self.post(self.central, f'/sistema/atenciones/{caso.pk}/', {
                'accion': 'solicitar', 'alcances': alcances, 'minutos': 30, 'motivo': 'Motivo suficientemente largo'})
            self.assertEqual(respuesta.status_code, 200)
            self.assertFalse(AccesoSoporte.objects.using('central').filter(atencion=caso).exists())
        acceso = self.conceder(alcances=['reportes', 'usuarios'])
        AccesoSoporte.objects.using('central').filter(pk=acceso.pk).update(alcances=['reportes', 'usuarios', 'exportar', 'gestionar_usuarios'])
        self.assertEqual(self.consultar(acceso, 'reportes', exportar='csv').status_code, 403)
        self.assertEqual(self.central.get(f'/sistema/empresas/la-fragua/usuarios/nuevo/?atencion={caso.pk}').status_code, 403)

    def test_solicitudes_invalidas_no_se_guardan_y_solo_hay_una_pendiente(self):
        caso = self.caso()
        for datos in ({'minutos': '9999'}, {'minutos': '0'}, {'motivo': 'corto'}, {'alcances': []}):
            respuesta = self.post(self.central, f'/sistema/atenciones/{caso.pk}/', {
                'accion': 'solicitar', 'alcances': ['catalogo'], 'minutos': '30', 'motivo': 'Incidencia que debemos revisar', **datos})
            self.assertEqual(respuesta.status_code, 200)
            self.assertFalse(AccesoSoporte.objects.using('central').exists())
        self.solicitar(caso)
        respuesta = self.post(self.central, f'/sistema/atenciones/{caso.pk}/', {
            'accion': 'solicitar', 'alcances': ['catalogo'], 'minutos': 30, 'motivo': 'Solicitud repetida para la revisión'})
        self.assertContains(respuesta, 'Ya hay una solicitud pendiente')
        self.assertEqual(AccesoSoporte.objects.using('central').count(), 1)

    def test_exportar_requiere_aprobacion_separada_y_lectura_del_reporte(self):
        acceso = self.conceder(self.plataforma, alcances=['reportes'])
        gestor = self.cliente(self.plataforma)
        self.assertEqual(self.consultar(acceso, 'reportes', gestor).status_code, 200)
        self.assertEqual(self.consultar(acceso, 'reportes', gestor, exportar='csv').status_code, 403)
        self.assertNotContains(self.consultar(acceso, 'reportes', gestor), '>Exportar CSV<')
        otro = self.conceder(self.plataforma, alcances=['reportes', 'exportar'])
        for formato in ('csv', 'pdf'):
            respuesta = self.consultar(otro, 'reportes', gestor, exportar=formato, informe='existencias')
            self.assertEqual(respuesta.status_code, 200)
        self.post(self.cliente_fragua, '/soporte/', {'accion': 'revocar', 'acceso': str(otro.pk)})
        self.assertEqual(self.consultar(otro, 'reportes', gestor, exportar='csv').status_code, 403)

    def test_consulta_no_concede_escrituras_stock_por_post(self):
        acceso = self.conceder(alcances=list(LECTURAS))
        for modulo in ('catalogo', 'bodegas', 'inventario', 'movimientos', 'transferencias', 'mermas'):
            respuesta = self.post(self.central, f'/sistema/{modulo}/?empresa=la-fragua&atencion={acceso.atencion_id}', {'cantidad': 999})
            self.assertEqual(respuesta.status_code, 405)
        self.assertEqual(StockBodega.objects.using('ferreteria').get(producto_id=10).cantidad_total, 15)

    def test_equipo_menu_configuracion_y_buzon_respetan_los_tres_perfiles(self):
        for usuario in (self.raiz, self.plataforma, self.soporte):
            cliente = self.cliente(usuario)
            self.assertEqual(cliente.get('/sistema/mi-cuenta/').status_code, 200)
            self.assertEqual(cliente.get('/sistema/diagnostico/').status_code, 200)
            self.assertEqual(cliente.get('/sistema/cuentas/').status_code, 200 if usuario.is_superuser else 403)
            self.assertEqual(cliente.get('/sistema/configuracion/').status_code, 200 if usuario.is_superuser else 403)
            self.assertEqual(cliente.get('/contacto/bandeja/').status_code, 403)

    def test_soporte_solo_ve_sus_atenciones_y_fichas_sin_consultar_bases_cliente(self):
        propia = self.caso()
        ajena = self.caso(self.plataforma, self.motor)
        self.assertEqual(self.central.get(f'/sistema/atenciones/{ajena.pk}/').status_code, 404)
        with patch('esquema_multiempresa.sistema.Usuario.objects.filter', side_effect=AssertionError('consulta de cliente no autorizada')):
            panel = self.central.get('/sistema/')
            ficha = self.central.get('/sistema/empresas/la-fragua/')
            empresas = self.central.get('/sistema/empresas/')
        self.assertContains(panel, propia.asunto)
        self.assertEqual(ficha.status_code, 200)
        self.assertEqual(empresas.status_code, 200)
        self.assertNotContains(panel, self.motor.nombre)
        self.assertNotContains(ficha, '>Base asignada<')

    def test_crear_atencion_no_permite_asignarse_una_empresa_ajena(self):
        datos = {'empresa': self.fragua.pk, 'tecnico': self.soporte.pk, 'asunto': 'Nueva atención', 'motivo': 'Consulta nueva del cliente'}
        respuesta = self.post(self.central, '/sistema/atenciones/nueva/', datos)
        self.assertEqual(respuesta.status_code, 200)
        self.assertFalse(AtencionSoporte.objects.using('central').exists())
        gestor = self.cliente(self.plataforma)
        respuesta = self.post(gestor, '/sistema/atenciones/nueva/', datos)
        self.assertEqual(respuesta.status_code, 302)
        caso = AtencionSoporte.objects.using('central').get()
        self.assertEqual((caso.empresa_id, caso.tecnico_id), (self.fragua.pk, self.soporte.pk))

    def test_filtros_y_contadores_de_atenciones_incluyen_todos_los_resultados(self):
        AtencionSoporte.objects.using('central').bulk_create([
            AtencionSoporte(empresa=self.fragua, asunto=f'Acceso pendiente {numero}', motivo='Solicitud de prueba')
            for numero in range(26)
        ] + [
            AtencionSoporte(empresa=self.fragua, asunto='Acceso resuelto', motivo='Solicitud de prueba', estado='cerrada'),
            AtencionSoporte(empresa=self.motor, tecnico=self.plataforma, asunto='Acceso motor', motivo='Solicitud de prueba'),
        ])
        gestor = self.cliente(self.plataforma)
        pagina = gestor.get('/sistema/atenciones/', {'empresa': 'la-fragua', 'search': 'acceso'})
        self.assertEqual(pagina.context['resumen_atenciones'], {'abiertas': 26, 'cerradas': 1, 'sin_responsable': 26})
        self.assertEqual(pagina.context['pagina'].paginator.count, 27)
        siguiente = gestor.get('/sistema/atenciones/', {
            'empresa': 'la-fragua', 'search': 'acceso', 'estado': 'abierta', 'page': '2'})
        self.assertEqual(len(siguiente.context['atenciones']), 1)
        self.assertEqual(siguiente.context['resumen_atenciones'], {'abiertas': 26, 'cerradas': 0, 'sin_responsable': 26})
        for parametro in ('empresa=la-fragua', 'search=acceso', 'estado=abierta'):
            self.assertIn(parametro, siguiente.context['filtros_pagina'])
        self.assertNotIn('page=', siguiente.context['filtros_pagina'])
        self.assertContains(siguiente, 'aria-label="Páginas del listado"')
        cerradas = gestor.get('/sistema/atenciones/', {'empresa': 'la-fragua', 'estado': 'cerrada'})
        self.assertEqual(cerradas.context['resumen_atenciones'], {'abiertas': 0, 'cerradas': 1, 'sin_responsable': 0})
        self.assertNotContains(cerradas, 'aria-label="Páginas del listado"')
        self.assertContains(cerradas, '1–1 de 1 registro')
        vacia = gestor.get('/sistema/atenciones/', {'search': 'No coincide con ninguna solicitud'})
        self.assertContains(vacia, 'No hay atenciones que coincidan con los filtros.')
        self.assertEqual(vacia.context['resumen_atenciones'], {'abiertas': 0, 'cerradas': 0, 'sin_responsable': 0})

    def test_filtro_de_historial_propio_no_revela_atenciones_ajenas_ni_habilita_inventario(self):
        self.caso(self.soporte, self.fragua)
        cerrada = self.caso(self.soporte, self.motor)
        cerrada.estado = 'cerrada'
        cerrada.save(using='central')
        ajena = self.caso(self.plataforma, self.motor)
        ajena.asunto = 'Solicitud ajena confidencial'
        ajena.save(using='central')
        pagina = self.central.get('/sistema/atenciones/', {'empresa': 'punto-motor'})
        self.assertEqual(pagina.status_code, 200)
        self.assertEqual([a.pk for a in pagina.context['atenciones']], [cerrada.pk])
        self.assertEqual(pagina.context['resumen_atenciones'], {'abiertas': 0, 'cerradas': 1, 'sin_responsable': 0})
        self.assertNotContains(pagina, ajena.asunto)
        self.assertIsNone(pagina.context['empresa_seleccionada'])
        self.assertEqual(self.central.get('/sistema/inventario/', {'empresa': 'punto-motor'}).status_code, 404)
        empresa_ajena = Empresa.objects.using('central').create(codigo='ajena', nombre='Empresa privada', alias_bd='ajena')
        self.caso(self.plataforma, empresa_ajena)
        invalida = self.central.get('/sistema/atenciones/', {'empresa': 'ajena'})
        self.assertTrue(invalida.context['formulario_filtros'].errors.get('empresa'))
        self.assertFalse(invalida.context['atenciones'])
        self.assertNotContains(invalida, empresa_ajena.nombre)

    def test_creacion_de_atencion_admite_responsable_pendiente_para_gestores(self):
        gestor = self.cliente(self.raiz)
        formulario = gestor.get('/sistema/atenciones/nueva/')
        self.assertContains(formulario, 'Crear atención')
        self.assertNotContains(formulario, '>Guardar cambios<')
        self.assertEqual(formulario.context['formulario'].fields['empresa'].empty_label, 'Selecciona una empresa')
        self.assertFalse(formulario.context['formulario'].fields['tecnico'].required)
        respuesta = self.post(gestor, '/sistema/atenciones/nueva/', {
            'empresa': self.fragua.pk, 'tecnico': '', 'asunto': 'Ayuda para ingresar',
            'motivo': 'La empresa solicita ayuda para acceder al sistema.'})
        self.assertEqual(respuesta.status_code, 302)
        creada = AtencionSoporte.objects.using('central').get(asunto='Ayuda para ingresar')
        self.assertIsNone(creada.tecnico_id)
        self.assertEqual(creada.empresa_id, self.fragua.pk)

    def test_cliente_crea_consulta_sin_elegir_otra_empresa_ni_un_tecnico(self):
        respuesta = self.post(self.cliente_fragua, '/soporte/', {'accion': 'nueva', 'asunto': 'Ayuda de mi empresa',
            'motivo': 'Necesito revisar las existencias', 'empresa': self.motor.pk, 'tecnico': self.raiz.pk})
        self.assertEqual(respuesta.status_code, 302)
        caso = AtencionSoporte.objects.using('central').get()
        self.assertEqual(caso.empresa_id, self.fragua.pk)
        self.assertIsNone(caso.tecnico_id)
        self.assertSetEqual(set(NotificacionSistema.objects.using('central').values_list('destinatario_id', flat=True)), {90, 91})

    def test_avisos_y_auditoria_usan_actor_y_destinatario_de_su_base(self):
        caso = self.caso()
        acceso = self.solicitar(caso)
        aviso = Notificacion.objects.using('ferreteria').get()
        self.assertEqual(aviso.usuario_destino_id, 90)
        self.assertEqual(aviso.link, '/soporte/')
        self.assertFalse(Notificacion.objects.using('repuestos').exists())
        self.aprobar(acceso)
        evento = Auditoria.objects.using('central').filter(modelo='AtencionSoporte', accion='UPDATE').latest('id')
        self.assertIsNone(evento.usuario_id)
        self.assertIn('cliente@example.invalid', evento.descripcion)
        self.assertTrue(NotificacionSistema.objects.using('central').filter(destinatario_id=94, link=f'/sistema/atenciones/{caso.pk}/').exists())
        self.consultar(acceso)
        lectura = Auditoria.objects.using('central').latest('id')
        self.assertIn(str(caso.pk), lectura.descripcion)
        self.assertIn(acceso.motivo, lectura.descripcion)

    def test_auditoria_de_soporte_no_revela_actividades_ajenas_del_equipo(self):
        Auditoria.objects.using('central').create(usuario=self.raiz, accion='UPDATE', modelo='Usuario', objeto_id='90', descripcion='SECRETO DE CONFIGURACIÓN')
        self.assertNotContains(self.central.get('/sistema/auditoria/'), 'SECRETO DE CONFIGURACIÓN')
        self.assertNotContains(self.cliente(self.plataforma).get('/sistema/auditoria/'), 'SECRETO DE CONFIGURACIÓN')
        self.assertContains(self.cliente(self.raiz).get('/sistema/auditoria/'), 'SECRETO DE CONFIGURACIÓN')

    def test_gestion_autorizada_no_permite_elegir_clave_o_cambiar_correo_existente(self):
        acceso = self.conceder(self.plataforma, alcances=['usuarios', 'gestionar_usuarios'])
        gestor = self.cliente(self.plataforma)
        ruta = f'/sistema/empresas/la-fragua/usuarios/91/?atencion={acceso.atencion_id}'
        pagina = gestor.get(ruta)
        self.assertNotIn('password1', pagina.context['formulario'].fields)
        rol = Rol.objects.using('ferreteria').get(codigo='operador')
        respuesta = self.post(gestor, ruta, {'email': 'atacante@example.invalid', 'nombres': 'Nombre editado', 'apellidos': 'Prueba',
            'telefono': '', 'activo': 'on', 'rol': rol.pk, 'password1': 'ClaveImpuesta', 'password2': 'ClaveImpuesta',
            'is_superuser': 'on', 'is_staff': 'on'})
        self.assertEqual(respuesta.status_code, 302)
        usuario = Usuario.objects.using('ferreteria').get(pk=91)
        self.assertEqual(usuario.email, 'operador@example.invalid')
        self.assertTrue(usuario.check_password(self.clave))
        self.assertFalse(usuario.is_superuser or usuario.is_staff)
        self.assertEqual(Usuario.objects.using('repuestos').get(pk=91).nombres, 'Operador')
        self.assertEqual(Usuario.objects.using('central').get(pk=91).nombres, 'Plataforma')

    def test_ultimo_administrador_no_puede_quedar_suspendido_por_el_equipo(self):
        acceso = self.conceder(self.plataforma, alcances=['usuarios', 'gestionar_usuarios'])
        rol = Rol.objects.using('ferreteria').get(codigo='operador')
        respuesta = self.post(self.cliente(self.plataforma), f'/sistema/empresas/la-fragua/usuarios/90/?atencion={acceso.atencion_id}',
            {'email': 'cliente@example.invalid', 'nombres': 'Cliente', 'apellidos': 'Prueba', 'rol': rol.pk})
        self.assertContains(respuesta, 'conservar al menos un administrador activo', msg_prefix=str(respuesta.context['formulario'].errors))
        usuario = Usuario.objects.using('ferreteria').select_related('rol').get(pk=90)
        self.assertTrue(usuario.activo)
        self.assertEqual(usuario.rol.codigo, 'administrador')

    def test_recuperacion_tiene_permiso_propio_y_solo_envia_al_correo_registrado(self):
        acceso = self.conceder(alcances=['usuarios'])
        ruta = f'/sistema/empresas/la-fragua/usuarios/91/recuperar/?atencion={acceso.atencion_id}'
        self.assertEqual(self.post(self.central, ruta, {'email': 'atacante@example.invalid'}).status_code, 403)
        otro = self.conceder(alcances=['usuarios', 'recuperar_acceso'])
        ruta = f'/sistema/empresas/la-fragua/usuarios/91/recuperar/?atencion={otro.atencion_id}'
        self.assertEqual(self.post(self.central, ruta, {'email': 'atacante@example.invalid'}).status_code, 302)
        self.assertEqual(mail.outbox[-1].to, ['operador@example.invalid'])
        self.assertIn('http://la-fragua.localhost:8000/', mail.outbox[-1].body)
        self.assertNotIn('punto-motor.localhost', mail.outbox[-1].body)
        token = re.search(r'/restablecer-clave/[^/]+/([^/]+)/', mail.outbox[-1].body)
        self.assertIsNotNone(token)
        token = token.group(1)
        with usar_empresa(self.fragua):
            self.assertTrue(token_recuperacion.check_token(Usuario.objects.get(pk=91), token))
        with usar_empresa(self.motor):
            self.assertFalse(token_recuperacion.check_token(Usuario.objects.get(pk=91), token))
        self.assertFalse(Auditoria.objects.using('central').filter(descripcion__contains=token).exists())
        self.assertEqual(self.post(self.central, ruta, {}).status_code, 302)
        self.assertEqual(len(mail.outbox), 1)

    def test_invitacion_inicial_fija_destinatario_y_reenvio_no_invalida_enlace(self):
        Usuario.objects.using('ferreteria').all().delete()
        gestor = self.cliente(self.plataforma)
        ruta = '/sistema/empresas/la-fragua/invitar-administrador/'
        datos = {'nombres': 'Titular', 'apellidos': 'Prueba', 'email': 'atacante@example.invalid', 'confirmar': 'on',
            'password1': 'ClaveElegidaPorTecnico', 'is_superuser': 'on'}
        respuesta = self.post(gestor, ruta, datos)
        self.assertEqual(respuesta.status_code, 302)
        usuario = Usuario.objects.using('ferreteria').get()
        self.assertEqual(usuario.email, self.fragua.contacto_email)
        self.assertFalse(usuario.has_usable_password() or usuario.is_superuser or usuario.is_staff)
        self.assertEqual(mail.outbox[-1].to, [self.fragua.contacto_email])
        hash_anterior = usuario.password
        self.assertEqual(self.post(gestor, ruta, datos).status_code, 302)
        usuario.refresh_from_db(using='ferreteria')
        self.assertEqual(usuario.password, hash_anterior)
        self.assertEqual(len(mail.outbox), 1)

    def test_invitacion_inicial_no_sustituye_administrador_inactivo_o_operador_existente(self):
        gestor = self.cliente(self.plataforma)
        ruta = '/sistema/empresas/la-fragua/invitar-administrador/'
        Usuario.objects.using('ferreteria').filter(pk=90).update(activo=False)
        self.assertEqual(gestor.get(ruta).status_code, 403)
        Usuario.objects.using('ferreteria').filter(pk=90).delete()
        self.assertEqual(gestor.get(ruta).status_code, 403)
        self.assertFalse(mail.outbox)

    def test_invitado_establece_su_clave_desde_el_enlace_y_solo_esa_empresa(self):
        Usuario.objects.using('ferreteria').all().delete()
        self.post(self.cliente(self.plataforma), '/sistema/empresas/la-fragua/invitar-administrador/',
            {'nombres': 'Titular', 'apellidos': 'Prueba', 'confirmar': 'on'})
        ruta = re.search(r'http://la-fragua.localhost:8000(/restablecer-clave/[^\s]+)', mail.outbox[-1].body).group(1)
        cliente = APIClient(enforce_csrf_checks=True, HTTP_HOST='la-fragua.localhost:8000')
        respuesta = cliente.get(ruta)
        self.assertEqual(respuesta.status_code, 302)
        self.assertContains(cliente.get(respuesta.url), 'name="new_password1"')
        cambio = self.post(cliente, respuesta.url, {'new_password1': 'Nueva-clave-del-titular-2026!', 'new_password2': 'Nueva-clave-del-titular-2026!'})
        self.assertEqual(cambio.status_code, 302)
        usuario = Usuario.objects.using('ferreteria').get(email=self.fragua.contacto_email)
        self.assertTrue(usuario.check_password('Nueva-clave-del-titular-2026!'))
        self.assertFalse(Usuario.objects.using('repuestos').filter(email=usuario.email).exists())
        self.assertEqual(self.cliente(self.plataforma).get('/sistema/empresas/la-fragua/invitar-administrador/').status_code, 403)

    def test_borrar_usuario_cliente_no_consulta_tablas_exclusivas_de_central(self):
        caso = self.caso(self.plataforma)
        acceso = self.conceder(self.plataforma, alcances=['catalogo'])
        for alias in ('ferreteria', 'repuestos'):
            self.assertNotIn('atenciones_soporte', connections[alias].introspection.table_names())
            self.assertNotIn('accesos_soporte', connections[alias].introspection.table_names())
        with usar_empresa(self.fragua):
            Usuario.objects.get(pk=91).delete()
        caso.refresh_from_db(using='central')
        acceso.refresh_from_db(using='central')
        self.assertEqual(caso.tecnico_id, 91)
        self.assertEqual(acceso.tecnico_id, 91)
        self.assertTrue(Usuario.objects.using('central').filter(pk=91).exists())
        from .admin_central import RecolectorCuentasCentrales
        recolector = RecolectorCuentasCentrales()
        recolector.collect(Usuario.objects.using('central').filter(pk=91))
        recolector.delete()
        caso.refresh_from_db(using='central')
        acceso.refresh_from_db(using='central')
        self.assertIsNone(caso.tecnico_id)
        self.assertIsNone(acceso.tecnico_id)


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ConcurrenciaSoporteTests(TransactionTestCase):
    databases = {'central', 'ferreteria', 'repuestos'}
    clave = PermisosSoporteTests.clave

    def test_aprobar_dos_veces_concurrentemente_no_extiende_ni_duplica_permiso(self):
        if connections['central'].vendor != 'postgresql':
            self.skipTest('Bloqueos de fila verificados con PostgreSQL real.')
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from .soporte_operaciones import decidir_acceso
        PermisosSoporteTests.setUpTestData.__func__(type(self))
        caso = AtencionSoporte.objects.using('central').create(empresa=self.fragua, tecnico=self.soporte,
            asunto='Prueba concurrente', motivo='Verificar decisiones simultáneas')
        acceso = AccesoSoporte.objects.using('central').create(atencion=caso, tecnico=self.soporte,
            alcances=['catalogo'], minutos=15, motivo='Verificar una autorización concurrente')
        barrera = Barrier(2)

        def decidir():
            connections.close_all()
            try:
                empresa = Empresa.objects.using('central').get(pk=self.fragua.pk)
                with usar_empresa(empresa):
                    request = RequestFactory().post('/soporte/')
                    request.empresa = empresa
                    request.user = Usuario.objects.select_related('rol').get(pk=90)
                    barrera.wait(timeout=10)
                    try:
                        resultado = decidir_acceso(request, acceso.pk, 'aprobar')
                        return ('aprobado', resultado.expira_en)
                    except ValidationError:
                        return ('resuelto', None)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as ejecutor:
            resultados = list(ejecutor.map(lambda _: decidir(), range(2)))
        self.assertEqual(sorted(r[0] for r in resultados), ['aprobado', 'resuelto'])
        acceso.refresh_from_db(using='central')
        self.assertEqual(acceso.expira_en - acceso.decidido_en, timedelta(minutes=15))
        self.assertEqual(acceso.expira_en, next(r[1] for r in resultados if r[0] == 'aprobado'))
        self.assertEqual(AccesoSoporte.objects.using('central').count(), 1)
