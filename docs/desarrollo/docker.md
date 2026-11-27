# Ejecutar SmartStock multiempresa con Docker

Esta configuración prepara una instalación local de demostración con Django, Gunicorn y PostgreSQL 16. Incluye la central de SmartStock, Ferretería La Fragua y Repuestos Punto Motor. Las bases e imágenes se guardan en volúmenes locales.

## Preparación

Instala Docker Desktop y comprueba que esté iniciado. En Windows utiliza los contenedores Linux. Desde la carpeta del repositorio, junto al Dockerfile, copia la configuración de ejemplo.

En CMD de Windows, ejecuta el siguiente comando.

```bat
copy .env.docker.example .env.docker.local
```

En PowerShell, Linux o macOS, utiliza este comando.

```bash
cp .env.docker.example .env.docker.local
```

El archivo contiene valores de demostración para la clave de Django, PostgreSQL y las cuentas iniciales. Puedes editarlos antes del primer arranque. La contraseña de las cuentas se toma de `SS_DOCKER_DEMO_PASSWORD`. El archivo `.env.docker.local` queda excluido de Git y de la imagen.

Inicia los servicios con Compose.

```bash
docker compose --env-file .env.docker.local up --build --detach --wait
```

PostgreSQL crea tres bases. Cuando está disponible, la aplicación aplica las migraciones por alias, registra las empresas y prepara sus permisos y cuentas iniciales. Después recopila los estáticos e inicia Gunicorn como usuario de aplicación. El primer arranque tarda más por la descarga de imágenes y dependencias.

## Accesos de demostración

| Ámbito | Dirección | Correo |
| --- | --- | --- |
| Equipo técnico de SmartStock | http://localhost:8000/ | tecnico@smartstock.test |
| Ferretería La Fragua | http://la-fragua.localhost:8000/ | admin.lafragua@smartstock.test |
| Repuestos Punto Motor | http://punto-motor.localhost:8000/ | admin.puntomotor@smartstock.test |

La contraseña inicial está en `SS_DOCKER_DEMO_PASSWORD` de `.env.docker.local`. El ejemplo utiliza `Demo-SmartStock-2026!`. Las cuentas empresariales tienen el perfil Administrador y la cuenta técnica tiene el perfil Superusuario técnico. El catálogo local comienza vacío y permite registrar productos y bodegas desde la interfaz.

Los navegadores actuales resuelven los dominios `.localhost` hacia el equipo local. Si el puerto 8000 está ocupado, cambia `SMARTSTOCK_PORT` en `.env.docker.local` y usa ese puerto en las direcciones anteriores.

## Archivos y servicios

| Archivo o servicio | Responsabilidad |
| --- | --- |
| Dockerfile | Imagen Python 3.13.7, requisitos web, código y usuario de ejecución. |
| docker-compose.yml | Aplicación, PostgreSQL, red, comprobaciones de salud y volúmenes. |
| .dockerignore | Exclusión de secretos locales, Git, entornos virtuales y archivos de desarrollo de la imagen. |
| esquema_multiempresa/docker.py | Bases locales, enrutamiento multiempresa, estáticos y almacenamiento por empresa. |
| infra/docker/01-databases.sh | Creación inicial de las tres bases de PostgreSQL. |
| preparar_docker | Migraciones por alias y preparación repetible del directorio y de las cuentas iniciales. |
| postgres_data | Persistencia de las bases locales. |
| media_data | Persistencia de las imágenes, separadas por empresa. |

El servicio web publica el puerto exclusivamente en la interfaz local del equipo. PostgreSQL se comunica por la red interna de Compose. Los correos de esta instalación se muestran en los registros del contenedor y las alertas SMS están desactivadas en el perfil local.

## Operación

Consulta el estado y los registros de la aplicación.

```bash
docker compose --env-file .env.docker.local ps
docker compose --env-file .env.docker.local logs --follow web
```

Detén los servicios conservando los volúmenes.

```bash
docker compose --env-file .env.docker.local down
```

Vuelve a iniciarlos con el siguiente comando.

```bash
docker compose --env-file .env.docker.local up --detach --wait
```

Los reinicios conservan los productos, las imágenes, las cuentas y los cambios de permisos. La contraseña de ejemplo se utiliza al crear las cuentas. Para cambiar una clave existente, utiliza el comando interactivo en su base. El siguiente comando corresponde al administrador de La Fragua.

```bash
docker compose --env-file .env.docker.local exec web python manage.py changepassword admin.lafragua@smartstock.test --database=ferreteria
```

Las bases locales se llaman `smartstock_central`, `ferreteria_la_fragua` y `repuestos_punto_motor`. Las conexiones de esta instalación se definen en el perfil Docker y en las variables explícitas de Compose.

## Verificación

El flujo `Docker multiempresa` de GitHub valida el archivo Compose, construye la imagen, inicia ambos servicios y comprueba los accesos a la central y a las empresas. También registra productos con el mismo SKU en ambas bases, comprueba el rechazo de tokens cruzados y sube imágenes diferentes con el mismo nombre. Finalmente recrea los contenedores con sus volúmenes y verifica la persistencia.

La preparación repetible también se comprueba con bases desechables mediante `esquema_multiempresa.pruebas_docker`.

Referencias de Docker para el [orden de inicio de servicios](https://docs.docker.com/compose/how-tos/startup-order/) y las [imágenes de PostgreSQL](https://hub.docker.com/_/postgres).
