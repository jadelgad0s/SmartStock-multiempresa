import re
from functools import wraps

from django import forms
from django.conf import settings
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from apps.usuarios.admin_site import SmartStockAdminSite
from apps.usuarios.models import Usuario
from .models import Empresa
from .permisos import es_superusuario_smartstock


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
        fields = ('nombre', 'codigo', 'alias_bd', 'activa')

    def clean_codigo(self):
        codigo = self.cleaned_data['codigo']
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,58}[a-z0-9])?', codigo):
            raise forms.ValidationError('Usa letras minúsculas, números y guiones entre palabras.')
        return codigo

    def clean_alias_bd(self):
        alias = self.cleaned_data['alias_bd']
        if alias not in settings.BASES_EMPRESA:
            raise forms.ValidationError('Selecciona una base de empresa configurada en este servidor.')
        return alias


@admin.register(Empresa, site=sitio_sistema)
class EmpresaAdmin(admin.ModelAdmin):
    form = EmpresaForm
    list_display = ('nombre', 'codigo', 'activa')
    list_filter = ('activa',)
    search_fields = ('nombre', 'codigo')
    ordering = ('nombre',)


class NuevaCuentaTecnica(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = Usuario
        fields = ('email', 'nombres', 'apellidos', 'is_superuser')


class EditarCuentaTecnica(UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = Usuario
        fields = ('email', 'password', 'nombres', 'apellidos', 'activo', 'is_superuser')


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
        return super().get_queryset(request).filter(is_staff=True)

    def save_model(self, request, obj, form, change):
        obj.is_staff = True
        obj.rol = None
        super().save_model(request, obj, form, change)
