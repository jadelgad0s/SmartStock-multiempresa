# Recorrido de revisión académica

Esta guía permite recorrer el repositorio durante la presentación. El [README principal](../README.md) resume el alcance y la [arquitectura](desarrollo/arquitectura.md) explica sus componentes.

## Qué resuelve SmartStock

SmartStock ayuda a una PYME a conocer sus existencias por bodega, registrar entradas y salidas, trasladar mercadería, controlar mermas y revisar su historial. La versión multiempresa mantiene una base operativa por empresa y una central para el directorio, las cuentas internas y el soporte. El alcance es inventario; no incluye ventas ni facturación.

## Dónde encontrar la implementación

| Tema que se revisa | Código principal | Evidencia automatizada |
| --- | --- | --- |
| Productos, bodegas y existencias | [Modelos](../apps/productos/models.py) y [operaciones de stock](../apps/productos/stock.py) | [Integridad del stock](../apps/productos/test_integridad_stock.py) |
| Entradas, salidas y transferencias | [Movimientos](../apps/productos/views_movimientos.py) y [transferencias](../apps/productos/views_transferencias.py) | [Movimientos](../apps/productos/test_movimientos.py) y [transferencias](../apps/productos/test_transferencias.py) |
| Mermas y reportes | [Mermas](../apps/productos/views_mermas.py) y [reportes](../apps/productos/reportes.py) | [Mermas](../apps/productos/test_mermas.py) y [reportes](../apps/productos/test_reportes.py) |
| Roles de cada empresa | [Permisos](../apps/usuarios/permissions.py) | [Inicio por rol](../apps/usuarios/test_inicio_por_rol.py) |
| Separación entre empresas | [Enrutador de bases](../esquema_multiempresa/router.py) y [contexto de empresa](../apps/core/empresa.py) | [Aislamiento y operaciones](../esquema_multiempresa/pruebas_web.py) |
| Entrada común y sesiones | [Acceso](../esquema_multiempresa/acceso.py) | [Inicio de sesión](../esquema_multiempresa/pruebas_login.py) |
| Equipo interno y soporte autorizado | [Guía de permisos](modulos/permisos-soporte.md) | [Panel central](../esquema_multiempresa/pruebas_sistema.py) y [soporte](../esquema_multiempresa/pruebas_soporte.py) |
| Pantallas y comportamiento del navegador | [Plantillas](../templates/) y [JavaScript](../static/js/) | [Pruebas JavaScript](../tests/js/) y [recorridos de Chrome](../esquema_multiempresa/selenium_suite.py) |

Las pruebas Python permanecen junto al componente que verifican. El [mapa de pruebas](../tests/README.md) y la [guía de ejecución](desarrollo/pruebas.md) explican esta distribución.

## Demostración de inventario y aislamiento

Utiliza las cuentas y los datos de ensayo preparados según la [instalación multiempresa](desarrollo/multiempresa.md).

1. Abre La Fragua y Punto Motor en pestañas separadas. Identifica la empresa y el rol de cada cuenta.
2. Usa un producto de ensayo con el mismo SKU en ambas empresas. Parte con stock cero y registra una entrada de 15 unidades en La Fragua y otra de 4 en Punto Motor.
3. Registra una salida de 3 en La Fragua. Comprueba que su saldo queda en 12 y que Punto Motor conserva 4.
4. Abre el Kardex y el historial de movimientos de ambas empresas para contrastar las operaciones.
5. Con cuentas de los roles preparados, comprueba sus pantallas iniciales y las acciones disponibles. La revisión de permisos también está cubierta por las pruebas del servidor.
6. Si se demuestra soporte, abre una atención, solicita un permiso, apruébalo desde la cuenta del cliente y revócalo al terminar. Comprueba que la consulta posterior queda bloqueada.

Los SMS están desactivados en el perfil local de ensayo. La demostración de existencias, historial y permisos se puede realizar con esa configuración.

## Versión y resultados que se presentan

Comprueba la rama y el commit utilizados, y consulta el [estado de las versiones](desarrollo/estado-versiones.md). Las mejoras que todavía estén en propuestas abiertas pueden no estar en main ni en el sitio publicado.

Los resultados de las comprobaciones están en [GitHub Actions](https://github.com/jadelgad0s/SmartStock-multiempresa/actions). Selecciona la ejecución del commit que se revisa: hay flujos de PostgreSQL, Chrome y ejecutable de Windows. La guía de pruebas permite repetir las suites con bases desechables, sin credenciales de Neon.

Los antecedentes del proyecto original están separados en [historial](historial/README.md). Las instrucciones actuales se encuentran en el [índice de documentación](README.md).
