"""Investigación de eventos con el mismo alcance en listado, detalle y exportación."""
import csv
from copy import copy
from datetime import datetime, time, timedelta
from itertools import groupby
from urllib.parse import urlencode
from uuid import uuid4

from django import forms
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.db.models import Case, CharField, F, Q, Value, When
from django.db.models.functions import Cast
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import Truncator
from django.views.decorators.http import require_GET

from apps.core.models import Auditoria
from apps.core.registro_auditoria import ETIQUETAS, MODULOS, cambios_seguros, crear_evento
from apps.core.views_auditoria import ACCIONES, SalidaCSV, celda_csv, consulta_base, datos_evento, fijar_reporte
from apps.usuarios.models import Usuario
from .autorizacion_soporte import acceso_para, atenciones_visibles, empresa_para_consulta, parametros_atencion
from .permisos import es_administrador_plataforma, es_personal_smartstock, es_superusuario_smartstock, registrar_empresa_consultada, requiere_personal


VISTAS = [('todos', 'Todos'), ('cambios', 'Cambios'), ('accesos', 'Accesos'), ('consultas', 'Consultas')]
RESULTADOS = dict(Auditoria._meta.get_field('resultado').choices)
RESULTADOS['solicitada'] = 'Solicitud registrada'
CAMPOS_URL = ('empresa', 'atencion', 'search', 'usuario', 'actor', 'accion', 'modulo', 'modelo', 'resultado',
              'desde', 'hasta', 'vista', 'agrupar', 'page')


class Filtros(forms.Form):
    search = forms.CharField(required=False, max_length=200)
    usuario = forms.RegexField(r'^(sin_usuario|[1-9][0-9]{0,18})$', required=False)
    actor = forms.RegexField(r'^(sin_identidad|(smartstock|empresa):[1-9][0-9]{0,18})$', required=False)
    accion = forms.CharField(required=False, max_length=20)
    modelo = forms.CharField(required=False, max_length=100)
    modulo = forms.CharField(required=False, max_length=100)
    resultado = forms.ChoiceField(required=False, choices=[('', 'Todos'), ('sin_registro', 'No registrado'), *RESULTADOS.items()])
    desde = forms.DateField(required=False, input_formats=['%Y-%m-%d'])
    hasta = forms.DateField(required=False, input_formats=['%Y-%m-%d'])
    vista = forms.ChoiceField(required=False, choices=VISTAS)
    agrupar = forms.ChoiceField(required=False, choices=[('0', 'No'), ('1', 'Sí')])

    def clean(self):
        datos = super().clean()
        if datos.get('desde') and datos.get('hasta') and datos['desde'] > datos['hasta']:
            raise forms.ValidationError('La fecha inicial no puede ser posterior a la final.')
        if datos.get('hasta') and datos['hasta'].year == 9999:
            raise forms.ValidationError('Selecciona una fecha final anterior al año 9999.')
        return datos


def alcance_central(consulta, usuario):
    if es_superusuario_smartstock(usuario):
        return consulta
    casos = atenciones_visibles(usuario).order_by()
    textos = casos.annotate(texto=Cast('pk', output_field=CharField())).values('texto')
    permitido = Q(usuario_id=usuario.pk) | Q(atencion_id__in=casos.values('pk')) | Q(
        modelo='AtencionSoporte', objeto_id__in=textos)
    if es_administrador_plataforma(usuario):
        permitido |= Q(modelo='Empresa')
    return consulta.filter(permitido)


def ambito(request):
    empresa = empresa_para_consulta(request, 'auditoria')
    alias = empresa.alias_bd if empresa else 'central'
    consulta = consulta_base().using(alias)
    if not empresa:
        consulta = alcance_central(consulta, request.user)
    modulo = Case(
        *(When(modulo='', modelo=nombre, then=Value(etiqueta)) for nombre, etiqueta in MODULOS.items()),
        When(modulo='', then=F('modelo')), default=F('modulo'), output_field=CharField())
    return empresa, consulta.annotate(modulo_visible=modulo)


def parametros(request, **cambios):
    datos = {campo: request.GET[campo] for campo in CAMPOS_URL if request.GET.get(campo)}
    datos.update(parametros_atencion(request))
    for campo, valor in cambios.items():
        if valor is None or valor == '':
            datos.pop(campo, None)
        else:
            datos[campo] = str(valor)
    return datos


def enlace(request, ruta='sistema_auditoria', **cambios):
    datos = parametros(request, **cambios)
    return reverse(ruta) + ('?' + urlencode(datos) if datos else '')


