# Documentación de SmartStock

Este índice organiza las guías del repositorio. Para una primera revisión, comienza con el [README principal](../README.md), continúa con la arquitectura y termina con las pruebas.

El [recorrido de revisión académica](presentacion.md) relaciona las funciones que se pueden demostrar con el código y las pruebas que las comprueban.

## Desarrollo y ejecución

| Documento | Para qué sirve |
| --- | --- |
| [Arquitectura y organización](desarrollo/arquitectura.md) | Relación entre las carpetas, el servidor y las bases de cada empresa. |
| [Instalación multiempresa](desarrollo/multiempresa.md) | Python, archivos privados, Neon, preparación y accesos locales. |
| [Producción en Render](desarrollo/produccion-render.md) | Perfil público, variables, HTTPS, almacenamiento externo y comandos de despliegue. |
| [Cambio del dominio oficial](desarrollo/cambio-dominio.md) | Preparación, traslado desde el servidor anterior y reversión con los cupos gratuitos. |
| [Pruebas](desarrollo/pruebas.md) | Suites de API, JavaScript, navegador y ejecución aislada en CI. |
| [Integridad del stock](desarrollo/integridad-stock.md) | Restricciones, diagnóstico y comprobaciones de concurrencia. |
| [Rendimiento en Neon](desarrollo/rendimiento-neon.md) | Reutilización de conexiones, consultas y carga del contenido de correos. |
| [Aplicación de escritorio](desarrollo/escritorio.md) | Ejecución local y compilación de SmartStock.exe para Windows. |
| [Docker multiempresa](desarrollo/docker.md) | Instalación local reproducible con tres bases PostgreSQL y cuentas de demostración. |
| [Estado de las versiones](desarrollo/estado-versiones.md) | Mejoras reunidas en main y preparación del cambio del sitio publicado. |

## Módulos y operaciones

| Documento | Contenido |
| --- | --- |
| [Bodegas](modulos/bodegas.md) | Administración de bodegas y existencias. |
| [Transferencias](modulos/transferencias.md) | Traslado de productos entre bodegas y consistencia de saldos. |
| [Lotes y FIFO](modulos/lotes-fifo.md) | Recepciones con costo, consumo por antigüedad, mermas y migración de saldos anteriores. |
| [Ubicaciones físicas](modulos/ubicaciones-fisicas.md) | Pasillos, estanterías, niveles y ubicaciones. |
| [Reportes y Kardex](modulos/reportes-inventario.md) | Informes, filtros, exportaciones y conciliación. |
| [Auditoría del panel central](modulos/auditoria.md) | Filtros, identidad histórica, detalle de cambios y exportaciones autorizadas. |
| [Códigos de producto](modulos/codigos-producto.md) | Consulta y registro a partir de SKU, barras y QR. |
| [Alertas SMS](modulos/alertas-sms.md) | Integración de Twilio, estados y configuración. |
| [Gestión de SMS pendientes](modulos/gestion-sms-pendientes.md) | Revisión, procesamiento y cancelación desde la interfaz. |
| [Cuenta de contacto y Zoho](modulos/contacto-zoho.md) | Acceso al buzón y conexión de correo. |
| [Permisos y soporte](modulos/permisos-soporte.md) | Perfiles internos y acceso temporal autorizado por el cliente. |

La documentación de módulos describe el código de su rama. El [estado de las versiones](desarrollo/estado-versiones.md) distingue la versión integrada del despliegue que utiliza el sitio oficial.

## Antecedentes

[Historial de integraciones](historial/README.md) conserva las notas de avances anteriores. Sus comandos y estados corresponden al momento de aquella integración.

## Documentación junto a sus archivos

- [Pruebas JavaScript](../tests/js/README.md): cobertura y requisitos del DOM de pruebas.
- [Datos territoriales](../esquema_multiempresa/datos/README.md): procedencia del catálogo de regiones y comunas.
- [Mapa de pruebas](../tests/README.md): ubicación de las suites.
