# Cuenta de contacto y bandeja de Zoho Mail

El perfil **Contacto** pertenece exclusivamente a `contacto@smartstockchile.cl` en la base central. No aparece en el selector de perfiles del equipo y no se crea en las empresas. El correo es fijo: crear un rol con el mismo nombre o marcar una cuenta como staff no concede este acceso. El login requiere la cuenta central activa, su rol activo, el correo exacto y ausencia de privilegios de superusuario.

## Habilitar la cuenta

Con el servidor detenido, actualiza la rama e instala las migraciones:

```bat
call .venv\Scripts\activate.bat
python -m pip install -r requirements-web.txt
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

## Conectar el buzón desde SmartStock

Crear la dirección de correo y enviarle un mensaje no autoriza automáticamente a la aplicación. La contraseña de SmartStock tampoco conecta Zoho. Antes de la primera consulta, los indicadores muestran **—** y una sola tarjeta indica que la conexión está pendiente.

1. Entra como **superusuario técnico** y abre **Cuenta de contacto → Conectar Zoho Mail**. La pantalla muestra si falta la autorización, si existe una configuración por comprobar o si hubo un error. Una configuración existente permite **Comprobar y actualizar bandeja**.
2. Abre [Zoho API Console](https://api-console.zoho.com/) con la cuenta cuyo buzón principal es `contacto@smartstockchile.cl`. Crea un **Self Client**. Selecciona el centro de datos correspondiente; para una cuenta en el centro de EE. UU. usa **Estados Unidos (.com)**.
3. Copia **Client ID** y **Client Secret** en el formulario de SmartStock. No se necesita la contraseña del correo y no hay que compartir credenciales en el chat.
4. En **Generate Code**, solicita estos permisos:

   ```text
   ZohoMail.accounts.READ,ZohoMail.messages.READ,ZohoMail.messages.CREATE
   ```

5. Genera un código, pégalo en **Código de autorización de Zoho** y pulsa **Autorizar y cargar correos** antes de que caduque. Si caduca, genera otro.
6. SmartStock comprueba que la cuenta es la de contacto, guarda la autorización cifrada e incorpora hasta 100 correos. La lectura debe estar permitida para la cuenta y su organización. La comprobación no envía ningún correo.
7. Inicia sesión como **Contacto** y abre la bandeja. **Actualizar bandeja** consulta Zoho aunque una actualización automática haya ocurrido hace pocos segundos. Al fallar, conserva la vista y explica la causa. Para consultar desde consola sin enviar correos:

   ```bat
   python manage.py sincronizar_contacto --settings=esquema_multiempresa.web
   ```

La autorización web se guarda cifrada en `buzon_contacto`, con Fernet y una clave derivada para este propósito de `SECRET_KEY`. No se devuelve al navegador ni se rellena en formularios. Conserva `SECRET_KEY` privado y estable; las instancias que compartan esta central deben poder descifrar esa autorización. Al rotar la clave, conserva temporalmente la anterior en `SECRET_KEY_FALLBACKS` o vuelve a conectar el buzón. No se cambia la clave de Django ni se invalidan sesiones al conectar Zoho.

### Configuración anterior mediante variables

Sigue admitiéndose `ZOHO_CONTACTO_CLIENT_ID`, `ZOHO_CONTACTO_CLIENT_SECRET`, `ZOHO_CONTACTO_REFRESH_TOKEN` y `ZOHO_CONTACTO_DC` en el entorno privado del servidor. Se utiliza cuando no hay una autorización guardada desde SmartStock. La pantalla del superusuario identifica el origen y permite sustituirla con una autorización nueva.

El comando anterior `conectar_zoho_contacto` continúa disponible para canjear un código Self Client usando Client ID y Client Secret del entorno. Guarda el refresh token en `.env`, sin mostrarlo en terminal; ese método requiere reiniciar el servidor. En un despliegue, las variables se configuran en el proveedor de hosting, no en un archivo efímero. Los correos de recuperación mantienen su configuración existente.

### Si un correo de prueba no aparece

- Comprueba primero que el correo llegó a **Recibidos (Inbox)** en Zoho Mail. Si una regla lo movió a otra carpeta o quedó en Spam, muévelo a Recibidos y actualiza SmartStock.
- En el superusuario, abre **Cuenta de contacto → Revisar conexión de Zoho** y pulsa **Comprobar y actualizar bandeja**. Si falta autorización, conecta el buzón en esa misma pantalla.
- El mensaje distingue falta de autorización, permisos, caducidad, problemas de red y límites temporales de Zoho. Una pestaña de contacto muestra el error concreto; no convierte un fallo en una bandeja vacía.
- Si Zoho devuelve cero correos de Recibidos, la pantalla indica **No hay correos importados**, sin afirmar que todo el buzón esté vacío. Si todavía no hubo consulta, los indicadores muestran **—**. Los correos ya guardados permanecen visibles si hay un fallo posterior.
- Una autorización ya guardada sigue siendo válida tras actualizar el código de consulta; no hay que generar otro código OAuth por este cambio.

## Funcionamiento y límites

La bandeja visible consulta Zoho cada minuto, con sesión y CSRF. Avisa cuando hay correos nuevos —también si los incorporó otra pestaña o el comando— y ofrece actualizar la vista; no recarga un borrador mientras se escribe. Para consultar sin una pestaña abierta puede ejecutarse `sincronizar_contacto` periódicamente en el servidor. Esta tarea solo consulta: nunca manda respuestas automáticas.

Cada actualización incorpora hasta **100 correos recientes de Recibidos (Inbox)**, leídos o sin leer. Se consulta `/messages/search` con `in:Inbox::groupResult:false`, en lugar de una lista `/messages/view` sin una carpeta seleccionada. Se envía la fecha actual en `receivedTime`: el valor predeterminado de la API de búsqueda deja fuera los dos minutos más recientes. La importación admite las marcas de tiempo `receivedtime` y `receivedTime` de las respuestas de Zoho. Solo se utiliza el permiso `messages.READ` ya autorizado; no se pide acceso adicional para listar carpetas. Spam, Papelera, Enviados y los mensajes de otras carpetas no se importan a esta bandeja; los que ya se habían importado permanecen en SmartStock.

**Cargar correos anteriores** continúa con otro lote de Recibidos. Las consultas de recientes conservan el avance por los anteriores; si llega un lote completo de 100 correos nuevos, el recorrido histórico vuelve al siguiente lote para poder recuperarlos. Es una consulta paginada, no una réplica instantánea de todo el buzón. Los IDs de cuenta y mensaje evitan duplicados. Los estados, notas, lectura y borradores son locales a SmartStock y no cambian las carpetas o banderas de Zoho.

El cuerpo del mensaje se recupera al abrirlo y se presenta como texto. No se ejecuta HTML ni se cargan imágenes remotas. Los adjuntos se consultan desde **Abrir Zoho Mail**. La vista **Enviados** muestra las respuestas confirmadas realizadas desde SmartStock, con búsqueda y paginación; no pretende mostrar todos los enviados desde otros clientes de Zoho. Las respuestas se guardan primero como borradores locales y se envían solo al pulsar **Enviar respuesta**, desde el remitente fijo al autor del correo. No hay envío masivo, reenvíos ni destinatarios libres.

Los guardados detectan cambios desde otra pestaña. El envío reclama el borrador una sola vez. Ante un timeout o una respuesta ambigua, queda **Revisar en Zoho** y se bloquean nuevas respuestas hasta comprobar el resultado en Enviados. Después se registra **Comprobé que se envió** o **Comprobé que no se envió**. Un proceso interrumpido queda Enviando y permite esa revisión pasados tres minutos. No se reintenta automáticamente una operación que podría haberse completado.

La migración `empresas.0007_contacto_y_bandeja` agrega el rol central y cuatro tablas: `buzon_contacto`, `mensajes_contacto`, `notas_contacto` y `respuestas_contacto`. La central pasa a **22 tablas previstas**; las empresas conservan **46**. La migración `empresas.0008_conexion_buzon_contacto` añade al buzón el estado de conexión, el diagnóstico y la autorización cifrada; no cambia las bases de empresas ni aumenta el número de tablas. Ninguna credencial se guarda en texto plano. La nueva bandeja no crea relaciones de usuarios entre bases.

Referencias oficiales: [OAuth Self Client](https://www.zoho.com/developer/oauth/self-client/authorization-code-flow.html), [cuentas del usuario](https://www.zoho.com/mail/help/api/get-all-users-accounts.html), [lista de correos](https://www.zoho.com/mail/help/api/get-emails-list.html), [búsqueda de correos](https://www.zoho.com/mail/help/api/get-search-emails.html), [sintaxis de búsqueda](https://www.zoho.com/mail/help/search-syntax.html), [contenido](https://www.zoho.com/mail/help/api/get-email-content.html) y [respuestas](https://www.zoho.com/mail/help/api/post-reply-to-an-email.html).
