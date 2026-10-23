# ADR 0001 · Sin dependencias: biblioteca estándar de Python

**Estado:** aceptada · 2026-10-23

## Contexto

El repositorio tiene que poder clonarse y validarse en un minuto, por personas que no van a crear un entorno virtual
ni instalar paquetes para probar una idea.

## Decisión

Todo usa la biblioteca estándar de Python 3.10+: `sqlite3` para los datos (base en memoria, creada desde
`data/data.sql` en cada ejecución), `http.server` para el servidor, `urllib` para hablar con el modelo y `unittest`
para las pruebas. La pantalla es un único HTML sin librerías externas ni CDN, así funciona sin red.

## Consecuencias

- `python3 app.py` alcanza para probarlo; la CI no instala nada.
- El servidor es de desarrollo: escucha solo en `127.0.0.1` y no está pensado para exponerse a internet.
- Si hiciera falta un framework web o un ORM, entra como dependencia opcional sin romper este camino.
