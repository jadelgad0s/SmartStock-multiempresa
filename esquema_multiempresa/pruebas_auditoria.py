"""Auditoría investigable, historia fiel y autorización idéntica en cada salida."""
import csv
from datetime import datetime, timezone as utc
from io import StringIO

from django.test import TestCase, TransactionTestCase, override_settings
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from apps.core.models import Auditoria
from apps.core.registro_auditoria import crear_evento
from apps.usuarios.models import Usuario
from . import pruebas_soporte as soporte
from .models import AccesoSoporte, AtencionSoporte


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'], TIME_ZONE='America/Santiago')
class AuditoriaInvestigacionTests(TestCase):
    databases = {'central', 'ferreteria', 'repuestos'}
    clave = soporte.PermisosSoporteTests.clave
    cliente = soporte.PermisosSoporteTests.cliente
    cliente_empresa = soporte.PermisosSoporteTests.cliente_empresa
    post = soporte.PermisosSoporteTests.post
    caso = soporte.PermisosSoporteTests.caso
    solicitar = soporte.PermisosSoporteTests.solicitar
    aprobar = soporte.PermisosSoporteTests.aprobar
    conceder = soporte.PermisosSoporteTests.conceder

    @classmethod
    def setUpTestData(cls):
        soporte.PermisosSoporteTests.setUpTestData.__func__(cls)

    def setUp(self):
        soporte.PermisosSoporteTests.setUp(self)
        self.raiz_web = self.cliente(self.raiz)

    def evento(self, **campos):
        datos = dict(alias='central', usuario=self.raiz, accion='UPDATE', modelo='Empresa', empresa=self.fragua,
                     objeto_id=self.fragua.pk, descripcion='Cambio de ficha de prueba', operacion='Ficha actualizada')
        datos.update(campos)
        return crear_evento(**datos)

    def csv(self, respuesta):
        self.assertEqual(respuesta.status_code, 200)
        filas = list(csv.reader(StringIO(b''.join(respuesta.streaming_content).decode('utf-8-sig')), delimiter=';'))
        indice = next(i for i, fila in enumerate(filas) if fila and fila[0] == 'ID')
        return filas[indice + 1:]

    def test_historicos_no_se_reescriben_ni_inventan_resultado_o_perfil(self):
        evento = Auditoria.objects.using('central').create(usuario=self.raiz, accion='UPDATE',
            modelo='MensajeContacto', descripcion='Texto histórico intacto')
        antes = Auditoria.objects.using('central').filter(pk=evento.pk).values().get()
        pagina = self.raiz_web.get(f'/sistema/auditoria/{evento.pk}/')
        self.assertContains(pagina, 'Texto histórico intacto')
        self.assertContains(pagina, 'No registrado')
        self.assertContains(pagina, 'Buzón de contacto')
        self.assertContains(pagina, 'datos actuales')
        self.assertEqual(Auditoria.objects.using('central').filter(pk=evento.pk).values().get(), antes)

    def test_identidad_y_empresa_del_momento_sobreviven_renombre_y_eliminacion(self):
        persona = Usuario.objects.db_manager('central').create_user(email='historica@example.invalid',
            nombres='Persona histórica', is_staff=True, rol=self.soporte.rol)
        evento = self.evento(usuario=persona)
        Usuario.objects.using('central').filter(pk=persona.pk).update(nombres='Nombre posterior', email='otro@example.invalid')
        ruta = f'/sistema/configuracion/usuarios/usuario/{persona.pk}/delete/'
        self.assertEqual(self.post(self.raiz_web, ruta, {'post': 'yes'}).status_code, 302)
        pagina = self.raiz_web.get(f'/sistema/auditoria/{evento.pk}/')
        self.assertContains(pagina, 'Persona histórica')
        self.assertContains(pagina, 'historica@example.invalid')
        self.assertContains(pagina, 'Soporte técnico')
        self.assertNotContains(pagina, 'Nombre posterior')
        evento.refresh_from_db(using='central')
        self.assertIsNone(evento.usuario_id)
        self.assertEqual(evento.actor['origen'], 'smartstock')

    def test_filtros_combinados_y_busqueda_por_identidad_historica_antes_de_paginar(self):
        for _ in range(28):
            self.evento(operacion='Ficha marcada ABC-99')
        self.evento(usuario=self.plataforma)
        pagina = self.raiz_web.get('/sistema/auditoria/', {
            'actor': f'smartstock:{self.raiz.pk}', 'accion': 'UPDATE', 'modulo': 'Empresas',
            'resultado': 'completada', 'search': 'ABC-99', 'page': 2, 'agrupar': '0'})
        self.assertEqual(pagina.status_code, 200)
        self.assertEqual(pagina.context['pagina'].paginator.count, 28)
        self.assertEqual(len(pagina.context['eventos']), 3)
        for enlace in pagina.context['paginas']:
            if not enlace.get('salto'):
                self.assertIn('ABC-99', enlace['url'])
        self.assertIn('actor=', pagina.context['anterior_url'])

    def test_fechas_locales_limites_y_filtros_invalidos(self):
        evento = self.evento()
        Auditoria.objects.using('central').filter(pk=evento.pk).update(
            fecha_creacion=datetime(2026, 11, 22, 2, 59, 59, tzinfo=utc.utc))
        pagina = self.raiz_web.get('/sistema/auditoria/', {'desde': '2026-11-21', 'hasta': '2026-11-21', 'search': 'Cambio de ficha'})
        self.assertEqual([e['id'] for e in pagina.context['eventos']], [evento.pk])
        for filtros in ({'desde': '2026-11-22', 'hasta': '2026-11-21'}, {'hasta': '9999-12-31'},
                        {'desde': 'incorrecta'}, {'actor': 'smartstock:-1'}, {'search': 'x' * 201}):
            pagina = self.raiz_web.get('/sistema/auditoria/', filtros)
            self.assertContains(pagina, 'Revisa los filtros')
            self.assertTrue(pagina.context['formulario_auditoria'].errors)
            self.assertEqual(self.raiz_web.get('/sistema/auditoria/exportar/', filtros).status_code, 400)

    def test_vistas_y_agrupacion_visual_conservan_todos_los_eventos(self):
        Auditoria.objects.using('central').all().delete()
        for _ in range(3):
            self.evento(accion='CONSULTA', operacion='Consulta de Empresas', resultado='solicitada')
        Auditoria.objects.using('central').update(fecha_creacion=datetime(2026, 11, 21, 16, 0, tzinfo=utc.utc))
        pagina = self.raiz_web.get('/sistema/auditoria/', {'vista': 'consultas'})
        self.assertEqual(len(pagina.context['grupos_eventos']), 1)
        self.assertEqual(len(pagina.context['grupos_eventos'][0]['eventos']), 3)
        self.assertEqual(pagina.context['pagina'].paginator.count, 3)
        self.assertContains(pagina, '>Ver detalle</a>', count=3)
        sin_grupo = self.raiz_web.get('/sistema/auditoria/', {'vista': 'consultas', 'agrupar': '0'})
        self.assertEqual(len(sin_grupo.context['grupos_eventos']), 3)
        self.evento(accion='LOGIN', modelo='Usuario')
        self.assertEqual(len(self.raiz_web.get('/sistema/auditoria/', {'vista': 'cambios'}).context['eventos']), 0)
        self.assertEqual(len(self.raiz_web.get('/sistema/auditoria/', {'vista': 'accesos'}).context['eventos']), 1)

    def test_misma_autorizacion_en_detalle_opciones_listado_y_exportacion(self):
        privado = self.evento(modelo='Usuario', empresa=None, descripcion='SECRETO CUENTA INTERNA')
        pagina = self.central.get('/sistema/auditoria/')
        self.assertNotContains(pagina, privado.descripcion)
        self.assertNotIn(self.raiz.email, ' '.join(a['etiqueta'] for a in pagina.context['actores']))
        self.assertEqual(self.central.get(f'/sistema/auditoria/{privado.pk}/').status_code, 404)
        self.assertEqual(self.central.get('/sistema/auditoria/exportar/').status_code, 403)
        self.assertEqual(self.central.get('/sistema/auditoria/reporte/').status_code, 403)

    def test_caso_reasignado_deja_de_aparecer_en_detalle_y_opciones(self):
        caso = self.caso()
        evento = self.evento(usuario=self.raiz, modelo='AtencionSoporte', objeto_id=caso.pk, atencion=caso)
        self.assertEqual(self.central.get(f'/sistema/auditoria/{evento.pk}/').status_code, 200)
        AtencionSoporte.objects.using('central').filter(pk=caso.pk).update(tecnico=self.plataforma)
        self.assertEqual(self.central.get(f'/sistema/auditoria/{evento.pk}/').status_code, 404)
        self.assertNotContains(self.central.get('/sistema/auditoria/'), evento.descripcion)

    def test_empresa_ajena_ids_coincidentes_y_revocacion_no_abren_otro_historial(self):
        acceso = self.conceder(alcances=['auditoria'])
        evento = self.evento(alias='ferreteria', usuario=self.soporte, modelo='Producto', descripcion='SOLO FRAGUA')
        self.evento(alias='repuestos', usuario=self.soporte, empresa=self.motor, modelo='Producto', descripcion='SOLO MOTOR')
        params = {'empresa': 'la-fragua', 'atencion': str(acceso.atencion_id)}
        pagina = self.central.get('/sistema/auditoria/', params)
        self.assertContains(pagina, 'SOLO FRAGUA')
        self.assertNotContains(pagina, 'SOLO MOTOR')
        self.assertEqual(self.central.get(f'/sistema/auditoria/{evento.pk}/', params).status_code, 200)
        self.assertEqual(self.central.get('/sistema/auditoria/exportar/', params).status_code, 403)
        self.assertIn(self.central.get('/sistema/auditoria/', {**params, 'empresa': 'punto-motor'}).status_code, (403, 404))
        AccesoSoporte.objects.using('central').filter(pk=acceso.pk).update(estado='revocado')
        self.assertEqual(self.central.get(f'/sistema/auditoria/{evento.pk}/', params).status_code, 403)

    def test_exportacion_completa_filtrada_csv_seguro_y_documento(self):
        Auditoria.objects.using('central').all().delete()
        for _ in range(28):
            self.evento(descripcion='=PRUEBA-FORMULA', operacion='Cambio exportable')
        self.evento(modelo='Usuario', descripcion='NO INCLUIR')
        parametros = {'modulo': 'Empresas', 'search': 'PRUEBA-FORMULA'}
        filas = self.csv(self.raiz_web.get('/sistema/auditoria/exportar/', parametros))
        self.assertEqual(len(filas), 28)
        self.assertTrue(all(f[10] == "'=PRUEBA-FORMULA" for f in filas))
        registros = Auditoria.objects.using('central').filter(accion='EXPORT').order_by('id')
        self.assertEqual(list(registros.values_list('resultado', flat=True)), ['solicitada', 'completada'])
        documento = self.raiz_web.get('/sistema/auditoria/reporte/', parametros)
        self.assertContains(documento, '28 eventos')
        self.assertNotContains(documento, 'NO INCLUIR')
        self.assertIn('no-store', documento['Cache-Control'])

    def test_empresa_exige_permiso_exportar_y_corta_si_se_revoca_antes_de_descargar(self):
        acceso = self.conceder(tecnico=self.plataforma, alcances=['auditoria', 'exportar'])
        cliente = self.cliente(self.plataforma)
        self.evento(alias='ferreteria', usuario=self.soporte, modelo='Producto', descripcion='DATO AUTORIZADO')
        parametros = {'empresa': 'la-fragua', 'atencion': str(acceso.atencion_id)}
        respuesta = cliente.get('/sistema/auditoria/exportar/', parametros)
        AccesoSoporte.objects.using('central').filter(pk=acceso.pk).update(estado='revocado')
        texto = b''.join(respuesta.streaming_content).decode('utf-8-sig')
        self.assertIn('Exportación interrumpida', texto)
        self.assertNotIn('DATO AUTORIZADO', texto)
        self.assertEqual(Auditoria.objects.using('central').filter(accion='EXPORT').latest('id').resultado, 'denegada')
        self.assertEqual(cliente.get('/sistema/auditoria/reporte/', parametros).status_code, 403)

    def test_escritura_de_ficha_guarda_cambios_y_denegaciones_no_guardan_post(self):
        ruta = '/sistema/empresas/la-fragua/editar/'
        respuesta = self.post(self.raiz_web, ruta, {'nombre': 'Nombre auditado', 'codigo': 'la-fragua', 'activa': 'on'})
        self.assertEqual(respuesta.status_code, 302)
        registro = Auditoria.objects.using('central').filter(accion='UPDATE', modelo='Empresa').latest('id')
        self.assertEqual(registro.cambios['nombre'], {'antes': self.fragua.nombre, 'despues': 'Nombre auditado'})
        self.assertEqual(registro.resultado, 'completada')
        respuesta = self.post(self.central, ruta, {'password': 'NO-REGISTRAR-CLAVE', 'access_token': 'NO-REGISTRAR-TOKEN'})
        self.assertEqual(respuesta.status_code, 403)
        registro = Auditoria.objects.using('central').latest('id')
        self.assertEqual(registro.resultado, 'denegada')
        self.assertNotIn('NO-REGISTRAR', str(registro.__dict__))

    def test_cambios_admiten_solo_campos_explicitamente_permitidos(self):
        evento = self.evento(cambios={'activo': {'antes': True, 'despues': False},
            'password': {'antes': 'secreto', 'despues': 'otro-secreto'}, 'texto': {'antes': '', 'despues': 'CORREO PRIVADO'}})
        self.assertEqual(evento.cambios, {'activo': {'antes': True, 'despues': False}})
        pagina = self.raiz_web.get(f'/sistema/auditoria/{evento.pk}/')
        self.assertContains(pagina, 'Cuenta activa')
        self.assertNotContains(pagina, 'secreto')
        self.assertEqual(self.post(self.raiz_web, f'/sistema/auditoria/{evento.pk}/', {'descripcion': 'CAMBIO'}).status_code, 405)
        evento.refresh_from_db(using='central')
        self.assertNotEqual(evento.descripcion, 'CAMBIO')

    def test_lista_25_no_hace_consultas_por_fila_ni_lee_otras_bases(self):
        for _ in range(26):
            self.evento()
        from django.db import connections
        from django.test.utils import CaptureQueriesContext
        with CaptureQueriesContext(connections['central']) as consultas, \
                CaptureQueriesContext(connections['ferreteria']) as fragua, \
                CaptureQueriesContext(connections['repuestos']) as motor:
            pagina = self.raiz_web.get('/sistema/auditoria/', {'agrupar': '0'})
        self.assertEqual(len(pagina.context['eventos']), 25)
        self.assertLessEqual(len(consultas), 10)
        self.assertEqual((len(fragua), len(motor)), (0, 0))

    def test_revocacion_entre_lotes_interrumpe_descarga_sin_exponer_siguiente_lote(self):
        acceso = self.conceder(tecnico=self.plataforma, alcances=['auditoria', 'exportar'])
        cliente = self.cliente(self.plataforma)
        for n in range(201):
            self.evento(alias='ferreteria', modelo='Producto', descripcion=f'DATO-{n:03d}')
        respuesta = cliente.get('/sistema/auditoria/exportar/', {'empresa': 'la-fragua', 'atencion': str(acceso.atencion_id)})
        partes, cantidad = [], 0
        iterador = iter(respuesta.streaming_content)
        for parte in iterador:
            partes.append(parte)
            if b'DATO-' in parte:
                cantidad += 1
            if cantidad == 200:
                break
        self.assertEqual(cantidad, 200)
        AccesoSoporte.objects.using('central').filter(pk=acceso.pk).update(estado='revocado')
        resto = b''.join(iterador).decode()
        self.assertIn('Exportación interrumpida', resto)
        self.assertNotIn('DATO-000', resto)
        self.assertNotIn(b'DATO-000', b''.join(partes))


