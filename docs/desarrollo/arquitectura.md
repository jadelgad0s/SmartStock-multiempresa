# Arquitectura y organización

SmartStock es una aplicación Django con una interfaz de plantillas HTML y JavaScript. Django REST Framework expone las operaciones que utiliza la interfaz. PostgreSQL conserva usuarios, inventario e historial; la instalación multiempresa usa bases alojadas en Neon.

## Componentes del código

| Componente | Responsabilidad |
| --- | --- |
| apps/usuarios | Autenticación, usuarios, roles, permisos y recuperación de contraseña. |
| apps/productos | Productos, bodegas, ubicaciones, existencias, movimientos, transferencias, mermas, reportes y alertas. |
| apps/core | Páginas comunes, contexto de empresa, auditoría y utilidades compartidas. |
| esquema_multiempresa | Directorio central, selección de empresa, enrutamiento de bases, panel interno, soporte y contacto. |
| config | Ajustes comunes, URLs y servidor WSGI. |
| templates y static | Presentación de la aplicación en el navegador. |
| desktop.py | Ventana de escritorio que abre el servidor o una dirección web. |

## Separación de datos

| Base | Datos |
| --- | --- |
| Central de SmartStock | Empresas registradas, cuentas del equipo, sesiones centrales, pases de acceso, soporte y buzón de contacto. |
| Base de una empresa | Sus usuarios y permisos, productos, bodegas, existencias, operaciones, sesiones e historial. |

En el ensayo actual, los alias son central, ferreteria y repuestos. La [guía multiempresa](multiempresa.md) identifica sus bases y direcciones.

El middleware de empresa identifica el ámbito a partir del host antes de abrir la sesión. El enrutador dirige las lecturas, escrituras y migraciones al alias correspondiente. El pase entre el acceso central y una empresa se valida en el destino y se consume una sola vez.

Los archivos subidos por una empresa se organizan bajo su alias. Un despliegue debe configurar su persistencia por separado de PostgreSQL.

## Dos grupos de permisos

Los usuarios de una empresa tienen los perfiles Administrador, Encargado de bodega y Operador. Las funciones disponibles dependen de los permisos asignados.

Las cuentas internas de SmartStock gestionan la plataforma y las atenciones de soporte. Consultar información operativa de un cliente requiere la autorización correspondiente. El buzón tiene una cuenta exclusiva. La [matriz de soporte](../modulos/permisos-soporte.md) detalla estas diferencias.

## Perfiles de configuración

| Perfil | Uso |
| --- | --- |
| esquema_multiempresa.web | Desarrollo local multiempresa conectado a la rama de pruebas de Neon. |
| esquema_multiempresa.settings | Inspección del esquema con conexiones de lectura. |
| esquema_multiempresa.migracion | Preparación y migraciones explícitas de las bases de prueba. |
| esquema_multiempresa.testing | Pruebas con bases desechables, sin credenciales de Neon. |
| esquema_multiempresa.production | Servidor público multiempresa, conexiones privadas de Neon y archivos externos. |
| esquema_multiempresa.migracion_produccion | Migraciones por alias con las conexiones directas del entorno público. |
| config.settings.testing | Pruebas de las aplicaciones generales. |
| config.settings.production | Configuración del sitio anterior, con una sola conexión principal. |

El archivo local_settings.py está versionado porque contiene la configuración de consulta del ensayo; lee la conexión privada de .env.multiempresa.local. Las migraciones existentes permanecen dentro de cada aplicación Django para conservar su historial.

## Recorrido para revisar el proyecto

1. Leer el [README](../../README.md) para conocer el alcance.
2. Revisar los modelos y operaciones de apps/productos y los permisos de apps/usuarios.
3. Revisar el middleware, enrutador y login de esquema_multiempresa.
4. Consultar una [guía de módulo](../README.md) y su plantilla/JavaScript.
5. Ejecutar las [pruebas aisladas](pruebas.md) y contrastar los resultados con el comportamiento esperado.
