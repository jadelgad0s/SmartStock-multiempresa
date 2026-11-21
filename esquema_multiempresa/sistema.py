"""Panel web del equipo de SmartStock y gestión de las cuentas de cada empresa."""
from urllib.parse import urlencode
from smtplib import SMTPException

from django.conf import settings
from django.contrib.auth import update_session_auth_hash
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import DatabaseError, IntegrityError, transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from apps.core.empresa import usar_empresa
from apps.core.registro_auditoria import crear_evento, diferencias, estado_auditable
from apps.productos.models import Bodega, Producto
from apps.usuarios.models import Rol, Usuario
from rest_framework.exceptions import ValidationError
from .forms import CuentaTecnicaForm, EmpresaPanelForm, UsuarioEmpresaForm
from .models import Empresa
from .models import AtencionSoporte, AccesoSoporte, BuzonContacto
from .autorizacion_soporte import (acceso_para, accesos_vigentes, alcances_actuales, atenciones_visibles,
    auditar_soporte, empresas_visibles, empresa_para_consulta, parametros_atencion)
from .cuentas_empresa import enviar_enlace, puede_invitar_inicial
from .notificaciones import confirmar_guardado, confirmaciones_para_pagina
from .permisos import (
    CONTACTO, CORREO_CONTACTO, es_administrador_plataforma, es_cuenta_interna,
    es_superusuario_smartstock, nombre_perfil_personal,
    registrar_empresa_consultada, requiere_administrador_plataforma, requiere_personal,
    requiere_superusuario,
)


def empresa_del_panel(codigo, request=None):
    if request is not None:
        empresa = next((e for e in empresas_del_menu(request) if e.codigo == codigo), None)
        if empresa is None:
            from django.http import Http404
            raise Http404
        return empresa
    consulta = empresas_visibles(request.user) if request else Empresa.objects.filter(alias_bd__in=settings.BASES_EMPRESA)
    return get_object_or_404(consulta, codigo=codigo)


def empresas_del_menu(request):
    if not hasattr(request, '_empresas_menu'):
        request._empresas_menu = list(empresas_visibles(request.user).order_by('nombre', 'id'))
    return request._empresas_menu


