# Carga de páginas con las bases en Neon

El servidor `esquema_multiempresa.web` sigue utilizando las tres conexiones de Neon: central, ferretería y repuestos. La actualización no copia sus registros a una base local ni crea una conexión alternativa. Conserva la validación de host, nombre de base y SSL de `local_settings.py`.

## Actualización en Windows

Detén el servidor y, desde el proyecto en CMD:

```bat
call .venv\Scripts\activate.bat
python -m pip install -r requirements-web.txt
python manage.py check --settings=esquema_multiempresa.web
python manage.py runserver 127.0.0.1:8000 --settings=esquema_multiempresa.web
```

La dependencia `psycopg[pool]` está incluida en requirements-web.txt; por eso es necesario actualizar los requisitos. La optimización de conexiones no requiere una migración propia. La versión consolidada incluye core.0006 de auditoría: sigue la [guía de actualización](../modulos/auditoria.md) antes de iniciar una instalación anterior.

## Qué se optimiza

- Cada alias mantiene un pool independiente de conexiones a su misma base de Neon, compartido entre los hilos del proceso. Al terminar una petición, Django devuelve la conexión para la siguiente. `CONN_MAX_AGE=0` es intencional cuando se utiliza este pool.
- Cada pool crece hasta cuatro conexiones, empieza vacío y libera conexiones ociosas. Se comprueba su estado antes de reutilizarlas. Los comandos de migración y el perfil de solo lectura conservan sus conexiones directas.
- El resumen de una empresa calcula sus indicadores de usuarios en una consulta agregada. La lista de empresas y los permisos de consulta se reutilizan únicamente dentro de una petición; la siguiente vuelve a la base. No se guardan autorizaciones vigentes en una caché compartida.
- Las páginas operativas entregan los permisos que Django acaba de verificar en el propio HTML. El navegador evita repetir inmediatamente la misma petición de navegación. Al recuperar una página del historial vuelve a consultar permisos actuales. Las API mantienen sus comprobaciones de acceso.
- La bandeja reutiliza la configuración de buzón leída durante esa petición y agrupa los contadores. El detalle reutiliza las respuestas ya consultadas.
- Abrir un correo muestra su página y editor sin esperar a Zoho. El contenido se solicita por separado, aparece dentro del mensaje y queda guardado en la base central de Neon. Si Zoho falla se conserva el resumen y se puede reintentar; no se presenta un mensaje vacío como descargado. No se reenvían correos automáticamente.
- Durante la espera de Zoho, el servidor devuelve al pool la conexión que ya no necesita, para dejar capacidad a las demás páginas.

Los pools conservan conexiones, no una copia de los datos. Cada consulta y cada guardado sigue utilizando PostgreSQL en Neon. Los permisos se revalidan entre peticiones y la revocación sigue bloqueando el acceso en la siguiente solicitud.

## Medir desde el computador de Javier

Con el entorno activado:

```bat
python manage.py medir_conexion_neon --settings=esquema_multiempresa.web
```

El comando muestra el tiempo de la primera conexión y la mediana de cinco consultas pequeñas por alias, cerrando cada préstamo al pool entre consultas. Solo utiliza `SELECT current_database()` y `SELECT 1`: no consulta inventarios, no modifica registros ni muestra contraseñas o URLs. La primera conexión puede incluir la reactivación del cómputo de Neon.

Esta medición permite distinguir el coste de conexión y red del trabajo de una página. Los tiempos dependen de Internet, la región de Neon y el estado de su cómputo; el número de consultas reducido no equivale por sí solo a una garantía de segundos de carga.
