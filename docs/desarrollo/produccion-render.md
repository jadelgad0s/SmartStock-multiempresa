# Preparación de producción multiempresa en Render

El perfil `esquema_multiempresa.production` publica la entrada central y las empresas desde un mismo servicio web. Lee tres conexiones independientes de Neon y almacena las imágenes en un bucket privado compatible con S3. El alojamiento de Render puede mantenerse en Free; el bucket y sus cuotas dependen del proveedor que se configure.

Esta guía prepara la publicación. El cambio del repositorio del servicio y de sus dominios se realiza después de configurar las bases, el almacenamiento y comprobar una instalación temporal.

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

Prepara en Render y en el DNS del dominio las direcciones central, www y los subdominios de las empresas. Los destinos finales previstos son smartstockchile.cl, la-fragua.smartstockchile.cl y punto-motor.smartstockchile.cl. La prueba temporal debe disponer también de nombres de empresa que lleguen a esa instalación; no cambies todavía el dominio central del sitio actual.

La recuperación e invitaciones utilizan Resend por HTTPS. El buzón conserva su configuración de Zoho en la central y necesita una clave de cifrado compatible.

Los SMS están desactivados por defecto en el perfil nuevo. Si se habilitan expresamente con SMS_ALERTAS_ACTIVAS=True, utiliza las variables de la [guía SMS](../modulos/alertas-sms.md). Los destinatarios siguen siendo la lista configurada en el servidor, compartida por esta instalación. El callback se construye con el dominio de la empresa y su firma se valida sobre esa URL exacta; el comando general no sustituye el contexto de una empresa.

## Validación aislada

La [guía de pruebas](pruebas.md) incluye pruebas de producción con datos desechables: URLs incompletas o inseguras, hosts públicos, HTTPS detrás del proxy, entrega de sesión entre dominios, cookies y archivos separados por empresa. El arranque real recoge los estáticos y sirve la entrada y /salud/ con conexiones a proveedores bloqueadas. El SDK de objetos se comprueba con respuestas controladas; la conectividad al bucket real se valida al configurar el proveedor.

Referencias: [variables de Render](https://render.com/docs/configure-environment-variables), [despliegues](https://render.com/docs/deploys), [comprobaciones HTTP](https://render.com/docs/health-checks), [archivos persistentes](https://render.com/docs/disks), [configuración del backend S3](https://django-storages.readthedocs.io/en/latest/backends/amazon-S3.html).
