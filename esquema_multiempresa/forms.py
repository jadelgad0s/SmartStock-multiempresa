from django import forms
from django.contrib.auth.password_validation import validate_password
from django.db.models import Q

from apps.productos.models import Bodega, Producto
from apps.productos.reportes import TITULOS
from apps.usuarios.models import Rol, Usuario
from .admin_central import EmpresaForm


class FormularioPanel:
    def estilizar(self):
        for campo in self.fields.values():
            if isinstance(campo.widget, forms.CheckboxInput):
                campo.widget.attrs['class'] = 'form-check-input'
            elif isinstance(campo.widget, forms.Select):
                campo.widget.attrs['class'] = 'form-select'
            else:
                campo.widget.attrs['class'] = 'form-control'


class EmpresaPanelForm(FormularioPanel, EmpresaForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['alias_bd'].label = 'Base preparada para la empresa'
        self.fields['alias_bd'].help_text = 'Cada empresa utiliza una base exclusiva. Se muestran las disponibles.'
        self.fields['codigo'].help_text = 'Déjalo vacío para generarlo a partir del nombre. Identifica la dirección de acceso.'
        self.fields['rut'].widget = forms.TextInput(attrs={'placeholder': '12.345.678-5', 'maxlength': 15})
        # Los registros anteriores pueden completar su ficha gradualmente.
        if self.instance._state.adding:
            for nombre in ('razon_social', 'rut', 'rubro', 'contacto_nombre', 'contacto_email'):
                self.fields[nombre].required = True
        self.fields['contacto_nombre'].widget.attrs['autocomplete'] = 'name'
        self.fields['contacto_email'].widget.attrs['autocomplete'] = 'email'
        self.fields['contacto_telefono'].widget = forms.TextInput(attrs={'type': 'tel', 'autocomplete': 'tel'})
        self.fields['direccion'].widget.attrs['autocomplete'] = 'street-address'
        self.fields['activa'].help_text = 'Habilita el acceso de las cuentas de esta empresa. Su configuración se revisa por separado.'
        self.estilizar()

    def secciones(self):
        return [
            ('Identificación de la empresa', 'Datos que identifican al cliente de SmartStock.',
             [self[nombre] for nombre in ('nombre', 'razon_social', 'rut', 'rubro')]),
            ('Contacto principal', 'Persona con quien coordinar la habilitación y el soporte del servicio.',
             [self[nombre] for nombre in ('contacto_nombre', 'contacto_email', 'contacto_telefono')]),
            ('Dirección de contacto', 'Opcional. Las direcciones de las bodegas se registran en su propio módulo.',
             [self[nombre] for nombre in ('direccion', 'comuna', 'region')]),
            ('Acceso a SmartStock', 'Asigna la base preparada y revisa el acceso de la empresa.',
             [self[nombre] for nombre in ('codigo', 'alias_bd', 'activa')]),
        ]


class CuentaPanelForm(FormularioPanel, forms.ModelForm):
    password1 = forms.CharField(label='Contraseña', max_length=4096, strip=False, widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}), required=False)
    password2 = forms.CharField(label='Repetir contraseña', max_length=4096, strip=False, widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}), required=False)

    class Meta:
        model = Usuario
        fields = ('email', 'nombres', 'apellidos', 'telefono', 'activo')
        labels = {'email': 'Correo electrónico', 'activo': 'Cuenta activa'}

    def __init__(self, *args, alias, **kwargs):
        self.alias = alias
        super().__init__(*args, **kwargs)
        nueva = self.instance._state.adding
        self.fields['password1'].required = self.fields['password2'].required = nueva
        if not nueva:
            self.fields['password1'].help_text = 'Completa ambos campos para cambiar la contraseña.'
        self.fields['email'].widget.attrs['autocomplete'] = 'email'
        self.estilizar()

    def clean_email(self):
        correo = self.cleaned_data['email'].strip().lower()
        existentes = Usuario.objects.using(self.alias).filter(email__iexact=correo)
        if self.instance.pk:
            existentes = existentes.exclude(pk=self.instance.pk)
        if existentes.exists():
            raise forms.ValidationError('Ya existe una cuenta con este correo.')
        return correo

    def clean(self):
        datos = super().clean()
        clave, confirmacion = datos.get('password1'), datos.get('password2')
        if clave != confirmacion:
            self.add_error('password2', 'Las contraseñas deben coincidir.')
        if clave:
            candidato = Usuario(**{campo: datos.get(campo, '') for campo in ('email', 'nombres', 'apellidos')})
            try:
                validate_password(clave, user=candidato)
            except forms.ValidationError as error:
                self.add_error('password1', error)
        return datos

    def save(self, commit=True):
        usuario = super().save(commit=False)
        if self.cleaned_data.get('password1'):
            usuario.set_password(self.cleaned_data['password1'])
        if commit:
            usuario.save(using=self.alias)
        return usuario


