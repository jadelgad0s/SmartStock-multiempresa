# Catálogo de regiones y comunas

`regiones_comunas.json` procede de la [planilla CUT 2018 v04 publicada por SUBDERE](https://www.subdere.gov.cl/sites/default/files/documentos/CUT_2018_v04.xls), descargada el 20 de noviembre de 2026. La [página oficial del catálogo](https://www.subdere.gov.cl/documentacion/c%C3%B3digos-%C3%BAnicos-territoriales-actualizados-al-06-de-septiembre-2018) identifica la versión e incluye la región de Ñuble.

Se extrajeron las columnas Código Región, Nombre Región, Código Comuna 2018 y Nombre Comuna. Los códigos se conservan como texto, incluidos sus ceros iniciales. Se retiraron espacios al inicio y al final; los nombres de la fuente se conservan. Las regiones se presentan de norte a sur y el formulario ordena las comunas por nombre.

El archivo contiene 16 regiones y 346 comunas. Su cabecera registra la URL del origen, fecha de descarga y SHA-256 del XLS para poder verificar futuras actualizaciones. La aplicación consume este JSON local y no necesita instalar un lector de Excel ni consultar una API durante el uso del formulario.
