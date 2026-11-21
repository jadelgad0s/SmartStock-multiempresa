from django import forms
from django.db.models import Q

from apps.usuarios.models import Usuario
from .autorizacion_soporte import ALCANCES, EXTRAS_GESTION, empresas_visibles
from .forms import FormularioPanel
from .models import AtencionSoporte
from .permisos import ADMINISTRADOR_PLATAFORMA, SOPORTE_TECNICO, CORREO_CONTACTO, es_administrador_plataforma


def personal_disponible():
    return Usuario.objects.using('central').filter(activo=True, is_staff=True).exclude(email__iexact=CORREO_CONTACTO).filter(
        Q(is_superuser=True) | Q(rol__codigo__in=[ADMINISTRADOR_PLATAFORMA, SOPORTE_TECNICO], rol__activo=True))


class AtencionForm(FormularioPanel, forms.ModelForm):
    class Meta:
        model = AtencionSoporte
        fields = ['empresa', 'tecnico', 'asunto', 'motivo']
        widgets = {'motivo': forms.Textarea(attrs={'rows': 4})}
        labels = {'tecnico': 'Responsable de la atención', 'motivo': 'Descripción de la incidencia'}

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['empresa'].queryset = empresas_visibles(actor).filter(activa=True).order_by('nombre')
        self.fields['tecnico'].queryset = personal_disponible().order_by('nombres', 'email')
        self.fields['tecnico'].label_from_instance = lambda u: u.nombre_completo or u.email
        if not self.instance._state.adding:
            self.fields['empresa'].disabled = True
        if not es_administrador_plataforma(actor):
            self.fields['tecnico'].queryset = personal_disponible().filter(pk=actor.pk)
            self.initial['tecnico'] = self.fields['tecnico'].initial = actor.pk
            self.fields['tecnico'].disabled = True
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

    def clean(self):
        datos = super().clean()
        alcances = datos.get('alcances', [])
        if 'exportar' in alcances and 'reportes' not in alcances:
            self.add_error('alcances', 'Para exportar, solicita también Consultar reportes.')
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