class UsuarioEmpresaForm(CuentaPanelForm):
    class Meta(CuentaPanelForm.Meta):
        fields = (*CuentaPanelForm.Meta.fields, 'rol')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['rol'].required = True
        self.fields['rol'].queryset = Rol.objects.using(self.alias).filter(
            Q(activo=True) | Q(pk=self.instance.rol_id),
        ).order_by('nombre')
        self.fields['rol'].label_from_instance = lambda rol: rol.nombre
        self.order_fields(('nombres', 'apellidos', 'email', 'telefono', 'rol', 'activo', 'password1', 'password2'))


class CuentaTecnicaForm(CuentaPanelForm):
    perfil = forms.ChoiceField(label='Perfil de acceso', choices=(('tecnico', 'Técnico de SmartStock'), ('superusuario', 'Superusuario')))

    def __init__(self, *args, actor, **kwargs):
        self.actor = actor
        super().__init__(*args, alias='central', **kwargs)
        self.initial['perfil'] = 'superusuario' if self.instance.is_superuser else 'tecnico'
        if not actor.is_superuser:
            del self.fields['perfil']
        if self.instance.pk == actor.pk:
            self.fields['activo'].disabled = True
            if 'perfil' in self.fields:
                self.fields['perfil'].disabled = True
        self.order_fields(('nombres', 'apellidos', 'email', 'telefono', 'perfil', 'activo', 'password1', 'password2'))
        self.estilizar()

    def save(self, commit=True):
        usuario = super().save(commit=False)
        usuario.is_staff = True
        usuario.rol = None
        if self.actor.is_superuser:
            usuario.is_superuser = self.cleaned_data['perfil'] == 'superusuario'
        if commit:
            usuario.save(using='central')
        return usuario


class ConsultaInventarioForm(FormularioPanel, forms.Form):
    search = forms.CharField(label='Buscar', max_length=200, required=False)
    bodega = forms.ModelChoiceField(label='Bodega', queryset=Bodega.objects.none(), required=False, empty_label='Todas las bodegas')
    desde = forms.DateField(label='Desde', required=False, widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))
    hasta = forms.DateField(label='Hasta', required=False, widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))
    informe = forms.ChoiceField(label='Reporte', choices=TITULOS.items(), required=False)
    producto = forms.ModelChoiceField(label='Producto para Kardex', queryset=Producto.objects.none(), required=False, empty_label='Selecciona un producto')

    def __init__(self, *args, alias, reporte=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['bodega'].queryset = Bodega.objects.using(alias).order_by('nombre', 'id')
        self.fields['bodega'].label_from_instance = lambda bodega: bodega.nombre
        self.fields['producto'].queryset = Producto.objects.using(alias).order_by('nombre', 'id')
        self.fields['producto'].label_from_instance = lambda producto: f'{producto.sku} · {producto.nombre}'
        if not reporte:
            del self.fields['informe']
            del self.fields['producto']
        self.estilizar()

    def clean(self):
        datos = super().clean()
        if datos.get('desde') and datos.get('hasta') and datos['desde'] > datos['hasta']:
            raise forms.ValidationError('La fecha inicial debe ser anterior o igual a la final.')
        if datos.get('hasta') and datos['hasta'].year == 9999:
            self.add_error('hasta', 'Selecciona una fecha anterior al año 9999.')
        return datos
