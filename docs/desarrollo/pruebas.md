# Pruebas y comprobaciones

Las pruebas crean sus propias bases desechables y simulan proveedores externos. No requieren contraseñas de Neon ni envían SMS o correos reales. La ejecución normal de la aplicación sigue utilizando las bases de Neon que tenga configuradas.

## Dónde están las suites

| Ruta | Comprobaciones |
| --- | --- |
| apps/core/test_*.py | Auditoría y comportamiento compartido de las pantallas. |
| apps/productos/test_*.py | API, permisos, stock, movimientos, mermas, bodegas, ubicaciones y reportes. |
| apps/usuarios/test_*.py | Cuentas, roles, permisos, autenticación y recuperación. |
| esquema_multiempresa/pruebas_*.py | Separación de empresas, login central, panel interno, soporte y contacto. |
| apps/core/selenium_suite.py y esquema_multiempresa/selenium_suite.py | Recorridos completos en Chrome. |
| tests/js | Comportamiento de la interfaz con respuestas HTTP controladas. |
| tests/desktop | Página de prueba que usa el ejecutable en Windows. |

## Django sin conexión a Neon

Desde CMD, con el entorno virtual activado y requirements-web.txt instalado:

~~~bat
set "SS_TEST_POSTGRES="
python manage.py check --settings=esquema_multiempresa.testing
python manage.py makemigrations --check --dry-run --settings=esquema_multiempresa.testing
python manage.py test --settings=config.settings.testing --verbosity 2
python manage.py test esquema_multiempresa.pruebas_web esquema_multiempresa.pruebas_login esquema_multiempresa.pruebas_sistema esquema_multiempresa.pruebas_contacto esquema_multiempresa.pruebas_soporte --settings=esquema_multiempresa.testing --verbosity 2
~~~

Con SS_TEST_POSTGRES desactivado, estos perfiles usan SQLite desechable únicamente para QA. Esta opción permite revisar el proyecto sin acceso a los datos de las empresas.

Para validar bloqueos, restricciones y concurrencia utiliza PostgreSQL aislado. Las variables SS_TEST_DB_USER, SS_TEST_DB_PASSWORD, SS_TEST_DB_HOST y SS_TEST_DB_PORT y el indicador SS_TEST_POSTGRES=true se describen en [Integridad del stock](integridad-stock.md). GitHub Actions prepara PostgreSQL 16 para esas comprobaciones.

## JavaScript

Instala Node.js 20 o posterior y ejecuta desde la raíz:

~~~bat
npm --prefix tests/js ci
npm --prefix tests/js test
~~~

El [README de la suite JavaScript](../../tests/js/README.md) explica su cobertura y las diferencias respecto de una revisión visual.

## Navegador

Con Chrome instalado:

~~~bat
python -m pip install selenium==4.52.0
set "SS_TEST_POSTGRES="
python manage.py test apps.core.selenium_suite --settings=config.settings.testing --verbosity 2
python manage.py test esquema_multiempresa.selenium_suite --settings=esquema_multiempresa.testing --verbosity 2
~~~

## GitHub Actions

| Flujo | Resultado esperado |
| --- | --- |
| tests-postgres.yml | Configuración válida, migraciones coherentes y suites Django sobre PostgreSQL. |
| tests-selenium.yml | Navegación, permisos y pantallas en Chrome con datos desechables. |
| desktop-windows.yml | Compilación y arranque del ejecutable con WebView2. |

Los resultados vigentes se consultan en [Actions](https://github.com/jadelgad0s/SmartStock-multiempresa/actions). Los flujos tienen filtros por rutas: una modificación exclusivamente documental puede no ejecutar todas las suites.

No se debe usar el perfil web ni el de migración para ejecutar pruebas sobre una base operativa.
