import re
from functools import wraps

from django import forms
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.contrib.admin.utils import NestedObjects
from django.core.exceptions import PermissionDenied
from django.db import connections, transaction
from django.db.models.deletion import ProtectedError
from django.shortcuts import redirect
from django.utils.text import slugify

from apps.usuarios.admin_site import SmartStockAdminSite
from apps.usuarios.models import Usuario
from .models import Empresa
from .permisos import es_superusuario_smartstock
from .validadores import normalizar_rut


class AdministracionSistema(SmartStockAdminSite):
    site_header = 'Administración de SmartStock'
    site_title = 'SmartStock'
    index_title = 'Configuración de SmartStock'
    site_url = '/sistema/'

    def has_permission(self, request):
        return es_superusuario_smartstock(request.user)

    def admin_view(self, view, cacheable=False):
        vista = super().admin_view(view, cacheable=cacheable)

        @wraps(view)
        def protegida(request, *args, **kwargs):
            if request.user.is_authenticated and not self.has_permission(request):
                raise PermissionDenied
            return vista(request, *args, **kwargs)
        return protegida

    def login(self, request, extra_context=None):
        if self.has_permission(request):
            return redirect('sistema_admin:index')
        if request.user.is_authenticated:
            raise PermissionDenied
        return redirect('login_page')


sitio_sistema = AdministracionSistema(name='sistema_admin')


class EmpresaForm(forms.ModelForm):
    class Meta:
        model = Empresa
        fields = ('nombre', 'razon_social', 'rut', 'rubro', 'contacto_nombre', 'contacto_email',
                  'contacto_telefono', 'direccion', 'comuna', 'region', 'codigo', 'alias_bd', 'activa')
        labels = {'nombre': 'Nombre comercial', 'activa': 'Empresa activa'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['codigo'].required = False
        ocupadas = set(Empresa.objects.using('central').exclude(pk=self.instance.pk).values_list('alias_bd', flat=True))
        self.bases_disponibles = [alias for alias in settings.BASES_EMPRESA if alias not in ocupadas]
        self.fields['alias_bd'].widget = forms.Select(choices=[('', 'Selecciona una base disponible'), *[
            (alias, alias) for alias in self.bases_disponibles
        ]])
        self.fields['alias_bd'].disabled = not self.instance._state.adding

    def clean_rut(self):
        rut = normalizar_rut(self.cleaned_data.get('rut', ''))
        if rut and Empresa.objects.using('central').exclude(pk=self.instance.pk).filter(rut=rut).exists():
            raise forms.ValidationError('Ya hay una empresa registrada con este RUT.')
        return rut

    def clean_codigo(self):
        codigo = self.cleaned_data.get('codigo', '')
        if not codigo:
            if not self.instance._state.adding:
                return self.instance.codigo
            base = slugify(self.cleaned_data.get('nombre', ''))[:54] or 'empresa'
            if base == 'nueva':
                base = 'empresa-nueva'
            codigo = base
            numero = 2
            while Empresa.objects.using('central').filter(codigo=codigo).exists():
                codigo = f'{base}-{numero}'
                numero += 1
        if codigo == 'nueva':
            raise forms.ValidationError('Este código está reservado. Usa otro identificador para la empresa.')
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,58}[a-z0-9])?', codigo):
            raise forms.ValidationError('Usa letras minúsculas, números y guiones entre palabras.')
        return codigo

    def clean_alias_bd(self):
        alias = self.cleaned_data['alias_bd']
        if alias not in settings.BASES_EMPRESA:
            raise forms.ValidationError('Selecciona una base de empresa configurada en este servidor.')
        if Empresa.objects.using('central').exclude(pk=self.instance.pk).filter(alias_bd=alias).exists():
            raise forms.ValidationError('Esta base ya está asignada a otra empresa. Selecciona una disponible.')
        return alias


@admin.register(Empresa, site=sitio_sistema)
class EmpresaAdmin(admin.ModelAdmin):
    form = EmpresaForm
    list_display = ('nombre', 'rut', 'codigo', 'activa')
    list_filter = ('activa',)
    search_fields = ('nombre', 'razon_social', 'rut', 'codigo', 'contacto_email')
    ordering = ('nombre',)
    readonly_fields = ('creada_en', 'actualizada_en')


class NuevaCuentaTecnica(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = Usuario
        fields = ('email', 'nombres', 'apellidos', 'is_superuser')


class EditarCuentaTecnica(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = Usuario
        fields = ('email', 'password', 'nombres', 'apellidos', 'activo', 'is_superuser')


class RecolectorCuentasCentrales(NestedObjects):
    """Recorre las relaciones que existen en la base central."""

    def __init__(self):
        super().__init__(using='central')
        self.tablas = set(connections['central'].introspection.table_names())

    def related_objects(self, related_model, related_fields, objs):
        # Los modelos operativos están registrados, pero sus tablas solo
        # existen en las bases de las empresas.
        if related_model._meta.db_table not in self.tablas:
            return related_model._base_manager.using('central').none()
        return super().related_objects(related_model, related_fields, objs)


@admin.register(Usuario, site=sitio_sistema)
class CuentaTecnicaAdmin(UserAdmin):
    add_form = NuevaCuentaTecnica
    form = EditarCuentaTecnica
    list_display = ('email', 'nombre_completo', 'activo')
    list_filter = ('activo',)
    search_fields = ('email', 'nombres', 'apellidos')
    ordering = ('email',)
    filter_horizontal = ()
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Cuenta técnica', {'fields': ('nombres', 'apellidos', 'activo', 'is_superuser')}),
    )
    add_fieldsets = ((None, {'fields': ('email', 'nombres', 'apellidos', 'password1', 'password2', 'is_superuser')}),)

    def get_queryset(self, request):
        return super().get_queryset(request).using('central').filter(is_staff=True)

    def save_model(self, request, obj, form, change):
        obj.is_staff = True
        obj.rol = None
        super().save_model(request, obj, form, change)

    def get_deleted_objects(self, objs, request):
        recolector = RecolectorCuentasCentrales()
        recolector.collect(objs)
        formato = lambda obj: f'{obj._meta.verbose_name}: {obj}'
        cantidades = {
            modelo._meta.verbose_name_plural: len(instancias)
            for modelo, instancias in recolector.model_objs.items()
        }
        # Este sitio exige un superusuario central antes de llegar a la vista.
        return (recolector.nested(formato), cantidades, set(),
                [formato(obj) for obj in recolector.protected])

    def delete_model(self, request, obj):
        self.delete_queryset(request, self.model._base_manager.filter(pk=obj.pk))

    def delete_queryset(self, request, queryset):
        with transaction.atomic(using='central'):
            recolector = RecolectorCuentasCentrales()
            recolector.collect(queryset.using('central').filter(is_staff=True))
            if recolector.protected:
                raise ProtectedError('La cuenta tiene registros protegidos.', recolector.protected)
            recolector.delete()
