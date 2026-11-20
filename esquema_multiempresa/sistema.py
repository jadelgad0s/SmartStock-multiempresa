"""Panel web del equipo de SmartStock y gestión de las cuentas de cada empresa."""
from types import SimpleNamespace
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from apps.core.empresa import usar_empresa
from apps.core.models import Auditoria
from apps.core.views_auditoria import consulta_filtrada, datos_evento
from apps.productos.models import Bodega, Producto
from apps.usuarios.models import Usuario
from rest_framework.exceptions import ValidationError
from .forms import CuentaTecnicaForm, EmpresaPanelForm, UsuarioEmpresaForm
from .models import Empresa
from .permisos import es_superusuario_smartstock, requiere_personal


def empresa_del_panel(codigo):
    return get_object_or_404(Empresa, codigo=codigo, alias_bd__in=settings.BASES_EMPRESA)


def contexto_sistema(request, modulo, titulo, empresa=None):
    if empresa is None and request.GET.get('empresa'):
        empresa = empresa_del_panel(request.GET['empresa'])
    contexto = {
        'titulo': titulo, 'modulo': modulo, 'empresa_seleccionada': empresa,
        'empresas_disponibles': list(Empresa.objects.order_by('nombre', 'id')),
        'es_superusuario': es_superusuario_smartstock(request.user),
    }
    secciones = [
        ('Visión general', [('inicio', 'Dashboard', 'chart-line', 'sistema_inicio')]),
        ('Gestión', [('empresas', 'Empresas', 'building', 'sistema_empresas'),
                     ('usuarios', 'Usuarios de empresas', 'users', 'sistema_usuarios')]),
        ('Inventario', [('inventario', 'Resumen por empresa', 'chart-pie', 'sistema_inventario'),
                        ('catalogo', 'Catálogo', 'box', 'sistema_catalogo'),
                        ('bodegas', 'Bodegas', 'warehouse', 'sistema_bodegas'),
                        ('reportes', 'Reportes', 'file-lines', 'sistema_reportes')]),
        ('Operaciones', [('movimientos', 'Movimientos', 'box-open', 'sistema_movimientos'),
                         ('transferencias', 'Transferencias', 'right-left', 'sistema_transferencias'),
                         ('mermas', 'Mermas y bajas', 'triangle-exclamation', 'sistema_mermas')]),
        ('Sistema', [('cuentas', 'Cuentas técnicas', 'user-gear', 'sistema_cuentas'),
                     ('sms', 'Alertas SMS', 'comment-sms', 'sistema_sms'),
                     ('auditoria', 'Auditoría', 'clipboard-list', 'sistema_auditoria')]),
    ]
    if contexto['es_superusuario']:
        secciones[-1][1].append(('configuracion', 'Configuración', 'sliders', 'sistema_admin:index'))
    contexto['secciones_menu'] = [
        {'nombre': nombre, 'enlaces': [
            {'nombre': texto, 'icono': icono, 'activo': clave == modulo,
             'url': reverse(ruta) + ('?' + urlencode({'empresa': empresa.codigo})
                                     if empresa and clave not in ('inicio', 'empresas', 'cuentas', 'configuracion') else '')}
            for clave, texto, icono, ruta in enlaces
        ]}
        for nombre, enlaces in secciones
    ]
    return contexto


def paginar(request, contexto, consulta):
    pagina = Paginator(consulta, 25).get_page(request.GET.get('page'))
    contexto['pagina'] = pagina
    filtros = request.GET.copy()
    filtros.pop('page', None)
    contexto['filtros_pagina'] = filtros.urlencode()
    return pagina.object_list


def parametros_consulta(request):
    parametros = request.GET.copy()
    for campo in list(parametros):
        if parametros[campo] == '':
            del parametros[campo]
    return parametros


def auditar_gestion(request, alias, accion, modelo, objeto, descripcion):
    # Las cuentas del equipo pertenecen a la central. En una empresa el actor
    # queda identificado en la descripción, sin una FK entre bases distintas.
    Auditoria.objects.using(alias).create(
        usuario=request.user if alias == 'central' else None,
        accion=accion, modelo=modelo, objeto_id=str(objeto.pk),
        descripcion=f'SmartStock · {request.user.email} · {descripcion}',
        ip_address=request.META.get('REMOTE_ADDR'),
    )


