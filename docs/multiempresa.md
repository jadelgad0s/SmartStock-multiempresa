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

El comando `createsuperuser` prepara el superusuario en la central y solicita un correo propio del equipo SmartStock, nombre, apellido y contraseña. Desde **Cuentas técnicas** se pueden crear las cuentas del personal de soporte.

Abre [el inicio de sesión local](http://127.0.0.1:8000/) e ingresa tu correo y contraseña. Una cuenta de empresa accede a su propia dirección automáticamente y llega a la vista de su rol. El personal de SmartStock accede al panel `/sistema/`, con el diseño, menú lateral, tema y carga de los módulos de la aplicación.

El panel incluye Dashboard, Empresas, Usuarios de empresas, Cuentas técnicas y Auditoría. Al seleccionar una empresa se consultan su resumen de inventario, catálogo, bodegas, movimientos, transferencias, mermas, alertas SMS y reportes. Los reportes usan los cálculos del Kardex y las existencias de la empresa y permiten descargar CSV e imprimir o guardar PDF. Los formularios de usuarios guardan en la base de la empresa elegida y registran al técnico que realizó el cambio en la descripción de auditoría.

Las cuentas centrales con `is_staff=True` representan al personal técnico. El superusuario tiene además `is_superuser=True`. Ambos pueden usar los módulos del panel. **Configuración** abre Django Admin en `/sistema/configuracion/` y exige superusuario tanto en el menú como en cualquier URL interna. La gestión de cuentas del panel permite que un superusuario asigne ese perfil. Las cuentas técnicas pueden administrar otras cuentas técnicas y sus propios datos.

Para registrar una empresa adicional, su base y conexión deben estar preparadas en el servidor. Las empresas inactivas siguen disponibles en el panel de soporte y su acceso operativo queda bloqueado.

## Ficha de empresa y actualización de instalaciones existentes

La ficha central incluye nombre comercial, razón social o nombre del titular, RUT, rubro, contacto principal, correo, teléfono y dirección de contacto (dirección, comuna y región). En un alta nueva se requieren los datos de identificación y el nombre y correo del contacto. El teléfono y la dirección son opcionales. Las empresas registradas antes de esta ampliación conservan sus accesos y pueden completar su información gradualmente. Los datos faltantes se indican en **Ver ficha**.

Después de actualizar el código, aplica esta migración en la base central antes de iniciar el servidor.

```bat
python manage.py migrate --database=central --settings=esquema_multiempresa.migracion
```

La migración `empresas.0003_ficha_empresa` amplía la tabla `empresas`. Conserva los códigos, las bases asignadas y el estado de acceso. Las fechas de registro de las empresas anteriores quedan sin dato porque no se conocen. Las nuevas altas y las actualizaciones guardan sus fechas automáticamente. Se mantienen 17 tablas en la central y 46 en cada empresa.

El RUT admite puntos y un verificador K en minúscula o mayúscula. Se valida el dígito verificador y se guarda sin puntos y con K mayúscula. Un RUT informado pertenece a una sola ficha. El código de acceso se genera a partir del nombre cuando se deja vacío.

**Añadir empresa** ofrece únicamente las bases configuradas que todavía no tienen empresa asignada. Si todas están ocupadas, muestra el motivo y deshabilita **Crear empresa**. El servidor también rechaza un envío manual que intente utilizar una base ocupada. Al editar una empresa, su base se conserva aunque el envío intente cambiarla.

Al guardar se abre **Ver ficha**, que reúne el contacto, la identificación y la preparación operativa. La conexión, la existencia de un administrador activo, las bodegas y los productos se revisan por separado del estado activo/inactivo del servicio. Desde una ficha sin administrador, **Añadir administrador** abre el formulario de usuario de esa empresa con el rol Administrador seleccionado. El registro usa una base ya preparada y la creación de usuarios sigue siendo un paso explícito.

El resumen por empresa distingue **Sin bodegas activas**, **Sin productos activos**, **Sin movimientos en el período** y un error de consulta. Los primeros dos estados muestran una explicación y el acceso al módulo correspondiente. Un período sin movimientos conserva las existencias y su gráfico. Un error de conexión ofrece reintentar y no se presenta como stock cero.

Las cuentas de prueba pueden conservar `admin@smartstock.cl` en ambas empresas con contraseñas diferentes. Si el mismo correo y contraseña dan acceso a varias empresas, el formulario muestra esos destinos después de autenticarse. La opción **¿Olvidaste tu contraseña?** envía los enlaces de recuperación correspondientes al correo ingresado.

El login común consulta las cuentas de las empresas activas configuradas. Si una base está inaccesible, devuelve un error temporal y permite reintentar. Este recorrido está pensado para el ensayo actual de dos empresas. Las cuentas técnicas centrales pueden autenticarse independientemente de la disponibilidad de las bases de clientes.

El paso a una empresa usa un pase de dos minutos enviado por POST desde el origen del login central. Se consume una sola vez y comprueba la empresa, la cuenta, sus permisos y su contraseña actual. Los tokens JWT se generan en la empresa de destino. Las sesiones usan cookies propias de cada dirección y una firma vinculada a su empresa.

Django comprueba que la empresa sigue activa en cada petición. El perfil web escribe las sesiones técnicas y los pases en la central. Las transacciones de inventario, el Kardex, las comparaciones y las descargas usan la base de la empresa. Los archivos subidos se guardan en `media/<alias>/`. Los correos de recuperación aparecen en la consola de desarrollo y los envíos SMS están desactivados en esta prueba.

## Comprobar el aislamiento

Crea una bodega y el mismo SKU en las dos empresas. Registra una entrada de 15 unidades en La Fragua y otra de 4 en Punto Motor. Desde La Fragua registra una salida de 3 unidades. El Kardex de La Fragua debe terminar en 12 y mostrar esa salida. El de Punto Motor debe seguir en 4. Para contrastarlo en el dashboard, crea un segundo SKU en cada catálogo y usa **Comparar productos** sobre la misma bodega y período.

La suite automatizada crea sus propias tres bases desechables. Comprueba el inicio de sesión, las restricciones entre empresas, el Kardex y el comparador, la exportación de auditoría, las sesiones, los archivos y las reversiones de transacciones.

```bat
set "SS_TEST_POSTGRES="
python manage.py test esquema_multiempresa.pruebas_web esquema_multiempresa.pruebas_login esquema_multiempresa.pruebas_sistema --settings=esquema_multiempresa.testing --verbosity 2
```

Para ejecutar la misma suite con PostgreSQL local o en CI, configura las variables `SS_TEST_DB_USER`, `SS_TEST_DB_PASSWORD`, `SS_TEST_DB_HOST` y `SS_TEST_DB_PORT` con un usuario de pruebas que pueda crear bases y establece `SS_TEST_POSTGRES=true`. El perfil de pruebas usa nombres de base reservados para QA.

La prueba de navegador inicia sesión desde el formulario común en dos pestañas de Chrome y comprueba sus saldos y sesiones independientes. En el panel central crea una cuenta técnica, verifica su menú y la restricción de Configuración, registra un usuario en La Fragua y prueba el menú móvil. Con Chrome instalado y el entorno de pruebas SQLite seleccionado puedes ejecutarla en CMD.

```bat
set "SS_TEST_POSTGRES="
python -m pip install selenium==4.52.0
python manage.py test esquema_multiempresa.selenium_suite --settings=esquema_multiempresa.testing --verbosity 2
```
