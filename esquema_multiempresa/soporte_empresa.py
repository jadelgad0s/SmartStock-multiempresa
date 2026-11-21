"""El administrador del cliente decide los permisos sobre su propia empresa."""
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .autorizacion_soporte import auditar_soporte, usuario_empresa_administrador
from .forms_soporte import ConsultaClienteForm, personal_disponible
from .models import AtencionSoporte, AccesoSoporte, NotificacionSistema
from .soporte_operaciones import decidir_acceso, revocar_accesos


@never_cache
@require_http_methods(['GET', 'POST'])
def soporte_empresa(request):
    if not request.user.is_authenticated:
        return redirect('login_page')
    if not usuario_empresa_administrador(request):
        raise PermissionDenied('Solo el administrador de esta empresa puede decidir los accesos de soporte.')
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
    atenciones = list(AtencionSoporte.objects.using('central').filter(empresa=request.empresa).select_related('tecnico').prefetch_related(
        Prefetch('accesos', queryset=AccesoSoporte.objects.using('central').select_related('tecnico')))[:50])
    return render(request, 'soporte/empresa.html', {'formulario': formulario, 'atenciones': atenciones, 'error_consulta': error})
