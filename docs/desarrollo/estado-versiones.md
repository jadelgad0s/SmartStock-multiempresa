# Estado de las versiones

Referencia de organización: 23 de noviembre de 2026.

## Repositorio y sitio publicado

Este repositorio contiene la evolución multiempresa. El sitio https://smartstockchile.cl/ continúa vinculado al repositorio anterior, [jadelgad0s/SmartStock](https://github.com/jadelgad0s/SmartStock), hasta realizar el cambio de despliegue.

main es la referencia del código integrado. Una instalación local que haya combinado otras ramas puede contener mejoras adicionales. El README y las guías deben leerse junto con la rama que se esté revisando.

## Mejoras pendientes de consolidación en esta fecha

| Propuesta | Cambio |
| --- | --- |
| [PR #6](https://github.com/jadelgad0s/SmartStock-multiempresa/pull/6) | Rendimiento en Neon y mejoras acumuladas de auditoría y paneles. |
| [PR #10](https://github.com/jadelgad0s/SmartStock-multiempresa/pull/10) | Consulta de códigos únicamente en el catálogo de cada empresa. |
| [PR #12](https://github.com/jadelgad0s/SmartStock-multiempresa/pull/12) | Identidad de empresa en el acceso y ayuda de cuenta. |
| [PR #13](https://github.com/jadelgad0s/SmartStock-multiempresa/pull/13) | Transición de marca y selector después de validar las credenciales. |

Esta tabla es una referencia fechada. El estado actual de cada propuesta está en su enlace de GitHub.

La guía de códigos conserva el comportamiento anterior mientras la PR #10 no se integre. La consolidación de estas ramas y la preparación de producción son etapas posteriores a la organización documental del repositorio.

## Antes de publicar la versión multiempresa

Se debe reunir y comprobar la versión elegida, preparar un perfil de producción multiempresa, configurar los dominios y las conexiones privadas de Neon y validar el despliegue.

El perfil esquema_multiempresa.web usa localhost y la rama de pruebas de Neon. El perfil config.settings.production corresponde al despliegue anterior; no sustituye la preparación multiempresa.

Los archivos subidos necesitan almacenamiento persistente además de las bases PostgreSQL. Las integraciones de correo y SMS requieren su configuración propia.
