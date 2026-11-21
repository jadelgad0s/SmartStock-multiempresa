# Equipo interno y soporte autorizado

La aplicación distingue el equipo interno de SmartStock de los usuarios operativos de cada empresa. Ni siquiera un superusuario central obtiene automáticamente acceso al inventario de los clientes. Los perfiles y su matriz de funciones se describen en [multiempresa.md](multiempresa.md#perfiles-del-equipo-de-smartstock).

## Actualizar una instalación existente

Detén el servidor. Desde la rama de esta actualización, en CMD y con el entorno activado:

```bat
python manage.py migrate --database=central --settings=esquema_multiempresa.migracion
python manage.py runserver 127.0.0.1:8000 --settings=esquema_multiempresa.web
```

`empresas.0009_soporte_temporal` agrega `atenciones_soporte` y `accesos_soporte` exclusivamente en la central. La central pasa a tener 24 tablas y las empresas conservan 46. No cambia las contraseñas, los perfiles existentes ni los datos de inventario. Los permisos generales de consulta del equipo se sustituyen por este flujo.

## Solicitar y aprobar acceso

1. El administrador de plataforma o superusuario abre **Atenciones de soporte → Nueva atención**, selecciona empresa, responsable, asunto y descripción. El administrador del cliente también puede crear una consulta desde **Soporte de SmartStock**; queda pendiente de asignación por el equipo.
2. El técnico asignado abre su atención y solicita los permisos concretos que necesita. Debe indicar el motivo y elegir 15, 30 o 60 minutos. Abrir una atención todavía no concede acceso. Solo puede quedar una solicitud pendiente por atención.
3. El administrador de la empresa recibe una notificación y abre **Soporte de SmartStock**. Revisa responsable, motivo, permisos y duración; autoriza o rechaza la solicitud. El equipo interno no tiene un botón para autorizarse.
4. Una vez aprobada, el técnico vuelve a abrir la atención. Aparecen las consultas autorizadas, un aviso con la empresa y el vencimiento, y los enlaces correspondientes en el menú. Los permisos se comprueban en el servidor en cada petición.
5. El cliente puede **Revocar acceso ahora** o cerrar la atención. El técnico puede retirar su solicitud o finalizarla con un resultado. Reasignar la atención, cerrarla o suspender la empresa revoca sus accesos; reabrir el servicio o volver a asignar el mismo técnico no los recupera. El vencimiento no necesita una tarea programada.

Cada atención mantiene una sola autorización efectiva. Autorizar una solicitud nueva reemplaza y revoca los permisos anteriores de esa atención; revocar la nueva no reactiva una autorización previa. Rechazar una renovación conserva únicamente el permiso anterior hasta su propio vencimiento o revocación.

En desarrollo, un administrador de La Fragua abre `http://la-fragua.localhost:8000/soporte/`. Punto Motor utiliza `http://punto-motor.localhost:8000/soporte/`. Cada página utiliza la empresa del host y la sesión; un ID enviado por formulario no permite aprobar solicitudes de otra empresa.

## Permisos separados

Las lecturas se eligen por módulo: resumen, catálogo y stock, bodegas, movimientos, transferencias, mermas, reportes, alertas SMS, auditoría y usuarios. Consultar un módulo no permite registrar operaciones ni modificar existencias.

**Recuperar acceso** exige solicitar también la consulta de usuarios. Envía un enlace al correo ya registrado; no muestra el enlace al técnico, no permite elegir otra dirección y limita las solicitudes repetidas durante dos minutos.

**Gestionar usuarios** solo está disponible para superusuario técnico y administrador de plataforma, con aprobación adicional del cliente. Permite altas, cambios de nombre, teléfono, rol y estado. Los usuarios nuevos reciben una invitación para establecer su contraseña. El equipo no puede imponer claves, cambiar el correo de una cuenta existente, crear usuarios con flags técnicos ni dejar a la empresa sin un administrador activo con acceso.

**Exportar reportes** solo está disponible para superusuario técnico y administrador de plataforma. Requiere solicitar también Reportes y la aprobación explícita del permiso Exportar. Soporte técnico no puede exportar aunque intente una URL directa o cambie los campos del formulario.

Los destinatarios de SMS se muestran parcialmente ocultos. El diagnóstico de integraciones presenta estados generales; sus credenciales y configuración siguen reservadas al superusuario. El contenido de `contacto@smartstockchile.cl` solo está disponible para la cuenta Contacto.

## Primer administrador de una empresa

Desde la ficha, **Invitar administrador** habilita el acceso inicial cuando todavía no hay cuentas con contraseña utilizable. Se envía exclusivamente al contacto principal registrado y exige confirmar su verificación. El técnico no escribe la contraseña ni recibe el enlace.

El usuario invitado establece su clave desde un enlace de una hora, vinculado a la empresa. Reenviar durante el límite de dos minutos conserva el enlace anterior. Si falla el envío, la cuenta permanece preparada para reintentar. Debe existir un backend de correo funcional en la instalación; el alta en la interfaz no configura el servicio de correo.

Una cuenta que ya fue utilizada, aunque esté inactiva o haya cambiado de rol, impide usar esta vía de habilitación inicial como sustituto de la recuperación normal. Si ya existe un administrador activo, los cambios adicionales se gestionan desde la empresa o mediante una atención autorizada.

## Auditoría y aislamiento

Las solicitudes, decisiones, cambios de responsable, cierres, recuperaciones y exportaciones registran al actor, empresa y atención. Las consultas autorizadas incluyen el motivo. Las decisiones del cliente conservan su ID y correo como datos históricos, sin relacionar usuarios de bases distintas.

Superusuario ve la auditoría interna completa; plataforma ve empresas, atenciones y sus propios eventos; soporte ve sus atenciones asignadas y actividad propia. Las notificaciones son privadas por usuario. Desactivar la cuenta del técnico o su rol bloquea los accesos existentes.

Las pruebas usan bases desechables, correo en memoria y permisos explícitos de prueba. Incluyen IDs repetidos entre bases, aprobación y revocación desde el cliente, vencimiento, reasignación, suspensión, formularios manipulados, invitaciones, exportaciones y decisiones concurrentes en PostgreSQL. La prueba de Chrome recorre la aprobación y revocación en dos pestañas, incluidos los controles móviles.
