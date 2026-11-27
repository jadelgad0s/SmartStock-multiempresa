# SmartStock · Inventario multiempresa

Proyecto académico de Ingeniería en Informática de Duoc UC para gestionar el inventario de las bodegas de una PYME. Permite registrar entradas, salidas, transferencias y mermas, consultar existencias y mantener trazabilidad mediante auditoría.

La versión multiempresa separa el directorio y las cuentas de SmartStock de los datos operativos de cada empresa. **Los datos de la instalación multiempresa se almacenan en PostgreSQL en Neon.**

## Empieza por aquí

| Quiero… | Dónde revisar |
| --- | --- |
| Revisar el repositorio durante la presentación | [Recorrido de revisión académica](docs/presentacion.md) |
| Entender el proyecto y sus componentes | [Arquitectura y organización](docs/desarrollo/arquitectura.md) |
| Instalar y ejecutar la versión multiempresa | [Preparación en Windows y conexión a Neon](docs/desarrollo/multiempresa.md) |
| Revisar el despliegue público | [Producción multiempresa en Render](docs/desarrollo/produccion-render.md) |
| Entender un módulo o sus permisos | [Índice de documentación](docs/README.md) |
| Ejecutar las pruebas sin credenciales de Neon | [Guía de pruebas](docs/desarrollo/pruebas.md) |
| Compilar la aplicación de escritorio | [Aplicación para Windows](docs/desarrollo/escritorio.md) |
| Distinguir la versión de GitHub del sitio publicado | [Estado de las versiones](docs/desarrollo/estado-versiones.md) |

## Funcionalidades

- Catálogo de productos con SKU, códigos de barras y QR.
- Existencias, mínimos y disponibilidad por bodega.
- Entradas y salidas de mercadería.
- [Lotes y FIFO](docs/modulos/lotes-fifo.md), con costos por recepción y conservación de lotes en transferencias.
- Transferencias entre bodegas y registro de mermas y bajas.
- Ubicaciones físicas: pasillos, estanterías y niveles.
- Reportes de existencias, stock crítico, movimientos, mermas y Kardex.
- Usuarios, roles, permisos, auditoría y notificaciones.
- Alertas de stock por SMS y buzón de contacto, sujetos a la configuración de sus proveedores.
- Panel interno de SmartStock y soporte temporal autorizado por la empresa.

El alcance del proyecto es el **control de inventario**. No incluye ventas ni facturación.

## Empresas y accesos

| Ámbito | Responsabilidad |
| --- | --- |
| Empresa | Administrador, Encargado de bodega y Operador, con permisos para sus tareas. |
| Plataforma SmartStock | Superusuario técnico, Administrador de plataforma y Soporte técnico. |
| Contacto | Cuenta de atención con acceso exclusivo a su buzón. |

El personal de soporte consulta información del cliente mediante autorizaciones vigentes. Los permisos se verifican en el servidor, además de controlar las opciones visibles del menú. La [guía de soporte](docs/modulos/permisos-soporte.md) explica los límites de cada perfil.

## Organización del repositorio

| Ruta | Contenido |
| --- | --- |
| [apps/](apps/) | Aplicaciones Django de inventario, usuarios y servicios comunes. Incluyen sus migraciones y pruebas de API. |
| [esquema_multiempresa/](esquema_multiempresa/) | Directorio de empresas, selección de base, login común, soporte y panel central. |
| [config/](config/) | Configuración general de Django, URLs y puntos de entrada del servidor. |
| [templates/](templates/) | Pantallas HTML. |
| [static/](static/) | JavaScript, CSS y recursos que utiliza la interfaz web. |
| [tests/](tests/) | Pruebas JavaScript y recursos de comprobación del ejecutable. |
| [docs/](docs/) | Guías de uso, documentación técnica y antecedentes históricos. |
| [scripts/](scripts/) | Herramientas de compilación. |
| [recursos/](recursos/) | Identidad visual compartida y pantalla de inicio del escritorio. |
| [.github/workflows/](.github/workflows/) | Comprobaciones automáticas en GitHub Actions. |
| [manage.py](manage.py) | Administración de Django. |
| [desktop.py](desktop.py) | Punto de entrada de la aplicación de escritorio. |
| [local_settings.py](local_settings.py) | Perfil de lectura de la rama de pruebas de Neon; las credenciales se leen desde un archivo privado. |

Las pruebas Python que están junto al código de cada aplicación forman parte de la estructura habitual de Django. No son copias de la aplicación; la [guía de pruebas](docs/desarrollo/pruebas.md) indica cómo ejecutarlas.

## Requisitos y ejecución

- **Python 3.13.7**, indicado en [.python-version](.python-version).
- Dependencias comunes del servidor en [requirements-web.txt](requirements-web.txt).
- Una conexión autorizada a la rama de pruebas de Neon para la ejecución multiempresa.
- Node.js 20 o posterior para las pruebas JavaScript; Chrome y Selenium para las pruebas de navegador.

Desde CMD, en la raíz del proyecto:

~~~bat
py -3.13 -m venv .venv
call .venv\Scripts\activate.bat
python -m pip install -r requirements-web.txt
~~~

A continuación, sigue la [guía de instalación multiempresa](docs/desarrollo/multiempresa.md) para configurar los archivos privados, comprobar las bases y preparar una instalación nueva. Si tu instalación ya está configurada:

~~~bat
python manage.py check --settings=esquema_multiempresa.web
python manage.py runserver --settings=esquema_multiempresa.web
~~~

Accesos del entorno local configurado: [entrada común](http://127.0.0.1:8000/), [La Fragua](http://la-fragua.localhost:8000/) y [Punto Motor](http://punto-motor.localhost:8000/). Las cuentas se crean durante la preparación; este repositorio no publica contraseñas.

## Versiones y despliegue

Desde el 24 de noviembre de 2026, el sitio público utiliza la versión multiempresa de este repositorio, con Render Free y bases independientes en Neon.

| Acceso | Dirección |
| --- | --- |
| Central SmartStock | https://smartstockchile.cl/ |
| Ferretería La Fragua | https://la-fragua.smartstockchile.cl/ |
| Repuestos Punto Motor | https://punto-motor.smartstockchile.cl/ |

El perfil público es `esquema_multiempresa.production`. Las actualizaciones de código e infraestructura continúan siendo manuales. El [estado de las versiones](docs/desarrollo/estado-versiones.md) identifica el despliegue comprobado y las guías para mantenerlo.

Las notas antiguas de avances están en [docs/historial/](docs/historial/). Se conservan como antecedentes y están separadas de las instrucciones actuales.