def filtrar(consulta, datos):
    if texto := datos.get('search'):
        consulta = consulta.filter(Q(descripcion__icontains=texto) | Q(objeto_id__icontains=texto)
            | Q(usuario__nombres__icontains=texto) | Q(usuario__apellidos__icontains=texto)
            | Q(usuario__email__icontains=texto) | Q(actor__nombre__icontains=texto)
            | Q(actor__email__icontains=texto) | Q(operacion__icontains=texto)
            | Q(empresa_nombre__icontains=texto) | Q(empresa_codigo__icontains=texto))
    if actor := datos.get('actor'):
        if actor == 'sin_identidad':
            consulta = consulta.filter(actor={}, usuario__isnull=True)
        else:
            origen, identificador = actor.split(':')
            anterior = Q(actor={}, usuario_id=int(identificador))
            # La FK del historial antiguo siempre pertenece a su propia base.
            if origen != ('smartstock' if consulta.db == 'central' else 'empresa'):
                anterior = Q(pk__in=[])
            consulta = consulta.filter(Q(actor__origen=origen, actor__id=identificador) | anterior)
    if usuario := datos.get('usuario'):
        consulta = consulta.filter(usuario__isnull=True) if usuario == 'sin_usuario' else consulta.filter(usuario_id=int(usuario))
    if accion := datos.get('accion'):
        consulta = consulta.filter(accion_mostrada__iexact=accion)
    if modulo := datos.get('modulo'):
        consulta = consulta.filter(modulo_visible=modulo)
    if modelo := datos.get('modelo'):
        consulta = consulta.filter(modelo__iexact=modelo)
    if resultado := datos.get('resultado'):
        consulta = consulta.filter(resultado='' if resultado == 'sin_registro' else resultado)
    vista = datos.get('vista') or 'todos'
    if vista == 'cambios':
        consulta = consulta.filter(accion_mostrada__in=['CREATE', 'UPDATE', 'DEACTIVATE', 'REACTIVATE', 'DELETE', 'EXPORT'])
    elif vista == 'accesos':
        consulta = consulta.filter(Q(accion_mostrada__in=['LOGIN', 'LOGOUT', 'LOGIN_FAILED', 'ACCESS_DENIED'])
            | Q(modelo='AtencionSoporte'))
    elif vista == 'consultas':
        consulta = consulta.filter(accion_mostrada='CONSULTA')
    for campo, operador, dias in [('desde', 'gte', 0), ('hasta', 'lt', 1)]:
        if datos.get(campo):
            fecha = datos[campo] + timedelta(days=dias)
            consulta = consulta.filter(**{'fecha_creacion__' + operador:
                timezone.make_aware(datetime.combine(fecha, time.min))})
    return consulta


def presentar_valor(valor):
    if valor is None or valor == '':
        return 'Sin valor'
    if isinstance(valor, bool):
        return 'Sí' if valor else 'No'
    if isinstance(valor, list):
        return ', '.join(str(v) for v in valor)
    return str(valor)


def presentar(evento, empresa=None, empresas=None):
    datos = datos_evento(evento, detalle=True)
    actor = evento.actor if isinstance(evento.actor, dict) else {}
    datos.update(usuario=actor.get('nombre') or datos['usuario'], usuario_email=actor.get('email') or datos['usuario_email'],
        perfil=actor.get('perfil', ''), origen_actor=actor.get('origen', ''),
        actor_id=actor.get('id') or datos['usuario_id'], identidad_guardada=bool(actor),
        modulo_mostrado=evento.modulo_visible, operacion=evento.operacion or datos['accion_etiqueta'],
        resultado=evento.resultado, resultado_etiqueta=RESULTADOS.get(evento.resultado, 'No registrado'),
        empresa_nombre=evento.empresa_nombre or (empresa.nombre if empresa else ''),
        empresa_codigo=evento.empresa_codigo or (empresa.codigo if empresa else ''),
        atencion_id=evento.atencion_id, cambios=[
            {'campo': ETIQUETAS[campo], 'antes': presentar_valor(valores['antes']), 'despues': presentar_valor(valores['despues'])}
            for campo, valores in cambios_seguros(evento.cambios).items()])
    if not datos['empresa_nombre'] and evento.modelo == 'Empresa' and empresas:
        anterior = empresas.get(evento.objeto_id)
        if anterior:
            datos.update(empresa_nombre=anterior.nombre, empresa_codigo=anterior.codigo)
    # El resumen nunca sustituye la descripción completa del detalle.
    resumen = evento.descripcion
    if resumen.startswith('SmartStock · ') and len(resumen.split(' · ', 2)) == 3:
        resumen = resumen.split(' · ', 2)[2]
    if datos['accion'] == 'CONSULTA':
        resumen = {'completada': 'Consulta completada.', 'fallida': 'La consulta no se completó.',
            'denegada': 'Consulta denegada.', 'solicitada': 'Solicitud registrada; resultado sin confirmar.'}.get(
                evento.resultado, 'Consulta sin resultado registrado.')
    datos['resumen'] = Truncator(' '.join(resumen.split())).chars(180)
    datos['resultado_ayuda'] = ('Se registró la solicitud, pero no quedó confirmado su resultado.'
                              if evento.resultado == 'solicitada' else '')
    datos['fecha_dia'], datos['fecha_hora'] = datos['fecha'].split(' ')
    datos['tipo_accion'] = {'DEACTIVATE': 'desactivar', 'REACTIVATE': 'crear', 'CREATE': 'crear',
        'DELETE': 'alerta', 'ACCESS_DENIED': 'alerta', 'LOGIN_FAILED': 'alerta'}.get(datos['accion'], 'normal')
    return datos


