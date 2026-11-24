from django import forms
from django.db.models import Q

from apps.usuarios.models import Usuario
from .autorizacion_soporte import ALCANCES, EXTRAS_GESTION, atenciones_visibles, empresas_visibles
from .forms import FormularioPanel
from .models import AtencionSoporte, Empresa
from .permisos import ADMINISTRADOR_PLATAFORMA, SOPORTE_TECNICO, CORREO_CONTACTO, es_administrador_plataforma


def personal_disponible():
    return Usuario.objects.using('central').filter(activo=True, is_staff=True).exclude(email__iexact=CORREO_CONTACTO).filter(
        Q(is_superuser=True) | Q(rol__codigo__in=[ADMINISTRADOR_PLATAFORMA, SOPORTE_TECNICO], rol__activo=True))


class FiltroAtencionesForm(FormularioPanel, forms.Form):
    search = forms.CharField(label='Buscar por asunto', max_length=160, required=False,
        widget=forms.SearchInput(attrs={'placeholder': 'Ej.: problema para ingresar', 'id': 'buscar-atencion'}))
    empresa = forms.ModelChoiceField(label='Empresa', queryset=Empresa.objects.none(), required=False,
        to_field_name='codigo', empty_label='Todas las empresas', widget=forms.Select(attrs={'id': 'empresa-atencion'}))
    estado = forms.ChoiceField(label='Estado', required=False,
        choices=[('', 'Todas'), ('abierta', 'Abiertas'), ('cerrada', 'Cerradas')],
        widget=forms.Select(attrs={'id': 'estado-atencion'}))

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        if es_administrador_plataforma(actor):
            empresas = empresas_visibles(actor)
        else:
            # El historial propio puede incluir empresas cuya atención ya se cerró.
            # Este filtro no concede acceso a la ficha ni al inventario del cliente.
            empresas = Empresa.objects.using('central').filter(
                pk__in=atenciones_visibles(actor).values('empresa_id'))
        self.fields['empresa'].queryset = empresas.order_by('nombre', 'id')
        self.estilizar()


class AtencionForm(FormularioPanel, forms.ModelForm):
    class Meta:
        model = AtencionSoporte
        fields = ['empresa', 'tecnico', 'asunto', 'motivo']
        widgets = {
            'asunto': forms.TextInput(attrs={'placeholder': 'Ej.: problema para ingresar al sistema'}),
            'motivo': forms.Textarea(attrs={'rows': 5,
                'placeholder': 'Indica qué sucede, desde cuándo y qué estabas intentando hacer.'}),
        }
        labels = {'tecnico': 'Responsable de la atención', 'motivo': 'Descripción de la incidencia'}

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['empresa'].queryset = empresas_visibles(actor).filter(activa=True).order_by('nombre')
        self.fields['empresa'].empty_label = 'Selecciona una empresa'
        self.fields['tecnico'].queryset = personal_disponible().order_by('nombres', 'email')
        self.fields['tecnico'].label_from_instance = lambda u: u.nombre_completo or u.email
        self.fields['tecnico'].empty_label = 'Sin responsable (pendiente de asignación)'
        self.fields['tecnico'].help_text = 'Puedes dejarla sin responsable y asignarla más adelante.'
        if not self.instance._state.adding:
            self.fields['empresa'].disabled = True
        if not es_administrador_plataforma(actor):
            self.fields['tecnico'].queryset = personal_disponible().filter(pk=actor.pk)
            self.initial['tecnico'] = self.fields['tecnico'].initial = actor.pk
            self.fields['tecnico'].disabled = True
            self.fields['tecnico'].help_text = 'La atención quedará asignada a tu cuenta.'
        self.estilizar()


class SolicitudAccesoForm(FormularioPanel, forms.Form):
    alcances = forms.MultipleChoiceField(label='Permisos solicitados', choices=ALCANCES.items(), widget=forms.CheckboxSelectMultiple)
    minutos = forms.TypedChoiceField(label='Duración', choices=[(15, '15 minutos'), (30, '30 minutos'), (60, '60 minutos')], coerce=int, initial=30)
    motivo = forms.CharField(label='Motivo de la consulta', min_length=10, max_length=1000, widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['alcances'].choices = [(k,v) for k,v in ALCANCES.items()
                                          if es_administrador_plataforma(actor) or k not in EXTRAS_GESTION]
        self.estilizar()
        self.fields['alcances'].widget.attrs['class'] = 'ss-soporte-permisos'

    def grupos_permisos(self):
        opciones = {str(opcion.data['value']): opcion for opcion in self['alcances']}
        grupos = [
            ('Inventario', 'Consultas de productos, existencias y operaciones registradas.',
             ('inventario', 'catalogo', 'bodegas', 'movimientos', 'transferencias', 'mermas', 'reportes')),
            ('Usuarios y accesos', 'Distingue la consulta de cuentas de las acciones de recuperación y gestión.',
             ('usuarios', 'recuperar_acceso', 'gestionar_usuarios')),
            ('Diagnóstico', 'Consulta de auditoría y del estado de las alertas.', ('auditoria', 'sms')),
            ('Exportaciones', 'Requiere solicitar también Reportes o Auditoría.', ('exportar',)),
        ]
        return [{'nombre': nombre, 'descripcion': descripcion,
                 'opciones': [opciones[clave] for clave in claves if clave in opciones]}
                for nombre, descripcion, claves in grupos if any(clave in opciones for clave in claves)]

    def clean(self):
        datos = super().clean()
        alcances = datos.get('alcances', [])
        if 'exportar' in alcances and not {'reportes', 'auditoria'}.intersection(alcances):
            self.add_error('alcances', 'Para exportar, solicita también Consultar reportes o Consultar auditoría.')
        if any(k in alcances for k in ('gestionar_usuarios', 'recuperar_acceso')) and 'usuarios' not in alcances:
            self.add_error('alcances', 'Para gestionar o recuperar acceso, solicita también Consultar usuarios.')
        return datos


class ResolucionForm(FormularioPanel, forms.Form):
    resolucion = forms.CharField(label='Resultado de la atención', min_length=10, max_length=2000,
                                widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.estilizar()


class ConsultaClienteForm(FormularioPanel, forms.Form):
    asunto = forms.CharField(label='Asunto', max_length=160)
    motivo = forms.CharField(label='Describe lo que necesitas revisar', min_length=10, max_length=2000,
                            widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.estilizar()


class InvitacionEmpresaForm(FormularioPanel, forms.ModelForm):
    confirmar = forms.BooleanField(label='Confirmé con el contacto principal la habilitación de este administrador.')

    class Meta:
        model = Usuario
        fields = ['nombres', 'apellidos', 'email']

    def __init__(self, *args, empresa, **kwargs):
        self.empresa = empresa
        super().__init__(*args, **kwargs)
        self.initial['email'] = self.fields['email'].initial = empresa.contacto_email
        self.fields['email'].disabled = True
        self.fields['email'].help_text = 'La invitación se envía al contacto principal registrado en la ficha.'
        self.estilizar()

    def clean(self):
        datos = super().clean()
        if not self.empresa.contacto_email or self.empresa.contacto_email.lower() == CORREO_CONTACTO:
            raise forms.ValidationError('Completa un correo de contacto propio de la empresa antes de invitar a su administrador.')
        return datos
