# Producción multiempresa en Render

El perfil `esquema_multiempresa.production` publica la entrada central y las empresas desde un mismo servicio web. Lee tres conexiones independientes de Neon y almacena las imágenes en un bucket privado compatible con S3. El alojamiento de Render puede mantenerse en Free; el bucket y sus cuotas dependen del proveedor que se configure.

El dominio oficial utiliza este perfil desde el 24 de noviembre de 2026. Esta guía describe los recursos activos, las variables y las comprobaciones del despliegue. La [guía del traslado](cambio-dominio.md) conserva el procedimiento y la reversión.

## Recursos preparados en Neon

La preparación del 23 de noviembre de 2026 conserva las bases multiempresa existentes mediante una copia independiente de `pruebas-multiempresa`, llamada `produccion-multiempresa`, en el proyecto SmartStock. Esta copia conserva las cuentas y la configuración; el usuario decidió iniciar con el inventario actual de esas bases. Zoho se reconectó desde la cuenta de Contacto y se comprobó en el servicio temporal. La autorización se conserva cifrada con la clave privada de esta instalación.

| Alias Django | Base de Neon | Variable privada |
| --- | --- | --- |
| central | smartstock_central | SS_CENTRAL_DATABASE_URL |
| ferreteria | ferreteria_la_fragua | SS_FERRETERIA_DATABASE_URL |
| repuestos | repuestos_punto_motor | SS_REPUESTOS_DATABASE_URL |

Las tres conexiones utilizan el endpoint directo de `produccion-multiempresa`, con SSL. El endpoint puede consultarse en Neon; no se deben copiar las URLs completas al repositorio.

| Parámetro de objetos | Valor |
| --- | --- |
| Proveedor | Neon Object Storage |
| Región | us-east-2 |
| Bucket | smartstock-imagenes |
| Acceso | Privado |
| Endpoint | https://br-purple-smoke-b52qkb96.storage.c-7.us-east-2.aws.neon.tech |
| Credencial de servidor | Limitada a almacenamiento de esta rama; conservada en Render. |

Las bases de pruebas continúan siendo independientes. El bucket corresponde a la rama de destino y no depende del disco temporal de Render. Las cuotas gratuitas se comparten con otros recursos del mismo proyecto; revisar el consumo en Neon antes de aumentar el volumen.

La credencial de S3 declara los permisos `storage:read` y `storage:write`. El cliente usa cargas compatibles con Neon y calcula las sumas de comprobación cuando la operación las exige, con HTTPS, firma SigV4 y direccionamiento por ruta. Los errores de la verificación muestran únicamente la operación y un código conocido, sin mensajes ni cabeceras del proveedor.

## Servicio público y verificación de proveedores