def opciones(consulta):
    actores = {}
    for fila in consulta.order_by().values('actor', 'usuario_id', 'usuario__nombres', 'usuario__apellidos', 'usuario__email').distinct()[:501]:
        actor = fila['actor'] or {}
        if actor.get('id') and actor.get('origen') in ('smartstock', 'empresa'):
            clave = f'{actor["origen"]}:{actor["id"]}'
            nombre, correo = actor.get('nombre', ''), actor.get('email', '')
        elif fila['usuario_id']:
            clave = f'{"smartstock" if consulta.db == "central" else "empresa"}:{fila["usuario_id"]}'
            nombre = f'{fila["usuario__nombres"]} {fila["usuario__apellidos"]}'.strip()
            correo = fila['usuario__email']
        else:
            clave, nombre, correo = 'sin_identidad', 'Sin identidad registrada', ''
        actores[clave] = {'valor': clave, 'etiqueta': f'{nombre} · {correo}' if correo else nombre}
    tipos = list(consulta.order_by().values_list('modulo_visible', 'accion_mostrada').distinct()[:500])
    return {'actores': sorted(actores.values(), key=lambda a: a['etiqueta'].casefold()),
            'modulos': sorted({m for m, _ in tipos if m}),
            'acciones': [(a, ACCIONES.get(a, a)) for a in sorted({a for _, a in tipos})],
            'resultados': RESULTADOS.items()}


def puede_exportar(request, empresa):
    return bool(es_administrador_plataforma(request.user) and (
        not empresa or acceso_para(request, empresa, 'exportar', exigir=False)))


