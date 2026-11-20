from django import forms

from .forms import FormularioPanel
from .models import MensajeContacto


class SeguimientoForm(FormularioPanel, forms.ModelForm):
    version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)

    class Meta:
        model = MensajeContacto
        fields = ('estado', 'categoria', 'seguimiento')
        labels = {'categoria': 'Tipo de consulta', 'seguimiento': 'Próximo seguimiento (opcional)'}
        widgets = {'seguimiento': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial['version'] = self.instance.version
        self.estilizar()


class NotaForm(FormularioPanel, forms.Form):
    texto = forms.CharField(label='Nota interna', max_length=4000, widget=forms.Textarea(attrs={'rows': 3}),
                            help_text='Solo se guarda en SmartStock; no se envía por correo.')

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('auto_id', 'nota_%s')
        super().__init__(*args, **kwargs)
        self.estilizar()


class BorradorForm(FormularioPanel, forms.Form):
    texto = forms.CharField(label='Respuesta', max_length=20000, widget=forms.Textarea(attrs={'rows': 7}),
                            help_text='Guarda y revisa el borrador antes de enviarlo.')
    version = forms.IntegerField(min_value=0, widget=forms.HiddenInput)
    borrador = forms.UUIDField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('auto_id', 'borrador_%s')
        super().__init__(*args, **kwargs)
        self.estilizar()
