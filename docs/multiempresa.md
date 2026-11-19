# Probar SmartStock con dos empresas

Este perfil levanta una instancia local de Django con un inicio de sesión común. El correo y la contraseña permiten acceder a la empresa correspondiente. La base central guarda el directorio de empresas, las cuentas técnicas y sus sesiones. Cada empresa dispone de su propia base PostgreSQL con sus usuarios, roles, sesiones, productos, bodegas, movimientos y auditoría.

| Empresa | Código de acceso | Alias de Django | Base en Neon |
| --- | --- | --- | --- |
| Directorio de SmartStock | | `central` | `smartstock_central` |
| Ferretería La Fragua | `la-fragua` | `ferreteria` | `ferreteria_la_fragua` |
| Repuestos Punto Motor | `punto-motor` | `repuestos` | `repuestos_punto_motor` |

## Preparación en Windows

Abre CMD en la carpeta del nuevo clon, junto a `manage.py`. Si tienes activo el entorno del proyecto anterior, ejecuta `deactivate`. El proyecto usa Python 3.13.7. Comprueba la versión y prepara un entorno propio del clon.

```bat
py -3.13 --version
if not exist ".venv\Scripts\python.exe" py -3.13 -m venv .venv
call .venv\Scripts\activate.bat
python -c "import sys; print(sys.executable)"
python -m pip install -r requirements-web.txt
```

La ruta de Python debe terminar en `SmartStock-multiempresa\.venv\Scripts\python.exe`.

Django lee su clave local de `.env`. Desde la carpeta de `manage.py`, el siguiente comando agrega una clave aleatoria si falta la línea `SECRET_KEY=` con un valor. Conserva el resto del archivo y guarda la clave directamente en disco.

```bat
findstr /R /C:"^SECRET_KEY=." ".env" >nul 2>nul || python -c "import secrets; print('\nSECRET_KEY=' + secrets.token_urlsafe(64))" >> ".env"
```

El segundo archivo privado, `.env.multiempresa.local`, contiene `SS_PRUEBAS_CENTRAL_URL` con la URL directa de `smartstock_central` en la rama `pruebas-multiempresa`, incluidos los parámetros SSL. Si ya comprobaste esa conexión en la copia anterior, puedes copiar ese archivo. Este ejemplo supone que ambas carpetas de proyecto están en el mismo directorio.

```bat
if not exist ".env.multiempresa.local" copy "..\SmartStock\smartstock\.env.multiempresa.local" ".env.multiempresa.local"
python manage.py check --settings=esquema_multiempresa.migracion
```

Ambos archivos están excluidos de Git. Cuando los ajustes cargan correctamente, Django muestra `System check identified no issues`.

Comprueba el esquema de las tres bases.

```bat
python manage.py plan_esquema --settings=esquema_multiempresa.settings
```

Con el esquema actual deben aparecer 17 tablas previstas en la central y 46 en cada empresa. Ejecuta las migraciones también al actualizar una instalación que tenía las dos tablas iniciales en la central. Django añadirá las tablas de autenticación, sesiones, auditoría técnica y pases de acceso.

```bat
python manage.py migrate --database=central --settings=esquema_multiempresa.migracion
python manage.py migrate --database=ferreteria --settings=esquema_multiempresa.migracion
python manage.py migrate --database=repuestos --settings=esquema_multiempresa.migracion
```

## Primer acceso

```bat
python manage.py registrar_empresas_prueba --settings=esquema_multiempresa.migracion
python manage.py seed_empresa la-fragua --settings=esquema_multiempresa.web
python manage.py seed_empresa punto-motor --settings=esquema_multiempresa.web
python manage.py createsuperuser --database=central --settings=esquema_multiempresa.web
python manage.py runserver 127.0.0.1:8000 --settings=esquema_multiempresa.web
```

