"""El administrador del cliente decide los permisos sobre su propia empresa."""
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Case, Count, Exists, IntegerField, OuterRef, Prefetch, Q, Value, When
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from apps.usuarios.navegacion import datos_navegacion

from .autorizacion_soporte import auditar_soporte, usuario_empresa_administrador
from .forms_soporte import ConsultaClienteForm, personal_disponible
from .models import AtencionSoporte, AccesoSoporte, NotificacionSistema
from .soporte_operaciones import decidir_acceso, revocar_accesos
from .presentacion_soporte import situacion_atencion


@never_cache
@require_http_methods(['GET', 'POST'])
def soporte_empresa(request):
    if not request.user.is_authenticated:
        return redirect('login_page')
    if not usuario_empresa_administrador(request):
        raise PermissionDenied('Solo el administrador de esta empresa puede decidir los accesos de soporte.')
    request.navegacion_verificada = datos_navegacion(request.user)
    formulario = ConsultaClienteForm(request.POST if request.POST.get('accion') == 'nueva' else None)
    error = ''
    if request.method == 'POST':
        try:
            accion = request.POST.get('accion')
            if accion == 'nueva' and formulario.is_valid():
                atencion = AtencionSoporte.objects.using('central').create(empresa=request.empresa, **formulario.cleaned_data)
                auditar_soporte(request, atencion, 'CREATE', 'Consulta del cliente: ' + atencion.motivo)
                for gestor in personal_disponible().filter(is_superuser=True) | personal_disponible().filter(rol__codigo='administrador_plataforma'):
                    NotificacionSistema.objects.using('central').create(destinatario=gestor, titulo='Nueva consulta de empresa',
                        mensaje=atencion.asunto, empresa_nombre=request.empresa.nombre,
                        link=f'/sistema/atenciones/{atencion.pk}/')
                messages.success(request, 'Tu consulta quedó registrada para el equipo de SmartStock.')
            elif accion in ('aprobar', 'rechazar', 'revocar'):
                acceso = decidir_acceso(request, request.POST.get('acceso'), accion)
                messages.success(request, 'Permiso autorizado hasta ' + timezone.localtime(acceso.expira_en).strftime('%H:%M')
                    if accion == 'aprobar' else 'La decisión quedó registrada y el acceso ya no está habilitado.')
            elif accion == 'cerrar':
                with transaction.atomic(using='central'):
                    atencion = get_object_or_404(AtencionSoporte.objects.using('central').select_for_update(),
                        pk=request.POST.get('atencion'), empresa=request.empresa)
                    atencion.estado, atencion.cerrada_en = 'cerrada', timezone.now()
                    atencion.resolucion = 'Atención finalizada por el administrador de la empresa.'
                    atencion.save(using='central')
                    revocar_accesos(atencion)
                    auditar_soporte(request, atencion, 'UPDATE', atencion.resolucion)
                messages.success(request, 'La atención fue cerrada y sus accesos fueron revocados.')
            else:
                accion = None
            if accion:
                return redirect('soporte_empresa')
        except (ValidationError, ValueError, TypeError) as e:
            error = ' '.join(e.messages) if isinstance(e, ValidationError) else 'Revisa la solicitud seleccionada.'
    consulta = AtencionSoporte.objects.using('central').filter(empresa=request.empresa).annotate(
        tiene_pendiente=Exists(AccesoSoporte.objects.using('central').filter(
            atencion_id=OuterRef('pk'), estado='pendiente', atencion__estado='abierta')),
        orden_estado=Case(When(estado='abierta', then=Value(0)), default=Value(1), output_field=IntegerField()))
    resumen = consulta.aggregate(pendientes=Count('pk', filter=Q(tiene_pendiente=True)),
        abiertas=Count('pk', filter=Q(estado='abierta')), cerradas=Count('pk', filter=Q(estado='cerrada')))
    atenciones = list(consulta.select_related('empresa', 'tecnico', 'tecnico__rol').prefetch_related(
        Prefetch('accesos', queryset=AccesoSoporte.objects.using('central').select_related('tecnico')))
        .order_by('-tiene_pendiente', 'orden_estado', '-creada_en', '-pk')[:50])
    for atencion in atenciones:
        atencion.situacion = situacion_atencion(atencion, atencion.accesos.all())
    return render(request, 'soporte/empresa.html', {'formulario': formulario, 'atenciones': atenciones,
        'atenciones_pendientes': [a for a in atenciones if a.tiene_pendiente],
        'otras_atenciones': [a for a in atenciones if not a.tiene_pendiente],
        'hay_mas_atenciones': resumen['abiertas'] + resumen['cerradas'] > len(atenciones),
        'resumen_soporte': resumen, 'error_consulta': error})
