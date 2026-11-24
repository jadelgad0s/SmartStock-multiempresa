# Estado de las versiones

Referencia de publicación: 24 de noviembre de 2026.

## Repositorio y sitio publicado

El sitio https://smartstockchile.cl/ utiliza la versión multiempresa de este repositorio desde el 24 de noviembre de 2026. El servidor del repositorio anterior, [jadelgad0s/SmartStock](https://github.com/jadelgad0s/SmartStock), se conserva como recurso de reversión.

main es la referencia del código integrado. Esta consolidación reúne las mejoras funcionales recientes y conserva la organización documental. El README y las guías deben leerse junto con la rama que se esté revisando.

## Mejoras reunidas en esta versión

| Propuesta | Cambio |
| --- | --- |
| [PR #6](https://github.com/jadelgad0s/SmartStock-multiempresa/pull/6) | Rendimiento en Neon y mejoras acumuladas de auditoría y paneles. |
| [PR #10](https://github.com/jadelgad0s/SmartStock-multiempresa/pull/10) | Consulta de códigos únicamente en el catálogo de cada empresa. |
| [PR #12](https://github.com/jadelgad0s/SmartStock-multiempresa/pull/12) | Identidad de empresa en el acceso y ayuda de cuenta. |
| [PR #13](https://github.com/jadelgad0s/SmartStock-multiempresa/pull/13) | Transición de marca y selector después de validar las credenciales. |
| [PR #16](https://github.com/jadelgad0s/SmartStock-multiempresa/pull/16) | Perfil de producción multiempresa para Render y almacenamiento privado externo. |
| [PR #17](https://github.com/jadelgad0s/SmartStock-multiempresa/pull/17) | Comprobación explícita de las conexiones y del almacenamiento real. |
| [PR #18](https://github.com/jadelgad0s/SmartStock-multiempresa/pull/18) | Compatibilidad de las cargas de imágenes con Neon. |
| [PR #21](https://github.com/jadelgad0s/SmartStock-multiempresa/pull/21) | Configuración del dominio definitivo y procedimiento de traslado y reversión. |

Esta tabla identifica las propuestas de origen. Sus commits se conservan en el historial de integración.

El catálogo de una empresa consulta únicamente sus productos registrados. La guía de [códigos de producto](../modulos/codigos-producto.md) describe el alta manual de códigos nuevos y la búsqueda privada. El acceso incluye la identidad de la empresa y la transición después de validar las credenciales.

La [auditoría](../modulos/auditoria.md) incorpora identidad histórica y campos estructurados mediante core.0006; una instalación anterior debe aplicar esa migración en sus tres alias antes de iniciar esta versión. El [rendimiento en Neon](rendimiento-neon.md) utiliza psycopg[pool], incluido en requirements-web.txt.

## Despliegue público comprobado

El traslado se aplicó al servicio existente `smartstock-multiempresa-pruebas`, en Ohio, con plan Free. Su nombre identifica el recurso conservado del ensayo. Usa `infra/render-produccion.yaml`, `SS_DOMINIO_EMPRESAS=smartstockchile.cl`, las tres bases de `produccion-multiempresa` y el bucket privado `smartstock-imagenes`.

| Referencia | Valor |
| --- | --- |
| Commit publicado al realizar el traslado | 5792355ac08da94b21d1b0fbd77cc543da018af0 |
| Despliegue Render | dep-dc2hlnek1f9s7381q9q0 |
| Estado comprobado | live, finalizado el 24 de noviembre de 2026 |
| Dominio principal | https://smartstockchile.cl/ |
| Empresas | https://la-fragua.smartstockchile.cl/ y https://punto-motor.smartstockchile.cl/ |
| Actualizaciones automáticas | Desactivadas para código e infraestructura |

La comprobación pública confirmó HTTPS, `/salud/` con HTTP 200 y estado ok, la redirección de www al dominio principal y las pantallas de acceso con la marca correcta. El usuario había confirmado el acceso de ensayo desde la central. La comprobación funcional de las sesiones en los dominios definitivos se realiza con las cuentas existentes.

Antes de aplicar el plan, el usuario confirmó cero dominios utilizados de dos incluidos; el plan añadió el dominio principal y un comodín para las empresas. La clave privada, las conexiones y las credenciales del bucket se conservaron. La [guía de Render](produccion-render.md) describe la configuración activa y la [guía del traslado](cambio-dominio.md) conserva el procedimiento de reversión.

El perfil esquema_multiempresa.web usa localhost y la rama de pruebas de Neon. El perfil config.settings.production corresponde al servidor anterior.

El perfil esquema_multiempresa.production admite el dominio público y las entradas centrales autorizadas, con almacenamiento externo privado compatible con S3. Las integraciones de correo y SMS requieren su configuración propia.