def resumen_empresa(empresa):
    datos = {'empresa': empresa, 'disponible': True}
    if empresa.alias_bd not in settings.BASES_EMPRESA:
        datos['disponible'] = False
        return datos
    try:
        with usar_empresa(empresa):
            datos.update(usuarios=Usuario.objects.filter(is_superuser=False).count(),
                         productos=Producto.objects.filter(activo=True).count(),
                         bodegas=Bodega.objects.filter(activa=True).count())
    except DatabaseError:
        datos['disponible'] = False
    return datos


@requiere_personal
@require_http_methods(['GET'])
def inicio_sistema(request):
    contexto = contexto_sistema(request, 'inicio', 'Resumen de SmartStock')
    empresas = contexto['empresas_disponibles']
    resumenes = [resumen_empresa(empresa) for empresa in empresas]
    disponibles = all(fila['disponible'] for fila in resumenes)
    contexto.update(
        resumen_empresas=resumenes,
        kpis=[
            ('Empresas registradas', len(empresas)),
            ('Empresas activas', sum(empresa.activa for empresa in empresas)),
            ('Usuarios de empresas', sum(fila.get('usuarios', 0) for fila in resumenes) if disponibles else None),
            ('Personal activo de SmartStock', Usuario.objects.using('central').filter(is_staff=True, activo=True).count()),
        ],
    )
    return render(request, 'sistema/inicio.html', contexto)


@requiere_personal
@require_http_methods(['GET'])
def empresas_sistema(request):
    contexto = contexto_sistema(request, 'empresas', 'Empresas')
    consulta = Empresa.objects.order_by('nombre', 'id')
    texto = request.GET.get('search', '').strip()[:200]
    if texto:
        consulta = consulta.filter(Q(nombre__icontains=texto) | Q(codigo__icontains=texto))
    contexto['resumen_empresas'] = [resumen_empresa(empresa) for empresa in paginar(request, contexto, consulta)]
    return render(request, 'sistema/empresas.html', contexto)


@requiere_personal
@require_http_methods(['GET', 'POST'])
def editar_empresa(request, codigo=None):
    empresa = empresa_del_panel(codigo) if codigo else Empresa()
    formulario = EmpresaPanelForm(request.POST or None, instance=empresa)
    if request.method == 'POST' and formulario.is_valid():
        nueva = empresa._state.adding
        try:
            with transaction.atomic(using='central'):
                guardada = formulario.save()
                auditar_gestion(request, 'central', 'CREATE' if nueva else 'UPDATE', 'Empresa', guardada,
                                f'Empresa guardada · {guardada.nombre}')
        except IntegrityError:
            formulario.add_error(None, 'El código o la base ya están vinculados a otra empresa. Revisa los datos.')
        else:
            messages.success(request, 'Empresa guardada correctamente.')
            return redirect('sistema_empresas')
    contexto = contexto_sistema(request, 'empresas', 'Añadir empresa' if codigo is None else 'Editar empresa')
    contexto.update(formulario=formulario, volver=reverse('sistema_empresas'))
    return render(request, 'sistema/formulario.html', contexto)


@requiere_personal
@require_http_methods(['GET'])
def usuarios_sistema(request):
    contexto = contexto_sistema(request, 'usuarios', 'Usuarios de empresas')
    empresa = contexto['empresa_seleccionada']
    if empresa is not None:
        try:
            with usar_empresa(empresa):
                consulta = Usuario.objects.filter(is_superuser=False).select_related('rol').order_by('nombres', 'apellidos', 'id')
                texto = request.GET.get('search', '').strip()[:200]
                if texto:
                    consulta = consulta.filter(Q(email__icontains=texto) | Q(nombres__icontains=texto) | Q(apellidos__icontains=texto))
                contexto['usuarios_empresa'] = list(paginar(request, contexto, consulta))
        except DatabaseError:
            contexto['error_consulta'] = 'No pudimos consultar los usuarios de esta empresa. Vuelve a intentarlo.'
    return render(request, 'sistema/usuarios.html', contexto)


