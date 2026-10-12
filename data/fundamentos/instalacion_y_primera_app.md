---
titulo: Instalación y primera aplicación con FastAPI
etiquetas: [instalacion, uvicorn, fastapi-cli, openapi, swagger]
---

# Instalación y primera aplicación

FastAPI es un framework web moderno para construir APIs con Python basado en las anotaciones de tipos estándar del lenguaje. Está construido sobre Starlette (la parte web y ASGI) y Pydantic (la parte de validación de datos), y fue creado por Sebastián Ramírez.

## Instalación

Se recomienda trabajar dentro de un entorno virtual. La forma más completa de instalarlo es con los extras estándar, que incluyen el servidor Uvicorn, la herramienta de línea de comandos `fastapi` y otras dependencias opcionales habituales:

```bash
python -m venv .venv
pip install "fastapi[standard]"
```

Si se instala solo `pip install fastapi`, no se incluye ningún servidor ASGI y hay que instalar Uvicorn (u otro servidor) por separado.

## La aplicación mínima

Un archivo `main.py` con la aplicación más simple posible:

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
async def raiz():
    return {"mensaje": "Hola mundo"}
```

El decorador `@app.get("/")` registra una *operación de ruta* (path operation): le indica a FastAPI que la función de abajo atiende las peticiones HTTP GET a la ruta `/`. Existen decoradores equivalentes para los demás métodos: `@app.post()`, `@app.put()`, `@app.delete()`, `@app.patch()`. La función puede devolver un diccionario, una lista, un modelo de Pydantic o tipos simples; FastAPI los convierte automáticamente a JSON.

## Ejecutar el servidor en desarrollo

Con la CLI de FastAPI, el modo desarrollo se levanta con:

```bash
fastapi dev main.py
```

Este comando inicia Uvicorn con recarga automática (auto-reload): cada vez que se guarda un cambio en el código, el servidor se reinicia solo. Por defecto escucha en `http://127.0.0.1:8000`. La alternativa clásica, invocando Uvicorn directamente, es:

```bash
uvicorn main:app --reload
```

donde `main` es el módulo (archivo `main.py`) y `app` es el objeto creado con `FastAPI()`. La recarga automática consume más recursos y no debe usarse en producción; para producción existe `fastapi run`, que no recarga y escucha en `0.0.0.0`.

## Documentación interactiva automática

Sin escribir nada extra, FastAPI genera el esquema OpenAPI de la API y lo publica en `/openapi.json`. A partir de ese esquema ofrece dos interfaces de documentación:

- `/docs`: Swagger UI, que permite probar cada endpoint desde el navegador ("Try it out").
- `/redoc`: ReDoc, una documentación alternativa de solo lectura.

Los metadatos de la API se pueden personalizar al crear la aplicación, por ejemplo `FastAPI(title="Mi API", version="1.0.0", description="...")`. También es posible desactivar la documentación pasando `docs_url=None` o `redoc_url=None`.

## async def o def

Las funciones de ruta pueden declararse con `async def` o con `def` normal. Si dentro de la función se usan librerías que soportan `await` (clientes HTTP asíncronos, drivers async de base de datos), conviene `async def`. Si se usan librerías bloqueantes, conviene `def`: FastAPI ejecuta esas funciones en un pool de hilos (threadpool) externo para no bloquear el event loop.
