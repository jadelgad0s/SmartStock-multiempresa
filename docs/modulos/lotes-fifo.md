# Lotes y FIFO

Cada entrada registrada en **Movimientos** crea un lote del producto. Se guardan su código interno, referencia opcional, fecha y hora de recepción, cantidad inicial y costo unitario opcional en CLP. Un costo vacío se conserva como desconocido y se distingue de un costo cero. El precio de referencia del catálogo sigue siendo un dato propio del producto.

Al registrar una salida, el servidor consume las existencias de esa bodega en orden de recepción, desde el lote más antiguo. Si dos recepciones comparten fecha, desempata el identificador del lote. Una salida puede consumir varios lotes y su detalle permite revisar cantidades y costos originales. La fecha de recepción se registra en el servidor al confirmar la entrada.

## Uso

1. En **Movimientos**, escanea o busca el producto y selecciona **Entrada**. Completa bodega, cantidad y, si los conoces, referencia de lote y costo unitario. Confirma la recepción.
2. En **Catálogo**, abre el detalle del producto y pulsa **Ver lotes FIFO**. Se muestran las existencias por lote de la bodega seleccionada, incluidos los agotados, en páginas de 25 filas. Conservar la consulta de un producto inactivo permite revisar sus lotes.
3. Al confirmar una **Salida**, las unidades se asignan automáticamente a los lotes disponibles. **Ver detalle** muestra el desglose de esa operación.
4. Una **Transferencia** descuenta lotes del origen y aumenta esos mismos lotes en el destino. Conserva su fecha de recepción y costo, incluso si llegan después de lotes más recientes que ya estaban en el destino.
5. Una **Merma** utiliza FIFO automáticamente. Para identificar un daño concreto, despliega **Elegir un lote para esta merma**, consulta los lotes del producto y selecciona uno con unidades suficientes. Su detalle conserva el lote descontado.

Las ubicaciones físicas continúan siendo referencias del producto. Las cantidades FIFO se distribuyen entre bodegas. Las fechas de vencimiento y las reglas FEFO quedan como una ampliación posterior.

## Existencias anteriores

La migración `productos.0008_lotes_fifo` crea un lote de **saldo anterior** por cada pareja producto/bodega con stock positivo. Conserva exactamente las cantidades y deja el costo sin registrar. La fecha técnica de ese saldo no se presenta como fecha real de recepción. Los movimientos anteriores conservan su historial y sus consultas de Kardex.

El saldo anterior se consume antes de las recepciones identificadas. Si se incorpora un saldo positivo anterior mediante una carga autorizada sin ningún desglose de lotes para esa pareja, la primera operación aplica el mismo criterio. Cuando ya existe una distribución por lote, una diferencia con `StockBodega` produce un conflicto y revierte toda la operación.

## Consistencia y confirmaciones

Producto, bodegas y existencias se bloquean dentro de la transacción operativa. Lotes, stock, movimientos, auditoría y avisos se confirman juntos. Una operación rechazada conserva todos los saldos anteriores. Las restricciones impiden cantidades negativas, duplicar la existencia de un lote en una bodega y asociar un desglose simultáneamente a movimiento y merma.

La interfaz de Movimientos envía un `solicitud_id` UUID que se conserva al reintentar la misma confirmación. Repetirlo devuelve la operación ya realizada con su desglose y saldo confirmado. Reutilizarlo con otros datos devuelve un conflicto. Los clientes anteriores pueden seguir enviando el cuerpo habitual. Las transferencias mantienen su identificador de confirmación existente.

## Migración y despliegue

Comprobar el cambio con bases desechables y disponer de un respaldo antes de publicar. Coordinar una ventana sin escrituras de inventario para aplicar la migración y activar el código de esta versión. Con las conexiones privadas de producción configuradas, ejecutar desde la raíz:

```bash
bash scripts/migrate-render.sh
```

El script aplica las migraciones por alias. El enrutador mantiene las tablas de inventario en las bases empresariales y excluye esas tablas de la central. Los scripts de compilación e inicio del servidor conservan la ejecución explícita de migraciones. Si una migración falla, resolverla antes de activar el código nuevo. Revertir esta migración elimina los datos de lotes creados por el módulo, por lo que una reversión posterior al uso de FIFO requiere el respaldo y una revisión del historial.

## Comprobaciones

```bash
python manage.py makemigrations --check --dry-run --settings=config.settings.testing
python manage.py test apps.productos.test_fifo --settings=config.settings.testing --noinput
python manage.py test esquema_multiempresa.pruebas_web --settings=esquema_multiempresa.testing --noinput
npm --prefix tests/js test
```

La suite PostgreSQL de GitHub también comprueba salidas concurrentes sobre los mismos lotes. La prueba de Chrome recorre dos entradas con costos diferentes y una salida que consume ambas recepciones.