El servicio `smartstock-multiempresa-pruebas` utiliza Render Free en Ohio y este repositorio. Su nombre identifica el recurso conservado del ensayo. La [entrada pública](https://smartstockchile.cl/) es el acceso principal; la dirección onrender.com permanece habilitada. Las actualizaciones automáticas de código e infraestructura están desactivadas.

`SS_DOMINIO_EMPRESAS=smartstockchile.cl` configura el dominio definitivo. Los accesos con `.pruebas.` pertenecen al ensayo previo al traslado. La central y las empresas conservan las bases, el almacenamiento y la clave privada que se comprobaron en ese ensayo.

Desde un equipo que tenga las variables privadas del servicio:

```bash
python manage.py verificar_produccion --probar-archivos --settings=esquema_multiempresa.production
```

El comando abre cada conexión real, comprueba el nombre de la base y escribe el mismo nombre relativo de archivo con contenido diferente en las dos empresas. Luego verifica ambas lecturas y elimina únicamente los archivos temporales que acaba de crear. No aplica migraciones, importa inventario ni muestra credenciales.

Para ejecutar esa misma comprobación al iniciar el servicio temporal, configura `SS_VERIFICAR_PRODUCCION=True` durante el despliegue de validación. Si falla, el inicio se detiene. Después de comprobar el resultado, guarda `SS_VERIFICAR_PRODUCCION=False` para los despliegues siguientes. Este control es explícito y permanece desactivado por defecto.

La lectura/escritura de imágenes y la conexión de bases se comprobaron durante la preparación. Las pruebas de cuentas, permisos, correos y navegación se realizan con el contexto de cada empresa en los dominios públicos.

## Dominios públicos

[infra/render-produccion.yaml](../../infra/render-produccion.yaml) es la configuración activa. El plan se aplicó el 24 de noviembre de 2026, conservando el servidor Free. Antes de aplicarlo, el usuario confirmó cero dominios utilizados de dos incluidos; el plan añadió el dominio principal y un comodín para las empresas.

| Parámetro | Valor |
| --- | --- |
| Servicio existente | smartstock-multiempresa-pruebas, srv-dc2b7safngtc73bbupu0 |
| Workspace | My Workspace |
| Plan del servidor | Free, una instancia en Ohio |
| Archivo de configuración | infra/render-produccion.yaml |
| Rama | main |
| Sincronización de infraestructura | Manual, autoSync desactivado |
| Publicaciones automáticas de código | Desactivadas |
| Dominios registrados | smartstockchile.cl y *.smartstockchile.cl |
| Comprobación HTTP | /salud/ |

El Blueprint administra el servicio existente indicado. Para futuros cambios, comprobar que el plan corresponde a ese ID y conserva Free. El archivo declara únicamente la variable pública SS_DOMINIO_EMPRESAS; las variables privadas continúan gestionándose en Environment y se conservan al estar omitidas del archivo. La autorización de Zoho depende de mantener estable SECRET_KEY.

La entrada central utiliza el dominio principal y el comodín cubre las direcciones de empresa:

| Acceso | Dirección pública |
| --- | --- |
| Central SmartStock | https://smartstockchile.cl/ |
| La Fragua | https://la-fragua.smartstockchile.cl/ |
| Punto Motor | https://punto-motor.smartstockchile.cl/ |

La verificación pública del 24 de noviembre de 2026 confirmó HTTPS y HTTP 200 en las tres pantallas de acceso, con la marca correspondiente. `/salud/` devuelve HTTP 200 y `{"estado": "ok"}` en la central y en las dos empresas. www redirige al dominio principal. El despliegue `dep-dc2hlnek1f9s7381q9q0`, del commit `5792355ac08da94b21d1b0fbd77cc543da018af0`, terminó live.

El usuario confirmó el funcionamiento del acceso de prueba y mostró una sesión de La Fragua abierta desde la central antes del traslado. La comprobación funcional en los dominios definitivos se realiza con las cuentas existentes. La [guía del traslado](cambio-dominio.md) conserva el procedimiento de reversión.

El plan Free del servidor y el cupo de dominios personalizados son conceptos distintos. Render incluye dos dominios en el workspace Hobby y cobra USD 0,25 mensuales por cada dominio que exceda el cupo. Revisar el uso del workspace y cualquier cargo adicional antes de aprobar el dominio comodín. Referencias: [dominios personalizados](https://render.com/docs/custom-domains), [planes y precios](https://render.com/pricing).

Los registros web de Cloudflare, dentro de la zona smartstockchile.cl, apuntan al servicio multiempresa con proxy DNS only y TTL automático. Los destinos de validación deben coincidir con las instrucciones que Render muestre para el dominio registrado.

| Tipo | Nombre | Destino |
| --- | --- | --- |
| CNAME | @ | smartstock-multiempresa-pruebas.onrender.com |
| CNAME | www | smartstock-multiempresa-pruebas.onrender.com |
| CNAME | * | smartstock-multiempresa-pruebas.onrender.com |
| CNAME | _acme-challenge | smartstock-multiempresa-pruebas.verify.renderdns.com |
| CNAME | _cf-custom-hostname | smartstock-multiempresa-pruebas.hostname.renderdns.com |

El registro @ dirige la base del comodín a Render. Para actualizar @ y www, editar sus filas CNAME existentes en Cloudflare: agregar otra fila con el mismo nombre produce un conflicto. Los registros de correo de Zoho conservan sus valores.

Después de futuros cambios de dominio o despliegue, abrir /salud/ bajo los tres hosts y comprobar el acceso desde la central con las cuentas de cada empresa. Guía del proveedor: [DNS de Cloudflare](https://render.com/docs/configure-cloudflare-dns).

## Perfiles

| Perfil | Función |
| --- | --- |
| esquema_multiempresa.production | Servidor público con HTTPS, sesiones por host, pool de conexiones y almacenamiento externo. |
| esquema_multiempresa.migracion_produccion | Migraciones explícitas por alias, con las mismas conexiones directas y sin el pool web. |
| esquema_multiempresa.web | Ensayo local existente con localhost y la rama de pruebas. |
| config.settings.production | Despliegue general anterior, con una base principal. |

El perfil nuevo no importa local_settings.py, no deriva las conexiones de una sola URL y no utiliza DATABASE_URL ni las variables DB_* del proyecto anterior. Si falta una conexión o dos alias apuntan a la misma base, el arranque se detiene.

## Variables privadas y parámetros

La [plantilla de producción](../../.env.multiempresa.production.example) contiene los nombres y valores públicos, sin credenciales. Completa las variables del nuevo servicio desde Environment en Render.

| Variable | Valor que se prepara |
| --- | --- |
| SECRET_KEY | Clave privada estable de al menos 50 caracteres. |
| DJANGO_SETTINGS_MODULE | esquema_multiempresa.production |
| SS_DOMINIO_EMPRESAS | smartstockchile.cl; en el ensayo público puede ser un dominio de pruebas bajo control del equipo. |
| SS_CENTRAL_DATABASE_URL | URL directa de la central definitiva de Neon. |
| SS_FERRETERIA_DATABASE_URL | URL directa de la base definitiva de La Fragua. |
| SS_REPUESTOS_DATABASE_URL | URL directa de la base definitiva de Punto Motor. |
| SS_S3_ENDPOINT_URL | Origen HTTPS del servicio de objetos compatible con S3, sin rutas ni credenciales en la URL. |
| SS_S3_BUCKET | Nombre del bucket privado. |
| SS_S3_ACCESS_KEY_ID y SS_S3_SECRET_ACCESS_KEY | Credenciales del servidor con acceso al bucket configurado. |
| SS_S3_REGION | Región indicada por el proveedor; por ejemplo, us-east-1 o auto según corresponda. |
| RESEND_API_KEY y DEFAULT_FROM_EMAIL | Proveedor HTTPS y remitente verificado para recuperación e invitaciones. |
| SS_HSTS_SECONDS | 0 durante la comprobación inicial de dominios; se aumenta después de verificar HTTPS. |

Las tres URLs deben ser PostgreSQL de Neon, directas, sin -pooler y con sslmode=require, verify-ca o verify-full. Cada una incluye sus propias credenciales y nombre de base. El pool de psycopg reutiliza conexiones dentro del servidor; las migraciones conservan la conexión directa. La configuración no copia registros ni crea bases.

Si se conserva una central existente, conserva también su SECRET_KEY para descifrar la conexión de Zoho y validar las sesiones. No copies automáticamente la clave del despliegue anterior si pertenece a otra central. Para una central nueva, utiliza una clave propia de producción. SECRET_KEY_FALLBACKS permite una rotación planificada de claves anteriores.

RENDER_EXTERNAL_HOSTNAME lo proporciona Render. Se admite como entrada central junto con el dominio principal y www. Las URLs de las empresas se construyen bajo SS_DOMINIO_EMPRESAS; una dirección onrender.com por sí sola no proporciona subdominios de clientes.

## Construcción, inicio y comprobación de vida

| Campo de Render | Valor |
| --- | --- |
| Repository | jadelgad0s/SmartStock-multiempresa |
| Branch | main |
| Runtime | Python 3.13.7, indicado en .python-version |
| Root Directory | Vacío: manage.py está en la raíz. |
| Build Command | bash scripts/build-render.sh |
| Start Command | bash scripts/start-render.sh |
| Health Check Path | /salud/ |

El [script de construcción](../../scripts/build-render.sh) instala los requisitos, comprueba Django y recopila los archivos estáticos con manifiesto y compresión. El [inicio](../../scripts/start-render.sh) ejecuta Gunicorn en 0.0.0.0:$PORT con un proceso y cuatro hilos. WhiteNoise entrega únicamente los recursos estáticos.

/salud/ comprueba que el proceso HTTP responde, sin abrir sesiones, consultar Neon ni enviar correos o SMS. No confirma que las bases o los proveedores estén disponibles; esa disponibilidad se comprueba durante la preparación y las pruebas funcionales. La ruta admite GET y HEAD, valida el host y no se almacena en caché.

El perfil fuerza HTTPS detrás del proxy de Render y activa las cookies seguras. Las cookies de sesión y CSRF son propias de cada host. HSTS queda inicialmente desactivado; check --deploy puede advertirlo hasta que se verifiquen los dominios y se configure su duración.

## Preparar el esquema antes de cambiar el sitio

Primero elige las bases definitivas y respáldalas si contienen datos. Desde un equipo autorizado, con Python 3.13.7, los requisitos y las variables privadas del entorno de destino:

```bat
python manage.py check --deploy --settings=esquema_multiempresa.production
python manage.py migrate --noinput --database=central --settings=esquema_multiempresa.migracion_produccion
python manage.py migrate --noinput --database=ferreteria --settings=esquema_multiempresa.migracion_produccion
python manage.py migrate --noinput --database=repuestos --settings=esquema_multiempresa.migracion_produccion
```

En Linux, [scripts/migrate-render.sh](../../scripts/migrate-render.sh) ejecuta esas tres migraciones y se detiene si falla una. Cada migración tiene su propia transacción; el conjunto de las tres bases no es una transacción distribuida. Si una falla, revisa el resultado antes de habilitar tráfico.

Las migraciones no se ejecutan durante el build ni cada vez que se reinicia Gunicorn. En un servicio Free se pueden aplicar desde el equipo autorizado antes del cambio. Un servicio pagado permite configurar un pre-deploy command; esa opción no es necesaria para preparar el alojamiento Free.

La migración core.0006 de auditoría ya forma parte de la versión consolidada. Registrar empresas y preparar roles es un paso posterior solo para bases nuevas; sigue la [guía multiempresa](multiempresa.md). No uses el seed para reemplazar cuentas existentes ni crear credenciales de demostración en una instalación ya preparada.

## Imágenes privadas y persistencia

El bucket debe tener desactivado el acceso público. El servidor necesita leer, escribir y eliminar los objetos de su espacio empresas/ y comprobar su existencia. Las claves se conservan en Render, no en el navegador.

| Empresa | Prefijo de objetos |
| --- | --- |
| La Fragua | empresas/ferreteria/ |
| Punto Motor | empresas/repuestos/ |

El mismo nombre de archivo en dos empresas corresponde a objetos distintos. Los enlaces siguen utilizando /media/ dentro del dominio de la empresa y exigen una sesión autenticada. El servidor abre el objeto de ese contexto; no entrega una URL pública del bucket. Un acceso central o un alias no configurado no puede utilizar este almacenamiento.

Las imágenes anteriores no se transfieren al configurar estas variables. Antes de publicar, copia los archivos conservando sus rutas relativas bajo el prefijo de cada empresa y comprueba su lectura con una cuenta de la empresa. Los logos incluidos en static/ se recopilan durante el build y no requieren esa transferencia.

## Dominios e integraciones

Las direcciones central, www y los subdominios de las empresas están configuradas en Render y Cloudflare. La [guía del traslado](cambio-dominio.md) identifica el servidor anterior conservado para reversión y los pasos necesarios para futuras modificaciones.

La recuperación e invitaciones utilizan Resend por HTTPS. El buzón conserva su configuración de Zoho en la central y necesita una clave de cifrado compatible.

Los SMS están desactivados por defecto en el perfil nuevo. Si se habilitan expresamente con SMS_ALERTAS_ACTIVAS=True, utiliza las variables de la [guía SMS](../modulos/alertas-sms.md). Los destinatarios siguen siendo la lista configurada en el servidor, compartida por esta instalación. El callback se construye con el dominio de la empresa y su firma se valida sobre esa URL exacta; el comando general no sustituye el contexto de una empresa.

## Recuperación de cuentas administradoras desde CMD

Para actualizar una cuenta administradora sin cargar las conexiones de la central y el almacenamiento web, utilizar el script independiente:

```cmd
python scripts\actualizar_cuenta_empresa.py --empresa punto-motor --usuario actual@example.test --nombres "Nombres" --apellidos "Apellidos" --correo nuevo@example.test
```

Sustituir los datos por los de la cuenta. Con la terminal interactiva y el entorno virtual activo, el script solicita de forma oculta la URL privada `SS_REPUESTOS_DATABASE_URL` del servicio publicado y la contraseña nueva dos veces. Para La Fragua se utiliza `--empresa la-fragua` y la URL `SS_FERRETERIA_DATABASE_URL`.

El destino se valida contra el servidor de la rama `produccion-multiempresa` y la base de la empresa seleccionada. Se conserva la política de contraseñas del proyecto, el rol, los permisos y el estado de la cuenta. Los datos y la contraseña se guardan junto con una entrada de auditoría; también se limpia el bloqueo por intentos fallidos. Un error revierte los cambios de la transacción. La auditoría conserva los cambios del perfil y el indicador de clave actualizada, sin guardar la contraseña ni su hash.

El script no carga el perfil `esquema_multiempresa.production`, no necesita las variables de la central ni S3 y no modifica archivos `.env` ni la configuración de Render. Las pruebas se ejecutan con SQLite aislado en Windows y Linux.

## Validación aislada

La [guía de pruebas](pruebas.md) incluye pruebas de producción con datos desechables: URLs incompletas o inseguras, hosts públicos, HTTPS detrás del proxy, entrega de sesión entre dominios, cookies y archivos separados por empresa. El arranque real recoge los estáticos y sirve la entrada y /salud/ con conexiones a proveedores bloqueadas. El SDK de objetos se comprueba con respuestas controladas; la conectividad al bucket real se valida al configurar el proveedor.

Referencias: [variables de Render](https://render.com/docs/configure-environment-variables), [despliegues](https://render.com/docs/deploys), [comprobaciones HTTP](https://render.com/docs/health-checks), [archivos persistentes](https://render.com/docs/disks), [configuración del backend S3](https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html).