def grupos(eventos, agrupar):
    def clave(evento):
        if not agrupar or evento['accion'] != 'CONSULTA':
            return ('evento', evento['id'])
        fecha = datetime.fromisoformat(evento['fecha_iso'])
        identidad = (evento['origen_actor'], evento['actor_id'], evento['usuario_email'], evento['perfil'])
        if not (evento['actor_id'] or evento['usuario_email']):
            return ('evento', evento['id'])
        return ('consulta', identidad,
                evento['modulo_mostrado'], evento['operacion'], evento['resultado'], evento['atencion_id'],
                int(fecha.timestamp()) // 300)
    salida = []
    for _, grupo in groupby(eventos, key=clave):
        filas = list(grupo)
        empresas = {('codigo', e['empresa_codigo']) if e['empresa_codigo'] else ('nombre', e['empresa_nombre'])
                    for e in filas if e['empresa_codigo'] or e['empresa_nombre']}
        fechas = sorted(datetime.fromisoformat(e['fecha_iso']) for e in filas)
        inicio, fin = fechas[0], fechas[-1]
        intervalo = inicio.strftime('%d/%m/%Y · %H:%M:%S')
        if fin != inicio:
            intervalo += '–' + fin.strftime('%H:%M:%S' if inicio.date() == fin.date() else '%d/%m/%Y %H:%M:%S')
        salida.append({'eventos': filas, 'cantidad_empresas': len(empresas), 'intervalo': intervalo})
    return salida


def listado(request):
    from .sistema import contexto_sistema
    empresa, consulta = ambito(request)
    contexto = contexto_sistema(request, 'auditoria', 'Auditoría', empresa)
    formulario = Filtros({k: v for k, v in request.GET.items() if v != ''})
    contexto.update(formulario_auditoria=formulario, ambito_nombre=empresa.nombre if empresa else 'Plataforma SmartStock',
        exportacion_permitida=puede_exportar(request, empresa), limpiar_url=enlace(request,
            **{k: None for k in CAMPOS_URL if k not in ('empresa', 'atencion')}),
        vista=request.GET.get('vista', 'todos'), agrupar=request.GET.get('agrupar', '1') == '1')
    contexto['filtros_avanzados_activos'] = sum(bool(request.GET.get(campo)) for campo in (
        'actor', 'usuario', 'accion', 'modulo', 'modelo', 'resultado'))
    contexto['vistas'] = [{'nombre': nombre, 'valor': valor, 'url': enlace(request, vista=valor, page=None)}
                           for valor, nombre in VISTAS]
    hoy = timezone.localdate()
    contexto['periodos'] = [{'nombre': nombre, 'url': enlace(request, desde=(hoy - timedelta(days=dias)).isoformat(),
        hasta=hoy.isoformat(), page=None)} for nombre, dias in [('Hoy', 0), ('Últimos 7 días', 6), ('Últimos 30 días', 29)]]
    contexto['exportar_url'] = enlace(request, 'sistema_auditoria_exportar', page=None)
    contexto['imprimir_url'] = enlace(request, 'sistema_auditoria_reporte', page=None)
    try:
        contexto.update(opciones(consulta))
        if formulario.is_valid():
            eventos = filtrar(consulta, formulario.cleaned_data)
            pagina = Paginator(eventos, 25).get_page(request.GET.get('page'))
            empresas = {str(e.pk): e for e in contexto['empresas_disponibles']}
            filas = [presentar(e, empresa, empresas) for e in pagina.object_list]
            for fila in filas:
                fila['detalle_url'] = reverse('sistema_auditoria_detalle', args=[fila['id']]) + '?' + urlencode(parametros(request))
            contexto.update(eventos=filas, grupos_eventos=grupos(filas, contexto['agrupar']), pagina=pagina,
                paginas=[{'numero': n, 'url': enlace(request, page=n)} if n != pagina.paginator.ELLIPSIS else {'salto': True}
                         for n in pagina.paginator.get_elided_page_range(pagina.number, on_each_side=1, on_ends=1)],
                anterior_url=enlace(request, page=pagina.previous_page_number()) if pagina.has_previous() else '',
                siguiente_url=enlace(request, page=pagina.next_page_number()) if pagina.has_next() else '')
            if empresa:
                registrar_empresa_consultada(request, empresa, 'completada')
        elif empresa:
            registrar_empresa_consultada(request, empresa, 'fallida')
    except DatabaseError:
        if empresa:
            registrar_empresa_consultada(request, empresa, 'fallida')
        contexto['error_consulta'] = 'No pudimos consultar la auditoría. Vuelve a intentarlo.'
    return render(request, 'sistema/auditoria.html', contexto)


@requiere_personal
@require_GET
def detalle(request, evento_id):
    from .sistema import contexto_sistema
    empresa, consulta = ambito(request)
    registro = get_object_or_404(consulta, pk=evento_id)
    contexto = contexto_sistema(request, 'auditoria', 'Detalle del evento', empresa)
    contexto.update(evento=presentar(registro, empresa, {str(e.pk): e for e in contexto['empresas_disponibles']}),
        volver_url=enlace(request), ambito_nombre=empresa.nombre if empresa else 'Plataforma SmartStock')
    if empresa:
        registrar_empresa_consultada(request, empresa, 'completada')
    return render(request, 'sistema/auditoria_detalle.html', contexto)


def preparar_exportacion(request):
    empresa, consulta = ambito(request)
    if not puede_exportar(request, empresa):
        raise PermissionDenied('Tu perfil o la autorización de la empresa no permiten exportar la auditoría.')
    formulario = Filtros({k: v for k, v in request.GET.items() if v != ''})
    if not formulario.is_valid():
        return empresa, None, formulario
    return empresa, fijar_reporte(filtrar(consulta, formulario.cleaned_data)), formulario


def auditar_exportacion(request, empresa, identificador, resultado, formato):
    return crear_evento(alias='central', request=request, empresa=empresa, accion='EXPORT', modelo='Auditoria',
        objeto_id=identificador, operacion=f'Exportación de auditoría {formato}', resultado=resultado,
        descripcion=f'Exportación {formato} del ámbito autorizado. Identificador {identificador}.')


def consulta_actual(request):
    """La descarga no prolonga una autorización revocada o caducada."""
    actual = copy(request)
    actual.user = Usuario.objects.using('central').select_related('rol').get(pk=request.user.pk)
    actual._lecturas_acceso = {}
    if not es_personal_smartstock(actual.user):
        raise PermissionDenied
    empresa, consulta, _ = preparar_exportacion(actual)
    return consulta


@requiere_personal
@require_GET
def exportar(request):
    empresa, consulta, formulario = preparar_exportacion(request)
    if consulta is None:
        return render(request, 'sistema/auditoria_error.html', {'errores': formulario.errors}, status=400)
    alias, identificador = consulta.db, str(uuid4())
    auditar_exportacion(request, empresa, identificador, 'solicitada', 'CSV')

    def contenido():
        escritor, ultimo, resultado = csv.writer(SalidaCSV(), delimiter=';'), None, 'fallida'
        try:
            yield '\ufeff'
            yield escritor.writerow(['Reporte', 'Auditoría de ' + (empresa.nombre if empresa else 'Plataforma SmartStock')])
            yield escritor.writerow(['Zona horaria', timezone.get_current_timezone_name()])
            yield escritor.writerow(['Generado', timezone.localtime().isoformat()])
            yield escritor.writerow(['ID de exportación', identificador])
            yield escritor.writerow(['Filtros', urlencode(parametros(request, page=None))])
            yield escritor.writerow(['ID', 'Fecha / hora', 'Zona horaria', 'Usuario', 'Correo', 'Perfil registrado',
                'Empresa', 'Acción', 'Módulo', 'Resultado', 'Descripción', 'Atención', 'IP', 'Navegador / dispositivo', 'Cambios'])
            while True:
                actual = consulta_actual(request).using(alias).filter(pk__in=consulta.values('pk'))
                if ultimo:
                    actual = actual.filter(Q(fecha_creacion__lt=ultimo.fecha_creacion) |
                        Q(fecha_creacion=ultimo.fecha_creacion, pk__lt=ultimo.pk))
                lote = list(actual[:200])
                if not lote:
                    resultado = 'completada'
                    break
                for registro in lote:
                    e = presentar(registro, empresa)
                    cambios = '; '.join(f'{c["campo"]}: {c["antes"]} → {c["despues"]}' for c in e['cambios'])
                    yield escritor.writerow([celda_csv(v) for v in [e['id'], e['fecha'], e['zona_horaria'],
                        e['usuario'], e['usuario_email'], e['perfil'], e['empresa_nombre'], e['operacion'],
                        e['modulo_mostrado'], e['resultado_etiqueta'], e['descripcion'], e['atencion_id'],
                        e['ip_address'], e['user_agent'], cambios]])
                ultimo = lote[-1]
        except (PermissionDenied, Usuario.DoesNotExist):
            resultado = 'denegada'
            yield escritor.writerow(['Exportación interrumpida', 'La autorización dejó de estar vigente.'])
        except DatabaseError:
            yield escritor.writerow(['Exportación interrumpida', 'No pudimos completar la lectura de todos los eventos.'])
        finally:
            try:
                auditar_exportacion(request, empresa, identificador, resultado, 'CSV')
            except DatabaseError:
                pass
    respuesta = StreamingHttpResponse(contenido(), content_type='text/csv; charset=utf-8')
    respuesta['Content-Disposition'] = 'attachment; filename="auditoria-smartstock.csv"'
    return respuesta


@requiere_personal
@require_GET
def reporte(request):
    empresa, consulta, formulario = preparar_exportacion(request)
    if consulta is None:
        return render(request, 'sistema/auditoria_error.html', {'errores': formulario.errors}, status=400)
    filas = list(consulta[:5001])
    if len(filas) > 5000:
        return render(request, 'sistema/auditoria_error.html',
            {'errores': 'El documento admite hasta 5.000 eventos. Acota las fechas o utiliza CSV.'}, status=400)
    permitidos = consulta_actual(request).filter(pk__in=[e.pk for e in filas]).count()
    if permitidos != len(filas):
        raise PermissionDenied('Los permisos cambiaron mientras se preparaba el documento. Vuelve al historial.')
    respuesta = render(request, 'sistema/auditoria_reporte.html', {
        'eventos': [presentar(e, empresa) for e in filas], 'total': len(filas),
        'ambito_nombre': empresa.nombre if empresa else 'Plataforma SmartStock',
        'generado': timezone.localtime(), 'zona_horaria': timezone.get_current_timezone_name(),
        'generado_por': request.user.email, 'filtros': parametros(request, page=None)})
    auditar_exportacion(request, empresa, str(uuid4()), 'completada', 'Impresión / PDF')
    return respuesta
