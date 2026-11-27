from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.db import connection, connections
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import Auditoria
from apps.usuarios.models import Usuario
from .models import (Bodega, DetalleLote, ExistenciaLote, Lote, Merma, Movimiento,
                     Producto, StockBodega, Transferencia)

ROOT = '/api/v1/productos/'


class LotesFIFOTests(TestCase):
    def setUp(self):
        self.usuario = Usuario.objects.create_superuser(email='fifo@example.invalid', password='prueba-fifo')
        self.client = APIClient()
        self.client.force_authenticate(self.usuario)
        self.producto = Producto.objects.create(sku='FIFO-001', nombre='Tornillos', precio_referencia=999)
        self.bodega = Bodega.objects.create(nombre='Bodega Central', direccion='Prueba')
        self.destino = Bodega.objects.create(nombre='Destino', direccion='Otra')

    def movimiento(self, tipo='ENTRADA', cantidad=10, **datos):
        return self.client.post(ROOT + 'registrar-movimiento/', {
            'producto_id': self.producto.pk, 'bodega_id': self.bodega.pk,
            'tipo_movimiento': tipo, 'cantidad': cantidad, **datos,
        }, format='json')

    def entrada(self, cantidad=10, costo='100.00', **datos):
        respuesta = self.movimiento(cantidad=cantidad, costo_unitario=costo, **datos)
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        return Lote.objects.get(pk=respuesta.data['data']['lotes'][0]['lote_id'])

    def stock(self, bodega=None):
        return StockBodega.objects.get(producto=self.producto, bodega=bodega or self.bodega).cantidad_total

    def comprobar_saldos(self):
        for stock in StockBodega.objects.all():
            cantidades = ExistenciaLote.objects.filter(lote__producto=stock.producto, bodega=stock.bodega).values_list('cantidad', flat=True)
            self.assertEqual(stock.cantidad_total, sum(cantidades))

    def test_salida_agota_primero_el_lote_antiguo_y_conserva_los_costos(self):
        antiguo = self.entrada(5, '10.25', referencia_lote='Recepción A')
        nuevo = self.entrada(8, '20.50', referencia_lote='Recepción B')
        self.producto.precio_referencia = 800
        self.producto.save()
        respuesta = self.movimiento('SALIDA', 7)
        self.assertEqual(respuesta.status_code, 201, respuesta.data)
        asignaciones = respuesta.data['data']['lotes']
        self.assertEqual([(a['lote_id'], a['cantidad']) for a in asignaciones], [(antiguo.pk, 5), (nuevo.pk, 2)])
        self.assertEqual([Decimal(a['costo_total']) for a in asignaciones], [Decimal('51.25'), Decimal('41.00')])
        self.assertEqual(self.stock(), 6)
        self.comprobar_saldos()

    def test_orden_fifo_es_fecha_de_recepcion_y_desempata_por_identificador(self):
        primero = self.entrada(2)
        segundo = self.entrada(3)
        fecha = timezone.now() - timedelta(days=2)
        Lote.objects.filter(pk=segundo.pk).update(fecha_recepcion=fecha)
        r = self.movimiento('SALIDA', 1)
        self.assertEqual(r.data['data']['lotes'][0]['lote_id'], segundo.pk)
        Lote.objects.filter(pk__in=(primero.pk, segundo.pk)).update(fecha_recepcion=fecha)
        r = self.movimiento('SALIDA', 1)
        self.assertEqual(r.data['data']['lotes'][0]['lote_id'], primero.pk)

    def test_costos_omitidos_y_cero_se_distinguen_y_los_invalidos_se_rechazan(self):
        sin_costo = self.entrada(costo=None)
        gratis = self.entrada(costo='0')
        self.assertIsNone(sin_costo.costo_unitario)
        self.assertEqual(gratis.costo_unitario, 0)
        for valor in ('-1', '99999999999.00', '1.001', 'NaN', 'Infinity'):
            with self.subTest(valor=valor):
                r = self.movimiento(costo_unitario=valor)
                self.assertEqual(r.status_code, 400, r.data)
        self.assertEqual(Lote.objects.count(), 2)
        self.assertEqual(self.movimiento('SALIDA', 1, costo_unitario=20).status_code, 400)

    def test_saldo_preexistente_se_incorpora_con_costo_desconocido_y_sale_primero(self):
        StockBodega.objects.create(producto=self.producto, bodega=self.bodega, cantidad_total=4)
        self.entrada(3, '500')
        previo = Lote.objects.get(es_saldo_inicial=True)
        self.assertEqual(previo.cantidad_inicial, 4)
        self.assertIsNone(previo.costo_unitario)
        r = self.movimiento('SALIDA', 5)
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['data']['lotes'][0]['lote_id'], previo.pk)
        self.assertIsNone(r.data['data']['lotes'][0]['fecha_recepcion'])
        self.assertIsNone(r.data['data']['lotes'][0]['costo_total'])
        self.comprobar_saldos()

    def test_transferencia_conserva_lotes_costo_antiguedad_y_reintento(self):
        antiguo = self.entrada(5, '10')
        self.entrada(5, '20')
        fecha = antiguo.fecha_recepcion
        datos = {'bodega_origen_id': self.bodega.pk, 'bodega_destino_id': self.destino.pk,
                 'producto_id': self.producto.pk, 'cantidad': 7, 'solicitud_id': str(uuid4())}
        r = self.client.post(ROOT + 'transferencias/', datos, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual([a['cantidad'] for a in r.data['data']['lotes']], [5, 2])
        self.assertEqual(self.client.post(ROOT + 'transferencias/', datos, format='json').status_code, 200)
        self.assertEqual(Transferencia.objects.count(), 1)
        antiguo.refresh_from_db()
        self.assertEqual(antiguo.fecha_recepcion, fecha)
        self.assertEqual(self.stock(self.destino), 7)
        r = self.movimiento('SALIDA', 6, bodega_id=self.destino.pk)
        self.assertEqual([a['cantidad'] for a in r.data['data']['lotes']], [5, 1])
        self.assertEqual(Lote.objects.count(), 2)
        self.comprobar_saldos()

    def test_transferir_lote_antiguo_a_bodega_con_recepcion_nueva_conserva_prioridad(self):
        antiguo = self.entrada(5, '10')
        self.entrada(5, '20', bodega_id=self.destino.pk)
        r = self.client.post(ROOT + 'transferencias/', {'bodega_origen_id': self.bodega.pk,
            'bodega_destino_id': self.destino.pk, 'producto_id': self.producto.pk,
            'cantidad': 3, 'solicitud_id': str(uuid4())}, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        r = self.movimiento('SALIDA', 2, bodega_id=self.destino.pk)
        self.assertEqual(r.data['data']['lotes'][0]['lote_id'], antiguo.pk)
        self.comprobar_saldos()

    def test_merma_usa_fifo_o_un_lote_especifico_con_existencias(self):
        antiguo = self.entrada(4)
        nuevo = self.entrada(6)
        datos = {'producto_id': self.producto.pk, 'bodega_id': self.bodega.pk,
                 'cantidad': 2, 'motivo': 'DAÑO', 'observacion': 'Daño del lote nuevo', 'lote_id': nuevo.pk}
        r = self.client.post(ROOT + 'mermas/', datos, format='json')
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(r.data['data']['lotes'][0]['lote_id'], nuevo.pk)
        datos.pop('lote_id')
        r = self.client.post(ROOT + 'mermas/', datos, format='json')
        self.assertEqual(r.data['data']['lotes'][0]['lote_id'], antiguo.pk)
        datos.update(lote_id=antiguo.pk, cantidad=3)
        r = self.client.post(ROOT + 'mermas/', datos, format='json')
        self.assertEqual(r.status_code, 409)
        self.assertEqual(Merma.objects.count(), 2)
        self.assertEqual(self.stock(), 6)
        self.comprobar_saldos()

    def test_rechaza_lote_de_otro_producto_o_bodega_y_revierte_el_desglose(self):
        self.entrada(4)
        ajeno = self.entrada(6, bodega_id=self.destino.pk)
        r = self.client.post(ROOT + 'mermas/', {'producto_id': self.producto.pk,
            'bodega_id': self.bodega.pk, 'cantidad': 1, 'motivo': 'DAÑO',
            'observacion': 'Prueba', 'lote_id': ajeno.pk}, format='json')
        self.assertEqual(r.status_code, 409, r.data)
        self.assertEqual(Merma.objects.count(), 0)
        self.assertEqual(self.stock(), 4)
        self.comprobar_saldos()

    def test_reintento_no_duplica_entrada_salida_auditoria_ni_modifica_el_saldo_confirmado(self):
        clave = str(uuid4())
        self.entrada(7, solicitud_id=clave)
        r = self.movimiento(cantidad=7, costo_unitario='100', solicitud_id=clave)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Lote.objects.count(), 1)
        clave_salida = str(uuid4())
        self.assertEqual(self.movimiento('SALIDA', 2, solicitud_id=clave_salida).status_code, 201)
        self.movimiento('SALIDA', 1)
        r = self.movimiento('SALIDA', 2, solicitud_id=clave_salida)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['data']['stock_restante'], 5)
        self.assertEqual(self.stock(), 4)
        self.assertEqual(self.movimiento('SALIDA', 3, solicitud_id=clave_salida).status_code, 409)
        self.assertEqual(Movimiento.objects.count(), 3)
        self.assertEqual(Auditoria.objects.filter(modelo='Movimiento').count(), 3)
        self.comprobar_saldos()

    def test_fallo_de_auditoria_revierte_stock_lotes_y_la_clave_para_reintentar(self):
        lote = self.entrada(5)
        clave = str(uuid4())
        with patch('apps.productos.views_movimientos.registrar_auditoria', side_effect=RuntimeError('prueba')):
            with self.assertRaises(RuntimeError):
                self.movimiento('SALIDA', 3, solicitud_id=clave)
        self.assertEqual(self.stock(), 5)
        self.assertEqual(ExistenciaLote.objects.get(lote=lote).cantidad, 5)
        self.assertEqual(DetalleLote.objects.count(), 1)
        self.assertEqual(self.movimiento('SALIDA', 3, solicitud_id=clave).status_code, 201)
        self.comprobar_saldos()

    def test_desajuste_de_lotes_bloquea_toda_la_operacion(self):
        lote = self.entrada(5)
        ExistenciaLote.objects.filter(lote=lote).update(cantidad=4)
        self.assertEqual(self.movimiento('SALIDA', 2).status_code, 409)
        self.assertEqual(self.stock(), 5)
        self.assertEqual(Movimiento.objects.count(), 1)

    def test_lotes_se_consultan_paginados_con_sus_permisos_y_estados(self):
        for _ in range(26):
            self.entrada(1)
        self.movimiento('SALIDA', 1)
        url = ROOT + str(self.producto.pk) + '/lotes/'
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['count'], 25)
        r = self.client.get(url, {'incluir_agotados': True, 'page': 2})
        self.assertEqual(r.data['count'], 26)
        self.assertEqual(len(r.data['results']), 1)
        self.assertEqual(self.client.patch(url, {'costo_unitario': 7}).status_code, 405)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(url).status_code, 401)