El primer comando registra las asociaciones que falten. Se puede repetir y conserva el estado de las empresas registradas. Los dos comandos `seed_empresa` preparan los permisos y roles en la base correspondiente. Cuando se crea una cuenta de administrador de negocio, el comando muestra su correo y una contraseña aleatoria propia de esa empresa. Guarda cada contraseña por separado. Si la cuenta ya existía, conserva sus credenciales. La opción `--sin-admin` permite preparar solo los roles y permisos.

El comando `createsuperuser` prepara la cuenta técnica en la central y solicita un correo propio del equipo SmartStock, nombre, apellido y contraseña. Ejecútalo una vez por cada cuenta técnica que necesites.

Abre [el inicio de sesión local](http://127.0.0.1:8000/) e ingresa tu correo y contraseña. Una cuenta de empresa accede a su propia dirección automáticamente y llega a la vista de su rol. El superusuario creado en la central accede a `/sistema/`, donde administra el directorio de empresas y las cuentas técnicas. Para registrar una empresa adicional, su base y conexión deben estar preparadas en el servidor.

Las cuentas de prueba pueden conservar `admin@smartstock.cl` en ambas empresas con contraseñas diferentes. Si el mismo correo y contraseña dan acceso a varias empresas, el formulario muestra esos destinos después de autenticarse. La opción **¿Olvidaste tu contraseña?** envía los enlaces de recuperación correspondientes al correo ingresado.

El login común consulta las cuentas de las empresas activas configuradas. Si una base está inaccesible, devuelve un error temporal y permite reintentar. Este recorrido está pensado para el ensayo actual de dos empresas. Las cuentas técnicas centrales pueden autenticarse independientemente de la disponibilidad de las bases de clientes.

El paso a una empresa usa un pase de dos minutos enviado por POST desde el origen del login central. Se consume una sola vez y comprueba la empresa, la cuenta, sus permisos y su contraseña actual. Los tokens JWT se generan en la empresa de destino. Las sesiones usan cookies propias de cada dirección y una firma vinculada a su empresa.

Django comprueba que la empresa sigue activa en cada petición. El perfil web escribe las sesiones técnicas y los pases en la central. Las transacciones de inventario, el Kardex, las comparaciones y las descargas usan la base de la empresa. Los archivos subidos se guardan en `media/<alias>/`. Los correos de recuperación aparecen en la consola de desarrollo y los envíos SMS están desactivados en esta prueba.

## Comprobar el aislamiento

Crea una bodega y el mismo SKU en las dos empresas. Registra una entrada de 15 unidades en La Fragua y otra de 4 en Punto Motor. Desde La Fragua registra una salida de 3 unidades. El Kardex de La Fragua debe terminar en 12 y mostrar esa salida. El de Punto Motor debe seguir en 4. Para contrastarlo en el dashboard, crea un segundo SKU en cada catálogo y usa **Comparar productos** sobre la misma bodega y período.

La suite automatizada crea sus propias tres bases desechables. Comprueba el inicio de sesión, las restricciones entre empresas, el Kardex y el comparador, la exportación de auditoría, las sesiones, los archivos y las reversiones de transacciones.

```bat
set "SS_TEST_POSTGRES="
python manage.py test esquema_multiempresa.pruebas_web esquema_multiempresa.pruebas_login --settings=esquema_multiempresa.testing --verbosity 2
```

Para ejecutar la misma suite con PostgreSQL local o en CI, configura las variables `SS_TEST_DB_USER`, `SS_TEST_DB_PASSWORD`, `SS_TEST_DB_HOST` y `SS_TEST_DB_PORT` con un usuario de pruebas que pueda crear bases y establece `SS_TEST_POSTGRES=true`. El perfil de pruebas usa nombres de base reservados para QA.

La prueba de navegador inicia sesión desde el formulario común en dos pestañas de Chrome, comprueba sus saldos, cierra una sesión mientras la otra sigue activa y verifica el destino del superusuario central. Con Chrome instalado y el entorno de pruebas SQLite seleccionado puedes ejecutarla en CMD.

```bat
set "SS_TEST_POSTGRES="
python -m pip install selenium==4.52.0
python manage.py test esquema_multiempresa.selenium_suite --settings=esquema_multiempresa.testing --verbosity 2
```
