# Estado de las versiones

Referencia de organización: 23 de noviembre de 2026.

## Repositorio y sitio publicado

Este repositorio contiene la evolución multiempresa. El sitio https://smartstockchile.cl/ continúa vinculado al repositorio anterior, [jadelgad0s/SmartStock](https://github.com/jadelgad0s/SmartStock), hasta realizar el cambio de despliegue.

main es la referencia del código integrado. Esta consolidación reúne las mejoras funcionales recientes y conserva la organización documental. El README y las guías deben leerse junto con la rama que se esté revisando.

## Mejoras reunidas en esta versión

| Propuesta | Cambio |
| --- | --- |
| [PR #6](https://github.com/jadelgad0s/SmartStock-multiempresa/pull/6) | Rendimiento en Neon y mejoras acumuladas de auditoría y paneles. |
| [PR #10](https://github.com/jadelgad0s/SmartStock-multiempresa/pull/10) | Consulta de códigos únicamente en el catálogo de cada empresa. |
| [PR #12](https://github.com/jadelgad0s/SmartStock-multiempresa/pull/12) | Identidad de empresa en el acceso y ayuda de cuenta. |
| [PR #13](https://github.com/jadelgad0s/SmartStock-multiempresa/pull/13) | Transición de marca y selector después de validar las credenciales. |

Esta tabla identifica las propuestas de origen. Sus commits se conservan en el historial de integración.

El catálogo de una empresa consulta únicamente sus productos registrados. La guía de [códigos de producto](../modulos/codigos-producto.md) describe el alta manual de códigos nuevos y la búsqueda privada. El acceso incluye la identidad de la empresa y la transición después de validar las credenciales.

La [auditoría](../modulos/auditoria.md) incorpora identidad histórica y campos estructurados mediante core.0006; una instalación anterior debe aplicar esa migración en sus tres alias antes de iniciar esta versión. El [rendimiento en Neon](rendimiento-neon.md) utiliza psycopg[pool], incluido en requirements-web.txt.

## Antes de publicar la versión multiempresa

El siguiente paso es preparar un perfil de producción multiempresa, configurar los dominios y las conexiones privadas de Neon y validar el despliegue en un entorno temporal antes de cambiar el servicio público.

El perfil esquema_multiempresa.web usa localhost y la rama de pruebas de Neon. El perfil config.settings.production corresponde al despliegue anterior; no sustituye la preparación multiempresa.

Los archivos subidos necesitan almacenamiento persistente además de las bases PostgreSQL. Las integraciones de correo y SMS requieren su configuración propia.