class MigracionLotesTests(TransactionTestCase):
    def test_saldo_inicial_preserva_stock_y_no_inventa_costos_o_historial(self):
        anterior = [('productos', '0007_integridad_stock')]
        destino = [('productos', '0008_lotes_fifo')]
        executor = MigrationExecutor(connection)
        executor.migrate(anterior)
        try:
            apps = executor.loader.project_state(anterior).apps
            producto = apps.get_model('productos', 'Producto').objects.create(sku='ANTERIOR', nombre='Anterior')
            bodega = apps.get_model('productos', 'Bodega').objects.create(nombre='Anterior', direccion='Prueba')
            apps.get_model('productos', 'StockBodega').objects.create(producto=producto, bodega=bodega, cantidad_total=9)
            executor = MigrationExecutor(connection)
            executor.migrate(destino)
            self.assertEqual(StockBodega.objects.get(producto_id=producto.pk).cantidad_total, 9)
            lote = Lote.objects.get(producto_id=producto.pk)
            self.assertTrue(lote.es_saldo_inicial)
            self.assertIsNone(lote.costo_unitario)
            self.assertEqual(ExistenciaLote.objects.get(lote=lote).cantidad, 9)
            self.assertFalse(DetalleLote.objects.exists())
        finally:
            MigrationExecutor(connection).migrate(destino)