@requiere_personal
@require_http_methods(['GET'])
def cuentas_sistema(request):
    contexto = contexto_sistema(request, 'cuentas', 'Cuentas técnicas de SmartStock')
    consulta = Usuario.objects.using('central').filter(is_staff=True).order_by('nombres', 'apellidos', 'id')
    texto = request.GET.get('search', '').strip()[:200]
    if texto:
        consulta = consulta.filter(Q(email__icontains=texto) | Q(nombres__icontains=texto) | Q(apellidos__icontains=texto))
    contexto['cuentas_tecnicas'] = list(paginar(request, contexto, consulta))
    return render(request, 'sistema/cuentas.html', contexto)


def formulario_cuenta(request, empresa, usuario_id):
    es_nueva = usuario_id is None
    alias = empresa.alias_bd if empresa else 'central'
    consulta = Usuario.objects.using(alias).filter(is_superuser=False) if empresa else Usuario.objects.using(alias).filter(is_staff=True)
    usuario = get_object_or_404(consulta, pk=usuario_id) if usuario_id else Usuario()
    if empresa is None and usuario.is_superuser and not request.user.is_superuser:
        raise PermissionDenied
    opciones = {'alias': alias} if empresa else {'actor': request.user}
    clase = UsuarioEmpresaForm if empresa else CuentaTecnicaForm
    estaba_activo = usuario.activo
    with usar_empresa(empresa):
        formulario = clase(request.POST or None, instance=usuario, **opciones)
        if request.method == 'POST' and formulario.is_valid():
            try:
                with transaction.atomic(using=alias):
                    guardado = formulario.save()
                    accion = 'CREATE' if es_nueva else 'UPDATE'
                    if not es_nueva and estaba_activo != guardado.activo:
                        accion = 'REACTIVATE' if guardado.activo else 'DEACTIVATE'
                    auditar_gestion(request, alias, accion, 'Usuario', guardado,
                                    f'Cuenta guardada · {guardado.email}')
            except IntegrityError:
                formulario.add_error(None, 'Ya existe una cuenta con esos datos. Revisa el correo electrónico.')
            else:
                if empresa is None and guardado.pk == request.user.pk:
                    update_session_auth_hash(request, guardado)
                messages.success(request, 'Cuenta guardada correctamente.')
                destino = reverse('sistema_usuarios') + '?' + urlencode({'empresa': empresa.codigo}) if empresa else reverse('sistema_cuentas')
                return redirect(destino)
        titulo = ('Añadir usuario' if es_nueva else 'Editar usuario') if empresa else (
            'Añadir cuenta técnica' if es_nueva else 'Editar cuenta técnica')
        contexto = contexto_sistema(request, 'usuarios' if empresa else 'cuentas', titulo, empresa=empresa)
        contexto.update(formulario=formulario,
                        volver=reverse('sistema_usuarios') + '?' + urlencode({'empresa': empresa.codigo}) if empresa else reverse('sistema_cuentas'))
        return render(request, 'sistema/formulario.html', contexto)


@requiere_personal
@require_http_methods(['GET', 'POST'])
def editar_usuario_empresa(request, codigo, usuario_id=None):
    return formulario_cuenta(request, empresa_del_panel(codigo), usuario_id)


@requiere_personal
@require_http_methods(['GET', 'POST'])
def editar_cuenta_tecnica(request, usuario_id=None):
    return formulario_cuenta(request, None, usuario_id)


@requiere_personal
@require_http_methods(['GET'])
def auditoria_sistema(request):
    contexto = contexto_sistema(request, 'auditoria', 'Auditoría')
    empresa = contexto['empresa_seleccionada']
    try:
        with usar_empresa(empresa):
            consulta, _ = consulta_filtrada(SimpleNamespace(query_params=parametros_consulta(request)))
            contexto['eventos'] = [datos_evento(evento) for evento in paginar(request, contexto, consulta)]
    except ValidationError:
        contexto['error_consulta'] = 'Revisa las fechas y los filtros de la consulta.'
    except DatabaseError:
        contexto['error_consulta'] = 'No pudimos consultar la auditoría. Vuelve a intentarlo.'
    return render(request, 'sistema/auditoria.html', contexto)


@requiere_personal
def abrir_configuracion(request):
    if not es_superusuario_smartstock(request.user):
        raise PermissionDenied
    return redirect('sistema_admin:index')
