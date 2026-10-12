---
titulo: Middleware y CORS
etiquetas: [middleware, cors, corsmiddleware, gzip, seguridad-web]
---

# Middleware y CORS

## Qué es un middleware

Un middleware es una función que se ejecuta con **cada** petición antes de que llegue a la operación de ruta, y con cada respuesta antes de devolverla al cliente. Es el lugar indicado para lógica transversal: medir tiempos, agregar headers, registrar logs o manejar CORS.

```python
import time
from fastapi import Request

@app.middleware("http")
async def agregar_tiempo_de_proceso(request: Request, call_next):
    inicio = time.perf_counter()
    respuesta = await call_next(request)
    respuesta.headers["X-Process-Time"] = f"{time.perf_counter() - inicio:.4f}"
    return respuesta
```

`call_next` pasa la petición al resto de la aplicación y devuelve la respuesta generada. Si hay dependencias con `yield`, su código de salida corre después del middleware; las tareas en segundo plano, después de todos los middlewares.

Los middlewares de clase se registran con `app.add_middleware(Clase, **opciones)`. Cada middleware agregado envuelve a los anteriores, por lo que el último agregado es el más externo.

## CORS: Cross-Origin Resource Sharing

Un *origen* es la combinación de protocolo, dominio y puerto: `http://localhost:3000` y `http://localhost:8000` son orígenes distintos. Cuando un frontend que corre en un origen llama con JavaScript a una API de otro origen, el navegador aplica la política de mismo origen y bloquea la respuesta salvo que el backend la autorice explícitamente con headers CORS. Para peticiones "no simples" (por ejemplo con `Content-Type: application/json` o headers personalizados como `Authorization`), el navegador envía antes una petición previa `OPTIONS` llamada *preflight*.

## Configurar CORSMiddleware

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://mi-frontend.com", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Parámetros de `CORSMiddleware`:

- `allow_origins`: lista de orígenes permitidos. `["*"]` permite cualquier origen.
- `allow_origin_regex`: expresión regular para orígenes, por ejemplo todos los subdominios de un dominio.
- `allow_methods`: métodos HTTP permitidos. Por defecto solo `GET`.
- `allow_headers`: headers de petición permitidos. Por defecto ninguno además de los "simples" que el navegador siempre acepta.
- `allow_credentials`: si se aceptan cookies y headers de autorización en peticiones cross-origin. Por defecto `False`. Si es `True`, ninguno de `allow_origins`, `allow_methods` ni `allow_headers` puede ser `["*"]`: deben listarse explícitamente.
- `expose_headers`: headers de la respuesta que el navegador expone al JavaScript.
- `max_age`: segundos que el navegador puede cachear la respuesta del preflight. Por defecto 600.

Un error frecuente es usar `allow_origins=["*"]` junto con `allow_credentials=True` y luego no entender por qué el navegador sigue bloqueando las peticiones con cookies.

## Otros middlewares incluidos

- `GZipMiddleware`: comprime las respuestas cuando el cliente envía `Accept-Encoding: gzip`. El parámetro `minimum_size` (por defecto 500 bytes) evita comprimir respuestas pequeñas.
- `TrustedHostMiddleware`: rechaza peticiones cuyo header `Host` no esté en `allowed_hosts`, como defensa ante ataques de host header.
- `HTTPSRedirectMiddleware`: redirige toda petición `http` o `ws` a su versión segura `https` o `wss`.
