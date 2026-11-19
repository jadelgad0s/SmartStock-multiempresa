# Probar SmartStock con dos empresas

Este perfil levanta una instancia local de Django y consulta el directorio de empresas de la rama `pruebas-multiempresa` de Neon. Cada empresa dispone de su propia base PostgreSQL. Sus usuarios, roles, sesiones, productos, bodegas, movimientos y auditoría se guardan en esa base.

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

Con el esquema actual deben aparecer 2 tablas previstas en la central y 46 en cada empresa. Si las tres bases están recién creadas y vacías, se preparan con estos comandos.

```bat
python manage.py migrate empresas --database=central --settings=esquema_multiempresa.migracion
python manage.py migrate --database=ferreteria --settings=esquema_multiempresa.migracion
python manage.py migrate --database=repuestos --settings=esquema_multiempresa.migracion
```

## Primer acceso

```bat
python manage.py registrar_empresas_prueba --settings=esquema_multiempresa.migracion
python manage.py seed_empresa la-fragua --settings=esquema_multiempresa.web
python manage.py seed_empresa punto-motor --settings=esquema_multiempresa.web
python manage.py runserver 127.0.0.1:8000 --settings=esquema_multiempresa.web
```

El primer comando registra las asociaciones que falten. Se puede repetir y conserva el estado de las empresas registradas. Los dos comandos `seed_empresa` preparan los permisos y roles en la base correspondiente. Cuando se crea una cuenta de administrador de negocio, el comando muestra su correo y una contraseña aleatoria propia de esa empresa. Guarda cada contraseña por separado. Si la cuenta ya existía, conserva sus credenciales. La opción `--sin-admin` permite preparar solo los roles y permisos.

Abre [el portal local](http://127.0.0.1:8000/), escribe el código de empresa y pulsa **Continuar**. También puedes abrir [La Fragua](http://la-fragua.localhost:8000/) y [Punto Motor](http://punto-motor.localhost:8000/) en dos pestañas del mismo navegador. La pantalla de acceso y el título de la pestaña muestran la empresa. Inicia sesión con la cuenta de cada una.

Django elige la empresa antes de abrir la sesión y comprueba que su directorio sigue activo en cada petición. El perfil web abre la central en modo de lectura. Las transacciones de inventario, el Kardex, las comparaciones y las descargas usan la base correspondiente a la dirección de la empresa. Los archivos subidos se guardan en `media/<alias>/`. Los correos de recuperación aparecen en la consola de desarrollo y los envíos SMS están desactivados en esta prueba.

## Comprobar el aislamiento

Crea una bodega y el mismo SKU en las dos empresas. Registra una entrada de 15 unidades en La Fragua y otra de 4 en Punto Motor. Desde La Fragua registra una salida de 3 unidades. El Kardex de La Fragua debe terminar en 12 y mostrar esa salida. El de Punto Motor debe seguir en 4. Para contrastarlo en el dashboard, crea un segundo SKU en cada catálogo y usa **Comparar productos** sobre la misma bodega y período.

La suite automatizada crea sus propias tres bases desechables. Comprueba el inicio de sesión, las restricciones entre empresas, el Kardex y el comparador, la exportación de auditoría, las sesiones, los archivos y las reversiones de transacciones.

```bat
set "SS_TEST_POSTGRES="
python manage.py test esquema_multiempresa.pruebas_web --settings=esquema_multiempresa.testing --verbosity 2
```

Para ejecutar la misma suite con PostgreSQL local o en CI, configura las variables `SS_TEST_DB_USER`, `SS_TEST_DB_PASSWORD`, `SS_TEST_DB_HOST` y `SS_TEST_DB_PORT` con un usuario de pruebas que pueda crear bases y establece `SS_TEST_POSTGRES=true`. El perfil de pruebas usa nombres de base reservados para QA.

La prueba de navegador abre las dos empresas en pestañas de Chrome, comprueba sus saldos y cierra una sesión mientras la otra sigue activa. Con Chrome instalado y el entorno de pruebas SQLite seleccionado puedes ejecutarla en CMD.

```bat
set "SS_TEST_POSTGRES="
python -m pip install selenium==4.52.0
python manage.py test esquema_multiempresa.selenium_suite --settings=esquema_multiempresa.testing --verbosity 2
```
