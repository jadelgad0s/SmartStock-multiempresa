# Buscar y registrar códigos en el catálogo de una empresa

En **Catálogo → Nuevo producto → Buscar código en el catálogo de la empresa**, escribe un SKU o código y pulsa **Buscar en catálogo** o Enter. Un lector USB puede escribirlo en ese campo. **Escanear** utiliza la cámara del navegador, requiere permiso y funciona en HTTPS o localhost.

La consulta utiliza exclusivamente la base de la empresa resuelta por el servidor. Incluye productos activos e inactivos. No consulta Open Food Facts ni utiliza fichas externas almacenadas para completar un producto nuevo de una empresa.

## Producto ya registrado

Una coincidencia muestra nombre, SKU y estado, ofrece abrir su ficha y bloquea la creación de un duplicado. Si el producto existe con otro código, abre su ficha para añadir ese código en lugar de crear otra ficha.

## Código nuevo

El código consultado queda preparado en el formulario. Completa SKU, nombre, precio y los demás datos, y confirma **Crear producto** para guardarlo. Consultar el código no crea productos, existencias ni movimientos.

Al cambiar la consulta se retira el código añadido automáticamente y se conservan los campos y códigos escritos manualmente. El lector físico, la cámara y los códigos secundarios continúan disponibles. Se reconocen los QR internos que contienen un SKU o una dirección de productos del dominio de la propia empresa.

## API

`GET /api/v1/productos/consultar-codigo/?codigo=CODIGO`

- Requiere una cuenta activa, JWT de la empresa y permiso crear_producto.
- Devuelve el formato habitual con success, mensaje y data.
- Una coincidencia devuelve estado existente y los datos del producto. Un código nuevo devuelve no_encontrado y permite completar la ficha manualmente.
- Los datos de entrada inválidos devuelven 400; una coincidencia ambigua devuelve 409.
- La API de creación de productos de una empresa rechaza asociar una ficha externa. Los productos anteriores conservan su historial.

La [referencia del proyecto original](../historial/consulta-externa-proyecto-original.md) documenta el comportamiento de consulta externa que permanece en el perfil general anterior.

## Comprobación

Con el entorno activado, desde la raíz del proyecto:

```bat
python manage.py test esquema_multiempresa.pruebas_web --settings=esquema_multiempresa.testing --verbosity 2
npm --prefix tests/js ci
npm --prefix tests/js test
```

El recorrido de [Chrome](../../esquema_multiempresa/selenium_suite.py) comprueba código nuevo, alta confirmada y producto inactivo existente en ambas empresas. Consulta la [guía de pruebas](../desarrollo/pruebas.md) para ejecutarlo con bases desechables.
