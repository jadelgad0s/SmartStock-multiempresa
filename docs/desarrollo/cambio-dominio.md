# Cambio de smartstockchile.cl a la versión multiempresa

Estado al 24 de noviembre de 2026: las pantallas públicas de las dos empresas y HTTPS están comprobados. El usuario confirmó el funcionamiento del acceso de prueba y mostró una sesión de La Fragua abierta desde la central. El traslado del sitio oficial continúa pendiente.

## Destinos

| Uso | Dirección definitiva |
| --- | --- |
| Entrada central | https://smartstockchile.cl/ |
| Ferretería La Fragua | https://la-fragua.smartstockchile.cl/ |
| Repuestos Punto Motor | https://punto-motor.smartstockchile.cl/ |

Se utiliza el servicio existente `smartstock-multiempresa-pruebas`, ID `srv-dc2b7safngtc73bbupu0`, en Ohio, con plan Free. Su nombre en el panel identifica el recurso ya preparado. El servidor anterior es `SmartStock`, ID `srv-dbb6vi1jfumc73eo2d00`, cuya dirección propia es `smartstock-fqky.onrender.com`.

[infra/render-produccion.yaml](../../infra/render-produccion.yaml) prepara el destino definitivo. Declarar el archivo en el repositorio no lo aplica: el Blueprint actual sigue usando `infra/render-pruebas.yaml`, con sincronización manual. Al cambiar de archivo, se debe revisar el plan que genere Render antes de aprobarlo.

La central y las empresas conservarán las bases actuales de `produccion-multiempresa` y el bucket ya comprobado. Solo cambia la variable pública `SS_DOMINIO_EMPRESAS` de `pruebas.smartstockchile.cl` a `smartstockchile.cl`. Las variables omitidas por el Blueprint se conservan: no cambiar `SECRET_KEY`, las conexiones privadas ni las credenciales de almacenamiento. Zoho depende de esa clave para conservar la autorización cifrada.

## 1. Preparar DNS sin mover el sitio principal

En Cloudflare, zona `smartstockchile.cl`, crear estos CNAME con proxy **DNS only**, nube gris y TTL automático. Si un nombre ya existe, comprobar su uso antes de sustituirlo.

| Tipo | Nombre | Destino |
| --- | --- | --- |
| CNAME | * | smartstock-multiempresa-pruebas.onrender.com |
| CNAME | _acme-challenge | smartstock-multiempresa-pruebas.verify.renderdns.com |
| CNAME | _cf-custom-hostname | smartstock-multiempresa-pruebas.hostname.renderdns.com |

En esta preparación se mantienen los registros actuales de `@`, `www` y los registros de prueba. Los registros de correo de Zoho —MX, SPF, DKIM y DMARC— continúan con sus valores actuales. Los tres registros nuevos todavía no completan el traslado: faltan las asociaciones en Render y el cambio del dominio principal.

## 2. Preparar la ventana de cambio

Guardar los valores actuales de los registros web `@` y `www`, su tipo y estado de proxy, y anotar las asociaciones de Custom Domains de ambos servicios. Son necesarios para una reversión.

Para conservar los dos cupos incluidos en Hobby, liberar las asociaciones anteriores antes de registrar las definitivas. No aprobar un plan que acumule el comodín de pruebas, el dominio principal anterior y el comodín definitivo. Verificar el contador de dominios en Billing durante el cambio; si aparece un cargo, detener las adiciones y revisar el cupo.

El cambio requiere retirar temporalmente el dominio principal de su servicio anterior. Desde ese retiro hasta que Render acepte las nuevas asociaciones, termine el despliegue y valide HTTPS, puede haber una interrupción del sitio. La coordinación entre Render y Cloudflare debe hacerse en una misma ventana, con ambos paneles abiertos.

## 3. Trasladar las asociaciones y la configuración

1. En el servicio multiempresa, sección Settings → Custom Domains, retirar únicamente `*.pruebas.smartstockchile.cl`. Confirmar que disminuya el contador de dominios; la dirección onrender.com seguirá disponible.
2. En el servicio anterior, retirar las asociaciones de `smartstockchile.cl` y su alias `www` si aparece. Conservar el servicio, su configuración y sus bases para la reversión.
3. En el Blueprint `smartstock-multiempresa-ensayo`, seleccionar `main` y `infra/render-produccion.yaml`, manteniendo `autoSync` desactivado. Solicitar un plan nuevo después de liberar las asociaciones anteriores. El plan debe modificar solamente el servicio multiempresa existente, añadir los dominios definitivos y actualizar `SS_DOMINIO_EMPRESAS`. Comprobar que mantiene Free y una instancia, y que conserva las variables privadas.
4. Revisar y aprobar ese plan. Si Render indica que un dominio sigue ocupado o la planificación falla, resolverlo y volver a planificar antes de aprobar.
5. En Cloudflare, actualizar los registros web `@` y `www` para que sean CNAME con destino `smartstock-multiempresa-pruebas.onrender.com`, proxy DNS only y TTL automático. Si `www` ya es un CNAME a `smartstockchile.cl`, puede conservarse porque seguirá al nuevo destino de la raíz. Evitar registros A/AAAA incompatibles en esos mismos nombres y conservar los registros de correo.
6. En Custom Domains del servicio multiempresa, verificar el dominio principal y el comodín. Los destinos de validación deben coincidir con las indicaciones que muestre Render.

Los registros de prueba se pueden retirar de Cloudflare después de confirmar el funcionamiento definitivo. La aplicación generará direcciones bajo `smartstockchile.cl`; los subdominios con `.pruebas.` dejarán de ser los accesos de las empresas.

## 4. Comprobar el resultado

- El despliegue multiempresa está live y sigue usando plan Free.
- Billing confirma un máximo de dos dominios incluidos, sin cargo por exceso.
- La central, La Fragua y Punto Motor responden por HTTPS; `/salud/` devuelve HTTP 200 en cada host.
- Desde la central, las cuentas existentes entran a la empresa correcta y muestran su marca, inventario y permisos.
- La conexión de Zoho sigue guardada y permite comprobar el buzón desde la central.

La verificación del buzón puede consultar correos existentes. Los mensajes de prueba, las recuperaciones por correo y las alertas SMS requieren decidir sus destinatarios antes de enviarlos.

## Reversión

Si el traslado falla, retirar de Render las asociaciones nuevas, volver a asociar el dominio principal al servicio `SmartStock` anterior y restaurar los registros web guardados de Cloudflare. Verificar su certificado y acceso.

Para recuperar también los accesos de ensayo, restaurar explícitamente `SS_DOMINIO_EMPRESAS=pruebas.smartstockchile.cl` en el servicio multiempresa y volver a asociar `*.pruebas.smartstockchile.cl`, respetando el cupo. Seleccionar otra vez `infra/render-pruebas.yaml` en el Blueprint y revisar un plan nuevo. Ese archivo omite envVars: cambiar solo su ruta no restaura la variable de dominio por sí mismo. No rotar claves ni restaurar bases por un problema de DNS.

Referencias del proveedor: [dominios de Render](https://render.com/docs/custom-domains), [DNS de Cloudflare](https://render.com/docs/configure-cloudflare-dns), [campos del Blueprint](https://render.com/docs/blueprint-spec).
