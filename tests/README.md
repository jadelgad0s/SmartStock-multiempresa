# Mapa de pruebas

Las pruebas se ubican junto al componente que validan:

| Ubicación | Tipo |
| --- | --- |
| apps/*/test_*.py | Pruebas de API y reglas de cada aplicación Django. |
| esquema_multiempresa/pruebas_*.py | Login, empresas, permisos internos y aislamiento de datos. |
| apps/core/selenium_suite.py y esquema_multiempresa/selenium_suite.py | Recorridos en Chrome. |
| [js/](js/) | Pruebas JavaScript con JSDOM y respuestas controladas. |
| [desktop/](desktop/) | Página usada por la comprobación del ejecutable Windows. |
| python/test_cuentas_consola.py | Recuperación administrativa, destinos permitidos, contraseñas y reversión atómica con SQLite aislado. |

La recuperación por consola se comprueba en un proceso separado, sin variables privadas ni conexiones a Neon:

```bash
python -m unittest discover -s tests/python -p test_cuentas_consola.py -v
```

Consulta la [guía de ejecución](../docs/desarrollo/pruebas.md) para seleccionar el perfil y ejecutar cada suite sin conectar con Neon.
