# Historial de auditoría de SmartStock

El panel /sistema/auditoria/ permite consultar la plataforma o una empresa autorizada. La selección no agrega bases ni habilita acceso a otra empresa. Las lecturas y escrituras siguen utilizando las conexiones de Neon.

## Actualización en Windows

Esta rama se apoya en mejora/rendimiento-neon. Con el servidor detenido, desde CMD:

    git fetch origin
    git switch mejora/auditoria-investigacion
    git pull --ff-only
    call .venv\Scripts\activate.bat
    python -m pip install -r requirements-web.txt
    python manage.py migrate core --database=central --settings=esquema_multiempresa.migracion
    python manage.py migrate core --database=ferreteria --settings=esquema_multiempresa.migracion
    python manage.py migrate core --database=repuestos --settings=esquema_multiempresa.migracion
    python manage.py check --settings=esquema_multiempresa.web
    python manage.py runserver 127.0.0.1:8000 --settings=esquema_multiempresa.web

La migración core.0006 incorpora datos de identidad histórica, empresa, atención, módulo, operación, resultado, cambios e índices para ordenar el historial. Se aplica en las tres bases de Neon antes de iniciar la versión nueva. No reconstruye resultados, roles ni cambios de eventos antiguos.

## Consulta

- Filtros por texto, identidad histórica, acción, módulo, resultado y fechas de Santiago; accesos rápidos a hoy, siete y treinta días.
- Vistas Todos, Cambios, Accesos y Consultas. Conservan los filtros y la atención de soporte seleccionada.
- Veinticinco registros por página, números de página y vista adaptable a celular.
- La agrupación opcional reúne consultas consecutivas del mismo actor y módulo en un intervalo de cinco minutos dentro de la página. No fusiona registros en la base ni modifica los conteos. Cada grupo se puede desplegar y cada evento tiene su detalle.
- El detalle conserva la descripción original. Los datos históricos ausentes aparecen como «No registrado». Cuando no hay una identidad capturada, se aclara si la información procede de la cuenta asociada actual.

## Eventos nuevos

Los registros emitidos por las utilidades de auditoría guardan una instantánea de nombre, correo, perfil y origen del actor. Un identificador central no se utiliza como FK de usuario en una base de empresa. La eliminación posterior de una cuenta conserva la identidad capturada en el evento.

Se capturan campos explícitamente permitidos al guardar fichas de empresa y cuentas desde el panel, decisiones de permisos y cambios de estado de soporte y seguimiento del buzón. No se copian formularios, hashes, contraseñas, tokens, credenciales de Zoho ni texto de correos o borradores al registro de cambios. Una operación que no registra valores anteriores/nuevos lo indica en el detalle.

Los resultados distinguen solicitudes, operaciones completadas, fallidas y denegadas. Las consultas registradas por el panel se identifican como solicitudes de consulta: una respuesta HTML, por sí sola, no prueba que toda dependencia externa haya respondido. Los eventos anteriores mantienen resultado vacío.

## Alcance y exportación

El superusuario puede ver la auditoría central completa. Plataforma conserva su historial de gestión y las atenciones visibles. Soporte conserva sus eventos y las atenciones asignadas; la consulta de auditoría de una empresa exige autorización vigente, igual que antes.

Solo superusuario y plataforma pueden exportar dentro de su alcance. Para una empresa se necesitan, en la misma atención, los permisos «Consultar auditoría» y «Exportar reportes o auditoría CSV / PDF». Una autorización de lectura no habilita la exportación.

El CSV incluye todos los eventos filtrados, independientemente de la página o la agrupación. Lee lotes de hasta 200 registros con la base fijada y comprueba de nuevo el perfil y la autorización antes de cada lote. Si se revoca el acceso o falla la lectura, el archivo contiene un aviso de interrupción y no presenta la descarga como completa. La solicitud y el resultado de la exportación se registran por separado con el mismo identificador.

«Imprimir / PDF» abre un documento preparado para impresión y permite guardarlo como PDF desde el navegador. Admite hasta 5.000 eventos y solicita acotar filtros o usar CSV si se supera el límite. Antes de mostrarlo se comprueba de nuevo que todos sus eventos sigan dentro del alcance. No permite editar ni eliminar eventos.