@skipUnless(connection.vendor == 'postgresql', 'Requiere bloqueos reales de PostgreSQL')
class ConcurrenciaFIFOTests(TransactionTestCase):
    def ejecutar_salidas(self, repetir_solicitud):
        usuario = Usuario.objects.create_superuser(email='concurrencia@example.invalid', password='prueba')
        producto = Producto.objects.create(sku='CONCURRENTE', nombre='Prueba')
        bodega = Bodega.objects.create(nombre='Bodega Central', direccion='Prueba')
        client = APIClient()
        client.force_authenticate(usuario)
        datos = {'producto_id': producto.pk, 'bodega_id': bodega.pk, 'tipo_movimiento': 'ENTRADA', 'cantidad': 5}
        for _ in range(2):
            self.assertEqual(client.post(ROOT + 'registrar-movimiento/', datos, format='json').status_code, 201)
        barrera = Barrier(2)
        clave = str(uuid4()) if repetir_solicitud else None

        def salida():
            try:
                cliente = APIClient()
                cliente.force_authenticate(Usuario.objects.get(pk=usuario.pk))
                barrera.wait(timeout=10)
                envio = {**datos, 'tipo_movimiento': 'SALIDA', 'cantidad': 8}
                if clave:
                    envio['solicitud_id'] = clave
                return cliente.post(ROOT + 'registrar-movimiento/', envio, format='json').status_code
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as ejecutor:
            resultados = list(ejecutor.map(lambda _: salida(), range(2)))
        self.assertEqual(sorted(resultados), [200, 201] if repetir_solicitud else [201, 409])
        self.assertEqual(StockBodega.objects.get(producto=producto).cantidad_total, 2)
        self.assertEqual(sum(ExistenciaLote.objects.values_list('cantidad', flat=True)), 2)

    def test_dos_salidas_no_consumen_las_mismas_unidades(self):
        self.ejecutar_salidas(repetir_solicitud=False)

    def test_la_misma_confirmacion_simultanea_devuelve_el_movimiento_ya_creado(self):
        self.ejecutar_salidas(repetir_solicitud=True)
