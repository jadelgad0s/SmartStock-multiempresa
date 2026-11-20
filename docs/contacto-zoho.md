# Cuenta de contacto y bandeja de Zoho Mail

El perfil **Contacto** pertenece exclusivamente a `contacto@smartstockchile.cl` en la base central. No aparece en el selector de perfiles del equipo y no se crea en las empresas. El correo es fijo: crear un rol con el mismo nombre o marcar una cuenta como staff no concede este acceso. El login requiere la cuenta central activa, su rol activo, el correo exacto y ausencia de privilegios de superusuario.

## Habilitar la cuenta

Con el servidor detenido, actualiza la rama e instala las migraciones:

```bat
call .venv\Scripts\activate.bat
python manage.py migrate --database=central --settings=esquema_multiempresa.migracion
python manage.py runserver 127.0.0.1:8000 --settings=esquema_multiempresa.web
```

Entra con el superusuario y abre **Cuenta de contacto** en el menú. Completa nombre, apellido y una contraseña de SmartStock. La cuenta se crea con correo y rol fijos; este formulario también permite suspenderla. Ninguna migración crea una contraseña o transforma cuentas existentes automáticamente. Si hay variantes del correo en la central, unifícalas primero. Si ese correo se utilizó para un superusuario, cambia primero el correo de ese superusuario desde Configuración, manteniendo otra cuenta técnica con acceso.

Al iniciar sesión con el correo reservado, el usuario abre `/contacto/bandeja/`. Puede:

- Consultar correos, buscar por remitente, asunto o resumen y revisar los que están sin leer.
- Clasificar consultas de acceso, uso, incidencias u otros temas.
- Marcar consultas pendientes, en seguimiento o resueltas y fijar una fecha de seguimiento.
- Guardar notas internas y borradores, revisar el texto guardado y enviar una respuesta al remitente.
- Ver su campana privada y modificar sus nombres, teléfono y contraseña desde el avatar.

No puede consultar inventarios, gestionar empresas o usuarios, asignar perfiles ni entrar a Django. El equipo técnico y los usuarios de empresas no pueden abrir esta bandeja; el superusuario administra la cuenta desde su apartado exclusivo. La contraseña de SmartStock es independiente del acceso OAuth a Zoho.

## Conectar el buzón real

Se utiliza la **API de Zoho Mail por HTTPS**, sin depender de puertos IMAP o SMTP. Hasta completar la conexión, la pantalla indica que el buzón está pendiente; no contiene correos de demostración ni envíos simulados.

1. Inicia sesión en [Zoho API Console](https://api-console.zoho.com/) con la cuenta que posee el buzón principal `contacto@smartstockchile.cl`. Crea un **Self Client**. Usa la consola correspondiente al centro de datos de tu cuenta.
2. Guarda su Client ID y Client Secret en el archivo local `.env` junto a `manage.py`. No compartas sus valores en capturas ni los subas al repositorio:

   ```dotenv
   ZOHO_CONTACTO_CLIENT_ID=valor_privado
   ZOHO_CONTACTO_CLIENT_SECRET=valor_privado
   ZOHO_CONTACTO_DC=com
   ```

   `com` corresponde al centro de EE. UU. También se admiten `eu`, `in`, `com.au` y `jp`; deben coincidir con el buzón y el cliente OAuth.
3. En **Generate Code**, solicita únicamente estos permisos:

   ```text
   ZohoMail.accounts.READ,ZohoMail.messages.READ,ZohoMail.messages.CREATE
   ```

4. Genera el código y ejecuta inmediatamente:

   ```bat
   python manage.py conectar_zoho_contacto --settings=esquema_multiempresa.web
   ```

   El comando pide el código de forma oculta, lo canjea y comprueba que corresponde al buzón de contacto. Guarda `ZOHO_CONTACTO_REFRESH_TOKEN` en `.env`, conservando las otras variables. No muestra tokens en la terminal y no envía correos. El código tiene una vigencia corta; si caduca, genera otro. El acceso a la API debe estar permitido para esa cuenta y su organización.
5. Reinicia el servidor. Entra como contacto y pulsa **Actualizar bandeja**. Para comprobar la lectura desde consola, sin enviar correos:

   ```bat
   python manage.py sincronizar_contacto --settings=esquema_multiempresa.web
   ```

En un despliegue, configura `ZOHO_CONTACTO_CLIENT_ID`, `ZOHO_CONTACTO_CLIENT_SECRET`, `ZOHO_CONTACTO_REFRESH_TOKEN` y `ZOHO_CONTACTO_DC` como variables privadas del servidor y reinicia la aplicación. No dependas de un `.env` creado en un disco efímero. Los correos de recuperación de contraseña mantienen su configuración existente.

## Funcionamiento y límites

La bandeja visible consulta Zoho cada minuto, con sesión y CSRF. Avisa cuando hay correos nuevos y ofrece actualizar la vista; no recarga un borrador mientras se escribe. Para consultar sin una pestaña abierta puede ejecutarse `sincronizar_contacto` periódicamente en el servidor. Esta tarea solo consulta: nunca manda respuestas automáticas.

Cada actualización incorpora hasta **100 correos recientes**, incluidos los archivados y excluidos los enviados. **Cargar correos anteriores** continúa con otro lote. Las consultas de recientes conservan el avance por los anteriores; si llega un lote completo de 100 correos nuevos, el recorrido histórico vuelve al siguiente lote para poder recuperarlos. Es una consulta paginada, no una réplica instantánea de todo el buzón. Los IDs de cuenta y mensaje evitan duplicados. Los estados, notas, lectura y borradores son locales a SmartStock y no cambian las carpetas o banderas de Zoho.

El cuerpo del mensaje se recupera al abrirlo y se presenta como texto. No se ejecuta HTML ni se cargan imágenes remotas. Los adjuntos se consultan desde **Abrir Zoho Mail**. Las respuestas se guardan primero como borradores locales y se envían solo al pulsar **Enviar respuesta**, desde el remitente fijo al autor del correo. No hay envío masivo, reenvíos ni destinatarios libres.

Los guardados detectan cambios desde otra pestaña. El envío reclama el borrador una sola vez. Ante un timeout o una respuesta ambigua, queda **Revisar en Zoho** y se bloquean nuevas respuestas hasta comprobar el resultado en Enviados. Después se registra **Comprobé que se envió** o **Comprobé que no se envió**. Un proceso interrumpido queda Enviando y permite esa revisión pasados tres minutos. No se reintenta automáticamente una operación que podría haberse completado.

La migración `empresas.0007_contacto_y_bandeja` agrega el rol central y cuatro tablas: `buzon_contacto`, `mensajes_contacto`, `notas_contacto` y `respuestas_contacto`. La central pasa a **22 tablas previstas**; las empresas conservan **46**. No se guardan credenciales de Zoho en esas tablas. La nueva bandeja no crea relaciones de usuarios entre bases.

Referencias oficiales: [OAuth Self Client](https://www.zoho.com/developer/oauth/self-client/authorization-code-flow.html), [cuentas del usuario](https://www.zoho.com/mail/help/api/get-all-users-accounts.html), [lista de correos](https://www.zoho.com/mail/help/api/get-emails-list.html), [contenido](https://www.zoho.com/mail/help/api/get-email-content.html) y [respuestas](https://www.zoho.com/mail/help/api/post-reply-to-an-email.html).
