# Mapa de pruebas

Las pruebas se ubican junto al componente que validan:

| Ubicación | Tipo |
| --- | --- |
| apps/*/test_*.py | Pruebas de API y reglas de cada aplicación Django. |
| esquema_multiempresa/pruebas_*.py | Login, empresas, permisos internos y aislamiento de datos. |
| apps/core/selenium_suite.py y esquema_multiempresa/selenium_suite.py | Recorridos en Chrome. |
| [js/](js/) | Pruebas JavaScript con JSDOM y respuestas controladas. |
| [desktop/](desktop/) | Página usada por la comprobación del ejecutable Windows. |

Consulta la [guía de ejecución](../docs/desarrollo/pruebas.md) para seleccionar el perfil y ejecutar cada suite sin conectar con Neon.
