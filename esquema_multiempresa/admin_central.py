import json
import re
from copy import deepcopy
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
from apps.usuarios.models import Rol, Usuario
from .models import Empresa
from .permisos import ADMINISTRADOR_PLATAFORMA, SOPORTE_TECNICO, es_superusuario_smartstock, nombre_perfil_personal
from .validadores import normalizar_rut
from .territorio import normalizar_comuna, normalizar_region, regiones_chile


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
    region = forms.ChoiceField(label='Región', required=False)
    comuna = forms.ChoiceField(label='Comuna', required=False)

    class Meta:
        model = Empresa
        fields = ('nombre', 'razon_social', 'rut', 'rubro', 'contacto_nombre', 'contacto_apellidos', 'contacto_email',
                  'contacto_telefono', 'direccion', 'comuna', 'region', 'codigo', 'alias_bd', 'activa')
        labels = {'nombre': 'Nombre comercial', 'activa': 'Empresa activa'}

    class Media:
        js = ('js/empresa_direccion.js',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.preparar_direccion()
        self.fields['codigo'].required = False
        ocupadas = set(Empresa.objects.using('central').exclude(pk=self.instance.pk).values_list('alias_bd', flat=True))
        self.bases_disponibles = [alias for alias in settings.BASES_EMPRESA if alias not in ocupadas]
        self.fields['alias_bd'].widget = forms.Select(choices=[('', 'Selecciona una base disponible'), *[
            (alias, alias) for alias in self.bases_disponibles
        ]])
        self.fields['alias_bd'].disabled = not self.instance._state.adding

    def preparar_direccion(self):
        regiones = deepcopy(regiones_chile())
        region_anterior = normalizar_region(self.instance.region) or self.instance.region.strip()
        comuna_anterior = normalizar_comuna(self.instance.comuna, region_anterior) or self.instance.comuna.strip()
        region_valida = next((region for region in regiones if region['nombre'] == region_anterior), None)
        self.direccion_anterior = False
        if self.instance.pk and (region_anterior or comuna_anterior):
            if region_valida is None:
                region_valida = {'nombre': region_anterior, 'anterior': True, 'comunas': []}
                regiones.append(region_valida)
                self.direccion_anterior = True
            if comuna_anterior and not any(comuna['nombre'] == comuna_anterior for comuna in region_valida['comunas']):
                region_valida['comunas'].append({'nombre': comuna_anterior, 'anterior': True})
                self.direccion_anterior = True
        self.initial.update(region=region_anterior, comuna=comuna_anterior)
        if self.is_bound:
            self.data = self.data.copy()
            region_clave, comuna_clave = self.add_prefix('region'), self.add_prefix('comuna')
            region = normalizar_region(self.data.get(region_clave)) or self.data.get(region_clave, '').strip()
            comuna = normalizar_comuna(self.data.get(comuna_clave), region) or self.data.get(comuna_clave, '').strip()
            self.data[region_clave], self.data[comuna_clave] = region, comuna
        else:
            region = region_anterior
        seleccionada = next((item for item in regiones if item['nombre'] == region), None)
        self.fields['region'].choices = [('', 'Selecciona una región'), *[
            (item['nombre'], item['nombre'] + (' (valor anterior)' if item.get('anterior') else ''))
            for item in regiones if item['nombre']
        ]]
        self.fields['comuna'].choices = [('', 'Selecciona una comuna'), *[
            (item['nombre'], item['nombre'] + (' (valor anterior)' if item.get('anterior') else ''))
            for item in (seleccionada['comunas'] if seleccionada else [])
        ]]
        self.fields['region'].widget.attrs.update({
            'data-ss-regiones-comunas': json.dumps(regiones, ensure_ascii=False, separators=(',', ':')),
            'data-ss-comuna-nombre': self.add_prefix('comuna'), 'autocomplete': 'address-level1',
        })
        self.fields['comuna'].widget.attrs['autocomplete'] = 'address-level2'
        self.fields['comuna'].help_text = 'Selecciona una región para ver sus comunas.'
        if self.direccion_anterior:
            self.fields['region'].help_text = 'Se conserva un valor anterior. Selecciona la región y comuna del listado para actualizarlo.'

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

    def save_model(self, request, obj, form, change):
        with transaction.atomic(using='central'):
            super().save_model(request, obj, form, change)
            if not obj.activa:
                from .models import AccesoSoporte
                AccesoSoporte.objects.using('central').filter(atencion__empresa=obj,
                    estado__in=['pendiente', 'aprobado']).update(estado='revocado')


class PerfilCuentaCentralForm:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['rol'].queryset = Rol.objects.using('central').filter(
            codigo__in=(ADMINISTRADOR_PLATAFORMA, SOPORTE_TECNICO),
        )
        self.fields['rol'].label = 'Perfil del equipo'
        self.fields['rol'].label_from_instance = lambda rol: rol.nombre
        self.fields['rol'].help_text = 'Selecciona Administrador de plataforma o Soporte técnico para una cuenta sin superusuario.'

    def clean(self):
        datos = super().clean()
        from .permisos import CONTACTO, CORREO_CONTACTO
        if (datos.get('email', '').lower() == CORREO_CONTACTO
                or self.instance.rol_id and self.instance.rol.codigo == CONTACTO):
            self.add_error(None, 'La cuenta de contacto se gestiona únicamente en /sistema/contacto/cuenta/.')
        if datos.get('is_superuser'):
            datos['rol'] = None
        elif datos.get('rol') is None:
            self.add_error('rol', 'Selecciona un perfil para la cuenta del equipo.')
        return datos


class NuevaCuentaTecnica(PerfilCuentaCentralForm, UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = Usuario
        fields = ('email', 'nombres', 'apellidos', 'is_superuser', 'rol')


class EditarCuentaTecnica(PerfilCuentaCentralForm, UserChangeForm):
    class Meta(UserChangeForm.Meta):
        model = Usuario
        fields = ('email', 'password', 'nombres', 'apellidos', 'activo', 'is_superuser', 'rol')


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
    list_display = ('email', 'nombre_completo', 'perfil_del_equipo', 'activo')
    list_filter = ('activo',)
    search_fields = ('email', 'nombres', 'apellidos')
    ordering = ('email',)
    filter_horizontal = ()
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Cuenta del equipo', {'fields': ('nombres', 'apellidos', 'activo', 'is_superuser', 'rol')}),
    )
    add_fieldsets = ((None, {'fields': ('email', 'nombres', 'apellidos', 'password1', 'password2', 'is_superuser', 'rol')}),)

    @admin.display(description='Perfil del equipo')
    def perfil_del_equipo(self, obj):
        return nombre_perfil_personal(obj)

    def get_queryset(self, request):
        return super().get_queryset(request).using('central').filter(is_staff=True)

    def save_model(self, request, obj, form, change):
        obj.is_staff = True
        if obj.is_superuser:
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
