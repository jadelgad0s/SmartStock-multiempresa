# Aplicación de escritorio para Windows

desktop.py abre SmartStock en una ventana de pywebview. Su pantalla de inicio y los recursos de marca están en recursos/; la compilación se realiza con scripts/build-desktop.cmd.

## Abrir una instalación multiempresa existente

Primero inicia el servidor configurado con Neon:

~~~bat
python manage.py runserver --settings=esquema_multiempresa.web
~~~

En otra ventana de CMD, activa el mismo entorno y ejecuta:

~~~bat
python -m pip install -r requirements.txt
python desktop.py --no-server --url http://127.0.0.1:8000/
~~~

La opción --no-server permite usar el servidor multiempresa ya iniciado. Ejecutar desktop.py sin esa opción utiliza el perfil local general de Django, que tiene otra configuración.

## Compilar el ejecutable

En Windows con Python 3.13.7 de 64 bits:

~~~bat
scripts\build-desktop.cmd
~~~

El script crea .venv-desktop, instala requirements-desktop-build.txt y genera dist\SmartStock.exe. Los archivos temporales y el ejecutable están excluidos de Git.

La aplicación compilada abre por defecto https://smartstockchile.cl/ y requiere Microsoft Edge WebView2 Runtime. Para revisar una dirección distinta:

~~~bat
dist\SmartStock.exe --url http://127.0.0.1:8000/
~~~

La dirección predeterminada no cambia el despliegue del sitio público. Su estado se explica en [Versiones](estado-versiones.md).

El flujo [desktop-windows.yml](../../.github/workflows/desktop-windows.yml) comprueba el arranque y el control de visibilidad de contraseña usando una página de prueba, sin credenciales reales.
