"""Auditoría investigable, historia fiel y autorización idéntica en cada salida."""
import csv
from datetime import datetime, timezone as utc
from io import StringIO
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, StreamingHttpResponse
from django.template.response import TemplateResponse
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.db import DatabaseError, connections
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from apps.core.models import Auditoria
from apps.core.registro_auditoria import crear_evento
from apps.usuarios.models import Rol, Usuario
from . import pruebas_soporte as soporte
from .models import AccesoSoporte, AtencionSoporte
from .permisos import registrar_empresa_consultada, requiere_personal


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
        for microsegundos in (100, 500, 900):
            evento = self.evento(accion='CONSULTA', operacion='Consulta de Empresas', resultado='solicitada')
            Auditoria.objects.using('central').filter(pk=evento.pk).update(
                fecha_creacion=datetime(2026, 11, 21, 16, 0, microsecond=microsegundos, tzinfo=utc.utc))
        pagina = self.raiz_web.get('/sistema/auditoria/', {'vista': 'consultas'})
        self.assertEqual(len(pagina.context['grupos_eventos']), 1)
        self.assertEqual(len(pagina.context['grupos_eventos'][0]['eventos']), 3)
        self.assertEqual(pagina.context['grupos_eventos'][0]['intervalo'], '21/11/2026 · 13:00:00')
        self.assertEqual([f.microsecond for f in Auditoria.objects.using('central').order_by('id').values_list('fecha_creacion', flat=True)],
                         [100, 500, 900])
        self.assertEqual(pagina.context['pagina'].paginator.count, 3)
        self.assertContains(pagina, '>Ver detalle</a>', count=3)
        sin_grupo = self.raiz_web.get('/sistema/auditoria/', {'vista': 'consultas', 'agrupar': '0'})
        self.assertEqual(len(sin_grupo.context['grupos_eventos']), 3)
        self.evento(accion='LOGIN', modelo='Usuario')
        self.assertEqual(len(self.raiz_web.get('/sistema/auditoria/', {'vista': 'cambios'}).context['eventos']), 0)
        self.assertEqual(len(self.raiz_web.get('/sistema/auditoria/', {'vista': 'accesos'}).context['eventos']), 1)

    def test_grupo_identifica_cuenta_empresas_y_periodo_sin_mezclar_perfiles(self):
        Auditoria.objects.using('central').all().delete()
        filas = [self.evento(accion='CONSULTA', operacion='Consulta de Empresas', resultado='completada',
                            empresa=empresa) for empresa in (self.fragua, self.motor, self.fragua)]
        for segundo, fila in enumerate(filas):
            Auditoria.objects.using('central').filter(pk=fila.pk).update(
                fecha_creacion=datetime(2026, 11, 21, 16, 1 + segundo, tzinfo=utc.utc))
        pagina = self.raiz_web.get('/sistema/auditoria/', {'vista': 'consultas'})
        grupo = pagina.context['grupos_eventos'][0]
        self.assertEqual(grupo['cantidad_empresas'], 2)
        self.assertEqual(grupo['intervalo'], '21/11/2026 · 13:01:00–13:03:00')
        self.assertContains(pagina, '3 consultas · 2 empresas · Empresas')
        self.assertContains(pagina, self.raiz.email)
        self.assertContains(pagina, 'Superusuario técnico')
        # El nombre compartido no identifica la cuenta. El perfil es el del evento.
        self.soporte.nombres = self.raiz.nombres
        otro = self.evento(usuario=self.soporte, accion='CONSULTA', operacion='Consulta de Empresas', resultado='completada')
        Auditoria.objects.using('central').filter(pk=otro.pk).update(
            fecha_creacion=datetime(2026, 11, 21, 16, 3, 30, tzinfo=utc.utc))
        actor = dict(filas[2].actor, perfil='Administrador de plataforma')
        Auditoria.objects.using('central').filter(pk=filas[2].pk).update(actor=actor)
        pagina = self.raiz_web.get('/sistema/auditoria/', {'vista': 'consultas'})
        self.assertEqual([len(g['eventos']) for g in pagina.context['grupos_eventos']], [1, 1, 2])
        self.assertEqual(pagina.context['pagina'].paginator.count, 4)

    def test_etiqueta_smartstock_solo_en_eventos_internos_y_conserva_historicos_en_cada_salida(self):
        texto = 'QA-EMPRESA-MOSTRADA'
        interno = self.evento(modelo='Usuario', empresa=None, accion='LOGIN', descripcion=texto)
        historico = Auditoria.objects.using('central').create(
            usuario=self.raiz, modelo='Usuario', accion='UPDATE', descripcion=texto)
        consulta = self.evento(modelo='Empresa', empresa=None, accion='CONSULTA', objeto_id='999999', descripcion=texto)
        denegado = self.evento(modelo='Acceso', empresa=None, accion='ACCESS_DENIED', descripcion=texto)
        cliente = Usuario.objects.using('ferreteria').select_related('rol').get(pk=90)
        ajeno = self.evento(usuario=cliente, modelo='Usuario', empresa=None, descripcion=texto)
        relacionado = self.evento(modelo='Usuario', descripcion=texto)
        registros = [interno, historico, consulta, denegado, ajeno, relacionado]
        antes = list(Auditoria.objects.using('central').filter(pk__in=[r.pk for r in registros]).order_by('id').values())
        esperados = {interno.pk: 'SmartStock', historico.pk: 'No registrada', consulta.pk: 'No registrada',
                     denegado.pk: 'No registrada', ajeno.pk: 'No registrada', relacionado.pk: self.fragua.nombre}
        pagina = self.raiz_web.get('/sistema/auditoria/', {'search': texto, 'agrupar': '0'})
        self.assertEqual({e['id']: e['empresa_mostrada'] for e in pagina.context['eventos']}, esperados)
        for registro in (interno, historico):
            detalle = self.raiz_web.get(f'/sistema/auditoria/{registro.pk}/')
            self.assertContains(detalle, f'<dt>Empresa relacionada</dt><dd>{esperados[registro.pk]}</dd>', html=True)
        filas = self.csv(self.raiz_web.get('/sistema/auditoria/exportar/', {'search': texto}))
        self.assertEqual({int(f[0]): f[6] for f in filas}, esperados)
        documento = self.raiz_web.get('/sistema/auditoria/reporte/', {'search': texto})
        self.assertContains(documento, '<br>Superusuario técnico<br>SmartStock</td>')
        self.assertContains(documento, '<br><br>No registrada</td>')
        despues = list(Auditoria.objects.using('central').filter(pk__in=esperados).order_by('id').values())
        self.assertEqual(despues, antes)

    def test_etiqueta_empresa_usa_el_ambito_autorizado_y_no_el_origen_del_actor(self):
        acceso = self.conceder(tecnico=self.raiz, alcances=['auditoria'])
        evento = self.evento(alias='ferreteria', usuario=self.raiz, empresa=None, modelo='Usuario', descripcion='QA-AMBITO')
        parametros = {'empresa': 'la-fragua', 'atencion': str(acceso.atencion_id), 'search': 'QA-AMBITO'}
        pagina = self.raiz_web.get('/sistema/auditoria/', parametros)
        self.assertEqual(pagina.context['eventos'][0]['empresa_mostrada'], self.fragua.nombre)
        detalle = self.raiz_web.get(f'/sistema/auditoria/{evento.pk}/', parametros)
        self.assertEqual(detalle.context['evento']['empresa_mostrada'], self.fragua.nombre)
        evento.refresh_from_db(using='ferreteria')
        self.assertEqual(evento.empresa_nombre, '')

    def test_solicitud_antigua_se_aclara_sin_reescribir_y_conserva_descripcion_en_salidas(self):
        texto = 'SmartStock · raiz@example.invalid · Solicitud de consulta de Empresas · TEXTO ORIGINAL LARGO ' + 'histórico ' * 30
        evento = self.evento(accion='CONSULTA', resultado='solicitada', descripcion=texto)
        antes = Auditoria.objects.using('central').filter(pk=evento.pk).values().get()
        pagina = self.raiz_web.get('/sistema/auditoria/', {'search': 'TEXTO ORIGINAL LARGO'})
        fila = pagina.context['eventos'][0]
        self.assertEqual(fila['resultado_etiqueta'], 'Solicitud registrada')
        self.assertEqual(fila['resumen'], 'Solicitud registrada; resultado sin confirmar.')
        self.assertNotContains(pagina, 'Solicitud de consulta de Empresas · TEXTO ORIGINAL LARGO')
        detalle = self.raiz_web.get(f'/sistema/auditoria/{evento.pk}/')
        self.assertContains(detalle, 'Este evento no acredita una operación completada.')
        self.assertContains(detalle, texto)
        parametros = {'search': 'TEXTO ORIGINAL LARGO', 'resultado': 'solicitada'}
        filas = self.csv(self.raiz_web.get('/sistema/auditoria/exportar/', parametros))
        self.assertEqual((filas[0][9], filas[0][10]), ('Solicitud registrada', texto))
        self.assertContains(self.raiz_web.get('/sistema/auditoria/reporte/', parametros), texto)
        self.assertEqual(Auditoria.objects.using('central').filter(pk=evento.pk).values().get(), antes)

    def test_filtros_avanzados_se_abren_con_filtros_activos_y_conservan_contexto(self):
        self.evento()
        pagina = self.raiz_web.get('/sistema/auditoria/')
        self.assertContains(pagina, '<details class="ss-aud-avanzados">')
        parametros = {'accion': 'UPDATE', 'resultado': 'completada', 'vista': 'cambios',
                      'usuario': str(self.raiz.pk), 'modelo': 'Empresa', 'agrupar': '0'}
        pagina = self.raiz_web.get('/sistema/auditoria/', parametros)
        self.assertContains(pagina, '<details class="ss-aud-avanzados" open>')
        self.assertEqual(pagina.context['filtros_avanzados_activos'], 4)
        self.assertContains(pagina, f'name="usuario" value="{self.raiz.pk}"')
        self.assertContains(pagina, 'name="modelo" value="Empresa"')
        for enlace in [pagina.context['exportar_url'], pagina.context['imprimir_url'],
                       pagina.context['periodos'][0]['url'], pagina.context['eventos'][0]['detalle_url']]:
            self.assertIn('resultado=completada', enlace)
            self.assertIn('accion=UPDATE', enlace)
        self.assertEqual(pagina.context['limpiar_url'], '/sistema/auditoria/')

    def test_lecturas_confirmadas_registran_completada_tras_preparar_los_datos(self):
        acceso = self.conceder(tecnico=self.raiz, alcances=['catalogo', 'inventario', 'usuarios', 'auditoria'])
        parametros = {'empresa': 'la-fragua', 'atencion': str(acceso.atencion_id)}
        for ruta in ('catalogo', 'inventario', 'usuarios', 'auditoria'):
            with self.subTest(ruta=ruta):
                respuesta = self.raiz_web.get(f'/sistema/{ruta}/', parametros)
                self.assertEqual(respuesta.status_code, 200)
                evento = Auditoria.objects.using('central').filter(accion='CONSULTA').latest('id')
                self.assertEqual(evento.resultado, 'completada')
                self.assertEqual(evento.empresa_codigo, 'la-fragua')
                self.assertEqual(evento.atencion_id, acceso.atencion_id)

    def test_error_de_lectura_con_html_200_no_se_registra_como_completada(self):
        acceso = self.conceder(tecnico=self.raiz, alcances=['catalogo', 'inventario', 'usuarios', 'auditoria'])
        parametros = {'empresa': 'la-fragua', 'atencion': str(acceso.atencion_id)}
        fallos = [('catalogo', 'esquema_multiempresa.consultas_sistema.tabla_catalogo'),
                  ('inventario', 'esquema_multiempresa.consultas_sistema.datos_resumen_dashboard'),
                  ('usuarios', 'esquema_multiempresa.sistema.paginar'),
                  ('auditoria', 'esquema_multiempresa.auditoria_sistema.opciones')]
        for ruta, funcion in fallos:
            with self.subTest(ruta=ruta), patch(funcion, side_effect=DatabaseError('NO-REGISTRAR-ERROR-INTERNO')):
                respuesta = self.raiz_web.get(f'/sistema/{ruta}/', parametros)
                self.assertContains(respuesta, 'No pudimos consultar')
                evento = Auditoria.objects.using('central').filter(accion='CONSULTA').latest('id')
                self.assertEqual(evento.resultado, 'fallida')
                self.assertNotIn('NO-REGISTRAR', evento.descripcion)

    def test_resumen_con_fallo_parcial_distingue_el_resultado_de_cada_empresa(self):
        from apps.core.empresa import empresa_actual
        original = Usuario.objects.aggregate

        def consultar(*args, **kwargs):
            if empresa_actual().codigo == 'punto-motor':
                raise DatabaseError('Fallo simulado')
            return original(*args, **kwargs)

        ultimo = Auditoria.objects.using('central').latest('id').pk
        with patch('esquema_multiempresa.sistema.Usuario.objects.aggregate', side_effect=consultar):
            self.assertEqual(self.raiz_web.get('/sistema/').status_code, 200)
        eventos = Auditoria.objects.using('central').filter(accion='CONSULTA', pk__gt=ultimo)
        self.assertEqual(dict(eventos.values_list('empresa_codigo', 'resultado')),
                         {'la-fragua': 'completada', 'punto-motor': 'fallida'})

    def test_filtro_invalido_o_fallo_al_renderizar_no_acreditan_lectura_completada(self):
        acceso = self.conceder(tecnico=self.raiz, alcances=['auditoria', 'catalogo'])
        parametros = {'empresa': 'la-fragua', 'atencion': str(acceso.atencion_id)}
        self.assertContains(self.raiz_web.get('/sistema/auditoria/', {**parametros, 'desde': 'invalida'}), 'Revisa los filtros')
        self.assertEqual(Auditoria.objects.using('central').filter(accion='CONSULTA').latest('id').resultado, 'fallida')
        with patch('esquema_multiempresa.consultas_sistema.render', side_effect=RuntimeError('Fallo al renderizar')):
            with self.assertRaises(RuntimeError):
                self.raiz_web.get('/sistema/catalogo/', parametros)
        self.assertEqual(Auditoria.objects.using('central').filter(accion='CONSULTA').latest('id').resultado, 'fallida')

    def test_respuesta_sin_confirmacion_flujo_o_redireccion_no_acreditan_finalizacion(self):
        respuestas = [HttpResponse(), HttpResponse(status=302), StreamingHttpResponse(iter([b'datos'])),
                      TemplateResponse(None, 'sistema/auditoria.html', {})]
        for indice, respuesta in enumerate(respuestas):
            with self.subTest(indice=indice):
                request = RequestFactory().get('/sistema/consulta/')
                request.user = self.raiz

                @requiere_personal
                def vista(request):
                    registrar_empresa_consultada(request, self.fragua, 'completada' if indice else None)
                    return respuesta

                vista(request)
                self.assertEqual(Auditoria.objects.using('central').filter(accion='CONSULTA').latest('id').resultado, 'solicitada')

    def test_denegacion_despues_de_contexto_preparado_no_acredita_consulta_completada(self):
        request = RequestFactory().get('/sistema/consulta/')
        request.user = self.raiz

        @requiere_personal
        def vista(request):
            registrar_empresa_consultada(request, self.fragua, 'completada')
            raise PermissionDenied

        with self.assertRaises(PermissionDenied):
            vista(request)
        self.assertEqual(Auditoria.objects.using('central').filter(accion='CONSULTA').latest('id').resultado, 'denegada')

    def test_reporte_solo_confirma_preparacion_despues_de_generar_el_archivo(self):
        acceso = self.conceder(tecnico=self.raiz, alcances=['reportes', 'exportar'])
        parametros = {'empresa': 'la-fragua', 'atencion': str(acceso.atencion_id), 'exportar': 'pdf'}
        self.assertEqual(self.raiz_web.get('/sistema/reportes/', parametros).status_code, 200)
        preparado = Auditoria.objects.using('central').filter(modelo='AtencionSoporte', accion='CONSULTA').latest('id')
        self.assertEqual((preparado.operacion, preparado.resultado), ('Archivo de reporte PDF preparado', 'completada'))
        for formato, funcion in (('csv', 'archivo_reporte'), ('pdf', 'documento_reporte')):
            with self.subTest(formato=formato), patch('esquema_multiempresa.consultas_sistema.' + funcion,
                                                       side_effect=DatabaseError('Fallo de generación')):
                respuesta = self.raiz_web.get('/sistema/reportes/', {**parametros, 'exportar': formato})
                self.assertContains(respuesta, 'No pudimos consultar')
                self.assertEqual(Auditoria.objects.using('central').filter(accion='CONSULTA').latest('id').resultado, 'fallida')
                self.assertEqual(Auditoria.objects.using('central').filter(modelo='AtencionSoporte', accion='CONSULTA').latest('id').pk,
                                 preparado.pk)

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

    def test_desactivar_y_reactivar_empresa_tienen_accion_y_titulo_concretos(self):
        ruta = '/sistema/empresas/la-fragua/editar/'
        datos = {'nombre': self.fragua.nombre, 'codigo': self.fragua.codigo,
                 'contacto_email': self.fragua.contacto_email}
        for activa, accion, titulo in ((False, 'DEACTIVATE', 'Empresa desactivada'),
                                       (True, 'REACTIVATE', 'Empresa reactivada')):
            respuesta = self.post(self.raiz_web, ruta, {**datos, **({'activa': 'on'} if activa else {})})
            self.assertEqual(respuesta.status_code, 302)
            evento = Auditoria.objects.using('central').filter(modelo='Empresa', accion=accion).latest('id')
            self.assertEqual(evento.operacion, titulo)
            self.assertEqual(evento.cambios['activa'], {'antes': not activa, 'despues': activa})
            self.assertContains(self.raiz_web.get(f'/sistema/auditoria/{evento.pk}/'), titulo)

    def test_cambiar_perfil_del_equipo_identifica_el_cambio_y_conserva_ambos_valores(self):
        respuesta = self.post(self.raiz_web, f'/sistema/cuentas/{self.soporte.pk}/', {
            'nombres': self.soporte.nombres, 'apellidos': 'De prueba', 'email': self.soporte.email,
            'activo': 'on', 'perfil': 'administrador_plataforma'})
        self.assertEqual(respuesta.status_code, 302)
        evento = Auditoria.objects.using('central').filter(modelo='Usuario', objeto_id=str(self.soporte.pk)).latest('id')
        self.assertEqual(evento.operacion, 'Perfil de acceso cambiado')
        self.assertEqual(evento.cambios['perfil'], {'antes': 'Soporte técnico', 'despues': 'Administrador de plataforma'})
        self.assertEqual(evento.resultado, 'completada')

    def test_cambiar_rol_de_empresa_identifica_el_cambio_sin_cruzar_identidades(self):
        acceso = self.conceder(tecnico=self.plataforma, alcances=['usuarios', 'gestionar_usuarios'])
        cliente = self.cliente(self.plataforma)
        rol = Rol.objects.using('ferreteria').get(codigo='encargado_bodega')
        respuesta = self.post(cliente, f'/sistema/empresas/la-fragua/usuarios/91/?atencion={acceso.atencion_id}', {
            'nombres': 'Operador', 'apellidos': 'De prueba', 'activo': 'on', 'rol': str(rol.pk)})
        self.assertEqual(respuesta.status_code, 302)
        evento = Auditoria.objects.using('ferreteria').filter(modelo='Usuario', objeto_id='91').latest('id')
        self.assertEqual(evento.operacion, 'Rol de usuario cambiado')
        self.assertEqual(evento.cambios['perfil'], {'antes': 'Operador', 'despues': rol.nombre})
        self.assertEqual(evento.actor['email'], self.plataforma.email)
        self.assertIsNone(evento.usuario_id)
        self.assertFalse(Auditoria.objects.using('repuestos').filter(objeto_id='91').exists())

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