def contexto_sistema(request, modulo, titulo, empresa=None):
    if empresa is None and request.GET.get('empresa'):
        empresa = empresa_del_panel(request.GET['empresa'], request)
    gestor = es_administrador_plataforma(request.user)
    alcances = alcances_actuales(request)
    acceso = getattr(request, '_acceso_soporte', None)
    contexto = {
        'titulo': titulo, 'modulo': modulo, 'empresa_seleccionada': empresa,
        'empresas_disponibles': empresas_del_menu(request),
        'es_superusuario': es_superusuario_smartstock(request.user),
        'puede_gestionar_empresas': es_administrador_plataforma(request.user),
        'perfil_personal': nombre_perfil_personal(request.user),
        'confirmaciones': confirmaciones_para_pagina(request),
        'es_gestor': gestor, 'acceso_soporte': acceso, 'alcances_soporte': alcances,
        'puede_gestionar_usuarios': 'gestionar_usuarios' in alcances,
        'puede_exportar': gestor and 'exportar' in alcances,
        'puede_recuperar_acceso': 'recuperar_acceso' in alcances,
    }
    request._modulo_consultado = titulo
    if empresa is not None and modulo not in ('cuentas', 'mi_cuenta'):
        registrar_empresa_consultada(request, empresa)
    secciones = [
        ('Visión general', [('inicio', 'Dashboard', 'chart-line', 'sistema_inicio')]),
        ('Gestión', [('empresas', 'Empresas' if gestor else 'Empresas asignadas', 'building', 'sistema_empresas'),
                     ('usuarios', 'Usuarios de empresas', 'users', 'sistema_usuarios'),
                     ('atenciones', 'Atenciones de soporte', 'headset', 'sistema_atenciones')]),
        ('Consulta autorizada', [('inventario', 'Resumen por empresa', 'chart-pie', 'sistema_inventario'),
                        ('catalogo', 'Catálogo', 'box', 'sistema_catalogo'),
                        ('bodegas', 'Bodegas', 'warehouse', 'sistema_bodegas'),
                        ('reportes', 'Reportes', 'file-lines', 'sistema_reportes'),
                        ('movimientos', 'Movimientos', 'box-open', 'sistema_movimientos'),
                         ('transferencias', 'Transferencias', 'right-left', 'sistema_transferencias'),
                         ('mermas', 'Mermas y bajas', 'triangle-exclamation', 'sistema_mermas'),
                         ('sms', 'Diagnóstico de SMS', 'comment-sms', 'sistema_sms')]),
        ('Sistema', [('diagnostico', 'Diagnóstico', 'heart-pulse', 'sistema_diagnostico'),
                     ('auditoria', 'Auditoría', 'clipboard-list', 'sistema_auditoria')]),
    ]
    secciones = [(nombre, [enlace for enlace in enlaces if (
        nombre != 'Consulta autorizada' or enlace[0] in alcances) and (
        gestor or enlace[0] != 'usuarios' or 'usuarios' in alcances)]) for nombre, enlaces in secciones]
    if contexto['es_superusuario']:
        secciones[-1][1].insert(0, ('cuentas', 'Equipo de SmartStock', 'user-gear', 'sistema_cuentas'))
        secciones[-1][1].insert(1, ('contacto', 'Cuenta de contacto', 'envelope', 'sistema_cuenta_contacto'))
        secciones[-1][1].append(('configuracion', 'Configuración', 'sliders', 'sistema_admin:index'))
    contexto['secciones_menu'] = [
        {'nombre': nombre, 'enlaces': [
            {'nombre': texto, 'icono': icono, 'activo': clave == modulo,
            'url': reverse(ruta) + ('?' + urlencode({'empresa': empresa.codigo, **parametros_atencion(request)})
                                     if empresa and clave not in ('inicio', 'empresas', 'cuentas', 'configuracion', 'mi_cuenta') else '')}
            for clave, texto, icono, ruta in enlaces
        ]}
        for nombre, enlaces in secciones if enlaces
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


def auditar_gestion(request, alias, accion, modelo, objeto, descripcion, *, operacion='', cambios=None, resultado='completada'):
    # Las cuentas del equipo pertenecen a la central. En una empresa el actor
    # queda identificado en la descripción, sin una FK entre bases distintas.
    return crear_evento(alias=alias, request=request,
        accion=accion, modelo=modelo, objeto_id=str(objeto.pk),
        descripcion=f'SmartStock · {request.user.email} · {descripcion}',
        operacion=operacion or descripcion.split(' · ')[0], cambios=cambios, resultado=resultado,
        empresa=objeto if modelo == 'Empresa' else None,
    )


def resumen_empresa(empresa, request=None):
    if request is not None:
        registrar_empresa_consultada(request, empresa)
    datos = {'empresa': empresa, 'disponible': True}
    if request is not None and not es_administrador_plataforma(request.user):
        # La ficha asignada procede del directorio central; consultar las
        # cuentas del cliente requiere su autorización específica.
        return datos
    if empresa.alias_bd not in settings.BASES_EMPRESA:
        datos['disponible'] = False
        return datos
    try:
        with usar_empresa(empresa):
            clave_usable = ~Q(password__startswith='!') & ~Q(password='')
            conteos = Usuario.objects.aggregate(
                usuarios=Count('pk', filter=Q(is_superuser=False)),
                administradores=Count('pk', filter=Q(activo=True, rol__codigo='administrador', rol__activo=True) & clave_usable),
                con_acceso=Count('pk', filter=clave_usable))
            datos.update(usuarios=conteos['usuarios'], administrador=bool(conteos['administradores']),
                         puede_invitar=not conteos['con_acceso'])
    except DatabaseError:
        datos['disponible'] = False
    return datos


@requiere_personal
@require_http_methods(['GET'])
def inicio_sistema(request):
    contexto = contexto_sistema(request, 'inicio', 'Resumen de SmartStock')
    empresas = contexto['empresas_disponibles']
    gestor = es_administrador_plataforma(request.user)
    resumenes = [resumen_empresa(empresa, request) for empresa in empresas] if gestor else []
    disponibles = all(fila['disponible'] for fila in resumenes)
    contexto.update(
        resumen_empresas=resumenes,
        atenciones=list(atenciones_visibles(request.user)[:8]),
        kpis=[
            ('Empresas registradas', len(empresas)),
            ('Empresas activas', sum(empresa.activa for empresa in empresas)),
            ('Usuarios de empresas', sum(fila.get('usuarios', 0) for fila in resumenes) if disponibles else None),
            ('Personal activo de SmartStock', sum(es_cuenta_interna(cuenta) for cuenta in
                Usuario.objects.using('central').filter(is_staff=True, activo=True).select_related('rol'))),
        ] if gestor else [
            ('Atenciones abiertas', atenciones_visibles(request.user).filter(estado='abierta').count()),
            ('Empresas asignadas', len(empresas)),
            ('Solicitudes pendientes', AccesoSoporte.objects.using('central').filter(tecnico=request.user, estado='pendiente').count()),
            ('Accesos vigentes', accesos_vigentes(request.user).count()),
        ],
    )
    return render(request, 'sistema/inicio.html', contexto)


@requiere_personal
@require_http_methods(['GET'])
def empresas_sistema(request):
    contexto = contexto_sistema(request, 'empresas', 'Empresas')
    consulta = empresas_visibles(request.user).order_by('nombre', 'id')
    texto = request.GET.get('search', '').strip()[:200]
    if texto:
        consulta = consulta.filter(Q(nombre__icontains=texto) | Q(codigo__icontains=texto)
                                   | Q(razon_social__icontains=texto) | Q(rut__icontains=texto.replace('.', '').upper())
                                   | Q(contacto_email__icontains=texto))
    contexto['resumen_empresas'] = [resumen_empresa(empresa, request) for empresa in paginar(request, contexto, consulta)]
    return render(request, 'sistema/empresas.html', contexto)


@requiere_administrador_plataforma
@require_http_methods(['GET', 'POST'])
def editar_empresa(request, codigo=None):
    empresa = empresa_del_panel(codigo, request) if codigo else Empresa()
    estaba_activa = empresa.activa
    formulario = EmpresaPanelForm(request.POST or None, instance=empresa)
    if request.method == 'POST' and formulario.is_valid():
        nueva = empresa._state.adding
        try:
            with transaction.atomic(using='central'):
                antes = estado_auditable(Empresa.objects.using('central').select_for_update().get(pk=empresa.pk)) if not nueva else {}
                guardada = formulario.save(commit=False)
                guardada.save(using='central')
                if not guardada.activa:
                    AccesoSoporte.objects.using('central').filter(atencion__empresa=guardada,
                        estado__in=['pendiente', 'aprobado']).update(estado='revocado')
                accion = 'CREATE' if nueva else 'UPDATE'
                if not nueva and antes.get('activa') != guardada.activa:
                    accion = 'REACTIVATE' if guardada.activa else 'DEACTIVATE'
                auditar_gestion(request, 'central', accion, 'Empresa', guardada,
                    f'Empresa guardada · {guardada.nombre}',
                    operacion='Empresa creada' if nueva else 'Ficha de empresa actualizada',
                    cambios=diferencias(antes, estado_auditable(guardada)))
        except IntegrityError:
            formulario.add_error(None, 'El RUT, el código o la base ya están vinculados a otra empresa. Revisa los datos.')
        else:
            titulo = 'Empresa creada' if nueva else 'Ficha de empresa actualizada'
            if not nueva and estaba_activa != guardada.activa:
                titulo = 'Acceso de empresa habilitado' if guardada.activa else 'Acceso de empresa suspendido'
            confirmar_guardado(request, alias='central', titulo=titulo,
                               mensaje=f'{guardada.nombre}: cambios guardados correctamente.',
                               link=reverse('sistema_ficha_empresa', args=[guardada.codigo]), empresa=guardada)
            return redirect('sistema_ficha_empresa', codigo=guardada.codigo)
    contexto = contexto_sistema(request, 'empresas', 'Añadir empresa' if codigo is None else 'Editar empresa',
                                empresa=empresa if codigo else None)
    contexto.update(formulario=formulario, volver=reverse('sistema_empresas'),
                    secciones_formulario=formulario.secciones(), nueva=empresa._state.adding,
                    sin_bases=empresa._state.adding and not formulario.bases_disponibles)
    return render(request, 'sistema/empresa_formulario.html', contexto)


@requiere_personal
@require_http_methods(['GET'])
def ficha_empresa(request, codigo):
    empresa = empresa_del_panel(codigo, request)
    resumen = resumen_empresa(empresa, request)
    if resumen['disponible']:
        try:
            with usar_empresa(empresa):
                if acceso_para(request, empresa, 'inventario', exigir=False):
                    resumen.update(productos=Producto.objects.filter(activo=True).count(),
                                   bodegas=Bodega.objects.filter(activa=True).count(), inventario_autorizado=True)
        except DatabaseError:
            resumen['disponible'] = False
    contexto = contexto_sistema(request, 'empresas', 'Ficha de empresa', empresa=empresa)
    contexto['resumen'] = resumen
    return render(request, 'sistema/empresa_ficha.html', contexto)


@requiere_personal
@require_http_methods(['GET'])
def usuarios_sistema(request):
    contexto = contexto_sistema(request, 'usuarios', 'Usuarios de empresas')
    empresa = contexto['empresa_seleccionada']
    if empresa is not None:
        if not es_administrador_plataforma(request.user):
            acceso_para(request, empresa, 'usuarios')
        else:
            acceso_para(request, empresa, 'usuarios', exigir=False)
        contexto = contexto_sistema(request, 'usuarios', 'Usuarios de empresas', empresa)
        try:
            with usar_empresa(empresa):
                contexto['puede_invitar_administrador'] = es_administrador_plataforma(request.user) and puede_invitar_inicial(empresa)
                consulta = Usuario.objects.filter(is_superuser=False).select_related('rol').order_by('nombres', 'apellidos', 'id')
                texto = request.GET.get('search', '').strip()[:200]
                if texto:
                    consulta = consulta.filter(Q(email__icontains=texto) | Q(nombres__icontains=texto) | Q(apellidos__icontains=texto))
                contexto['usuarios_empresa'] = list(paginar(request, contexto, consulta))
        except DatabaseError:
            contexto['error_consulta'] = 'No pudimos consultar los usuarios de esta empresa. Vuelve a intentarlo.'
    return render(request, 'sistema/usuarios.html', contexto)


@requiere_superusuario
@require_http_methods(['GET'])
def cuentas_sistema(request):
    contexto = contexto_sistema(request, 'cuentas', 'Equipo de SmartStock')
    consulta = Usuario.objects.using('central').filter(is_staff=True).select_related('rol').order_by('nombres', 'apellidos', 'id')
    texto = request.GET.get('search', '').strip()[:200]
    if texto:
        consulta = consulta.filter(Q(email__icontains=texto) | Q(nombres__icontains=texto) | Q(apellidos__icontains=texto))
    cuentas = list(paginar(request, contexto, consulta))
    for cuenta in cuentas:
        cuenta.perfil_mostrado = nombre_perfil_personal(cuenta)
        cuenta.perfil_habilitado = es_cuenta_interna(cuenta)
        cuenta.es_contacto = cuenta.email.lower() == CORREO_CONTACTO or bool(cuenta.rol_id and cuenta.rol.codigo == CONTACTO)
    contexto['cuentas_tecnicas'] = cuentas
    return render(request, 'sistema/cuentas.html', contexto)


def formulario_cuenta(request, empresa, usuario_id, propia=False):
    es_nueva = usuario_id is None
    alias = empresa.alias_bd if empresa else 'central'
    consulta = Usuario.objects.using(alias).select_related('rol')
    consulta = consulta.filter(is_superuser=False) if empresa else consulta.filter(is_staff=True)
    usuario = get_object_or_404(consulta, pk=usuario_id) if usuario_id else Usuario()
    if empresa is None and usuario.pk and (usuario.email.lower() == CORREO_CONTACTO or usuario.rol_id and usuario.rol.codigo == CONTACTO):
        return redirect('sistema_cuenta_contacto')
    if empresa is None and not request.user.is_superuser and not (propia and usuario.pk == request.user.pk):
        raise PermissionDenied
    opciones = {'alias': alias} if empresa else {'actor': request.user}
    clase = UsuarioEmpresaForm if empresa else CuentaTecnicaForm
    estaba_activo = usuario.activo
    era_admin_empresa = bool(empresa and usuario.pk and usuario.activo and usuario.rol_id and usuario.rol.codigo == 'administrador')
    with usar_empresa(empresa):
        iniciales = {}
        if empresa and es_nueva and request.GET.get('rol') == 'administrador':
            iniciales['rol'] = Rol.objects.using(alias).filter(codigo='administrador', activo=True).first()
        formulario = clase(request.POST or None, instance=usuario, initial=iniciales, **opciones)
        if request.method == 'POST' and formulario.is_valid():
            try:
                with transaction.atomic(using=alias):
                    antes = estado_auditable(consulta.select_for_update(of=('self',)).get(pk=usuario.pk)) if not es_nueva else {}
                    if empresa:
                        Rol.objects.using(alias).select_for_update().filter(codigo='administrador').first()
                        datos = formulario.cleaned_data
                        if era_admin_empresa and (not datos.get('activo') or datos['rol'].codigo != 'administrador') and not (
                                Usuario.objects.using(alias).exclude(pk=usuario.pk).filter(activo=True, rol__codigo='administrador',
                                    rol__activo=True).exclude(password__startswith='!').exclude(password='').exists()):
                            formulario.add_error(None, 'La empresa debe conservar al menos un administrador activo con acceso.')
                            raise ValidationError('Debe conservarse un administrador activo.')
                        auditar_soporte(request, request._atencion_soporte, 'UPDATE', 'Gestión autorizada de una cuenta de empresa')
                    guardado = formulario.save()
                    accion = 'CREATE' if es_nueva else 'UPDATE'
                    if not es_nueva and estaba_activo != guardado.activo:
                        accion = 'REACTIVATE' if guardado.activo else 'DEACTIVATE'
                    detalle = f'Cuenta guardada · {guardado.email}'
                    if empresa is None:
                        detalle += f' · Perfil: {nombre_perfil_personal(guardado)}'
                    auditar_gestion(request, alias, accion, 'Usuario', guardado, detalle,
                        operacion={'CREATE': 'Cuenta creada', 'DEACTIVATE': 'Cuenta desactivada', 'REACTIVATE': 'Cuenta reactivada'}.get(accion, 'Cuenta actualizada'),
                        cambios=diferencias(antes, estado_auditable(guardado)))
            except IntegrityError:
                formulario.add_error(None, 'Ya existe una cuenta con esos datos. Revisa el correo electrónico.')
            except ValidationError:
                pass
            else:
                if empresa is None and guardado.pk == request.user.pk:
                    update_session_auth_hash(request, guardado)
                if propia:
                    destino = reverse('sistema_mi_cuenta')
                elif empresa:
                    destino = reverse('sistema_usuarios') + '?' + urlencode({'empresa': empresa.codigo, **parametros_atencion(request)})
                else:
                    destino = reverse('sistema_cuentas')
                tipo_cuenta = 'Usuario de empresa' if empresa else 'Cuenta del equipo'
                estado = {'CREATE': 'creada', 'DEACTIVATE': 'desactivada', 'REACTIVATE': 'reactivada'}.get(accion, 'actualizada')
                if empresa:
                    estado = {'CREATE': 'creado', 'DEACTIVATE': 'desactivado', 'REACTIVATE': 'reactivado'}.get(accion, 'actualizado')
                mensaje_guardado = f'{guardado.nombre_completo or guardado.email}: cambios guardados correctamente.'
                if empresa and es_nueva:
                    try:
                        enviar_enlace(request, empresa, guardado)
                        mensaje_guardado = 'La cuenta fue creada y se envió una invitación para establecer su contraseña.'
                    except (SMTPException, OSError):
                        mensaje_guardado = 'La cuenta fue creada. No pudimos enviar la invitación; utiliza Enviar recuperación para reintentar.'
                confirmar_guardado(request, alias=alias,
                                   titulo='Mi cuenta actualizada' if propia else f'{tipo_cuenta} {estado}',
                                   mensaje=mensaje_guardado,
                                   link=destino, empresa=empresa)
                return redirect(destino)
        titulo = ('Añadir usuario' if es_nueva else 'Editar usuario') if empresa else (
            'Añadir cuenta del equipo' if es_nueva else 'Editar cuenta del equipo')
        if propia:
            titulo = 'Mi cuenta'
        contexto = contexto_sistema(request, 'mi_cuenta' if propia else 'usuarios' if empresa else 'cuentas', titulo, empresa=empresa)
        volver = reverse('sistema_inicio') if propia else reverse('sistema_cuentas')
        if empresa:
            volver = reverse('sistema_usuarios') + '?' + urlencode({'empresa': empresa.codigo, **parametros_atencion(request)})
        contexto.update(formulario=formulario, volver=volver)
        return render(request, 'sistema/formulario.html', contexto)


@requiere_administrador_plataforma
@require_http_methods(['GET', 'POST'])
def editar_usuario_empresa(request, codigo, usuario_id=None):
    empresa = empresa_del_panel(codigo, request)
    acceso_para(request, empresa, 'gestionar_usuarios')
    return formulario_cuenta(request, empresa, usuario_id)


@requiere_superusuario
@require_http_methods(['GET', 'POST'])
def editar_cuenta_tecnica(request, usuario_id=None):
    return formulario_cuenta(request, None, usuario_id)


@requiere_personal
@require_http_methods(['GET', 'POST'])
def mi_cuenta(request):
    return formulario_cuenta(request, None, request.user.pk, propia=True)


@requiere_personal
@require_http_methods(['GET'])
def auditoria_sistema(request):
    from .auditoria_sistema import listado
    return listado(request)


@requiere_personal
def abrir_configuracion(request):
    if not es_superusuario_smartstock(request.user):
        raise PermissionDenied
    return redirect('sistema_admin:index')


@requiere_personal
@require_http_methods(['GET'])
def diagnostico_sistema(request):
    contexto = contexto_sistema(request, 'diagnostico', 'Diagnóstico de SmartStock')
    # Estado del servicio, sin tokens, destinatarios ni contenido del buzón.
    if es_administrador_plataforma(request.user):
        buzon = BuzonContacto.objects.using('central').only('conexion_estado', 'comprobado_en').first()
        contexto.update(estado_correo=buzon.get_conexion_estado_display() if buzon else 'Pendiente de conexión',
            comprobacion_correo=buzon.comprobado_en if buzon else None,
            sms_activo=bool(getattr(settings, 'SMS_ALERTAS_ACTIVAS', False)))
    contexto['atenciones'] = list(atenciones_visibles(request.user).filter(estado='abierta')[:20])
    return render(request, 'sistema/diagnostico.html', contexto)