class MigracionAuditoriaTests(TransactionTestCase):
    databases = {'central', 'ferreteria', 'repuestos'}

    def test_migracion_conserva_eventos_en_las_tres_bases_sin_inventar_metadatos(self):
        for alias in ('central', 'ferreteria', 'repuestos'):
            conexion = connections[alias]
            ejecutor = MigrationExecutor(conexion)
            destinos = ejecutor.loader.graph.leaf_nodes()
            anterior = [('core', '0005_consultas_empresa')]
            try:
                ejecutor.migrate(anterior)
                modelo = MigrationExecutor(conexion).loader.project_state(anterior).apps.get_model('core', 'Auditoria')
                registro = modelo.objects.using(alias).create(accion='UPDATE', modelo='Usuario',
                    objeto_id='42', descripcion='Descripción original · áéíóú', ip_address='192.0.2.8', user_agent='Navegador histórico')
                fecha = registro.fecha_creacion
                MigrationExecutor(conexion).migrate(destinos)
                migrado = Auditoria.objects.using(alias).get(pk=registro.pk)
                self.assertEqual((migrado.descripcion, migrado.objeto_id, migrado.fecha_creacion),
                                 ('Descripción original · áéíóú', '42', fecha))
                self.assertEqual((migrado.actor, migrado.resultado, migrado.cambios), ({}, '', {}))
                self.assertEqual((migrado.ip_address, migrado.user_agent), ('192.0.2.8', 'Navegador histórico'))
            finally:
                MigrationExecutor(conexion).migrate(destinos)
