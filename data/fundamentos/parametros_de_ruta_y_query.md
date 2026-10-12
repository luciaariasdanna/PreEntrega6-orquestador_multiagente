---
titulo: Parámetros de ruta, parámetros de consulta y validación
etiquetas: [path-params, query-params, validacion, 422, enum]
---

# Parámetros de ruta y de consulta

## Parámetros de ruta (path parameters)

Los parámetros de ruta se declaran con la misma sintaxis que los *format strings* de Python y se reciben como argumentos de la función:

```python
@app.get("/items/{item_id}")
async def leer_item(item_id: int):
    return {"item_id": item_id}
```

Gracias a la anotación `int`, FastAPI convierte automáticamente el texto de la URL a entero. Si alguien pide `/items/abc`, la conversión falla y FastAPI responde sin ejecutar la función.

El orden de declaración importa: si existen `/usuarios/yo` y `/usuarios/{usuario_id}`, la ruta fija `/usuarios/yo` debe declararse primero; de lo contrario, "yo" sería interpretado como un `usuario_id`.

Para restringir un parámetro a un conjunto cerrado de valores se usa una clase `Enum` que herede de `str` y de `Enum`. La documentación en `/docs` mostrará entonces un desplegable con los valores permitidos.

## Parámetros de consulta (query parameters)

Todo argumento de la función que no forma parte de la ruta se interpreta como parámetro de consulta, es decir, lo que va después del `?` en la URL:

```python
@app.get("/items/")
async def listar_items(skip: int = 0, limit: int = 10, q: str | None = None):
    return {"skip": skip, "limit": limit, "q": q}
```

Un parámetro con valor por defecto es opcional; uno sin valor por defecto es obligatorio. Los booleanos aceptan `true`, `1`, `on`, `yes` y sus equivalentes negativos.

## Validaciones adicionales con Query y Path

Para agregar restricciones se usan `Query()` y `Path()`, preferentemente dentro de `Annotated`:

```python
from typing import Annotated
from fastapi import Path, Query

@app.get("/productos/{producto_id}")
async def leer_producto(
    producto_id: Annotated[int, Path(ge=1, title="ID del producto")],
    q: Annotated[str | None, Query(min_length=3, max_length=50, pattern="^[a-z]+$")] = None,
):
    ...
```

Las validaciones numéricas son `gt` (mayor que), `ge` (mayor o igual), `lt` y `le`. Para strings existen `min_length`, `max_length` y `pattern` (expresión regular). Un parámetro de consulta que recibe varios valores (`?tag=a&tag=b`) se declara como `list[str]` con `Query()`.

## ¿Qué pasa cuando la validación falla?

Cuando un parámetro no cumple su tipo o sus restricciones, FastAPI no ejecuta la función de ruta y responde automáticamente con el código de estado HTTP **422 Unprocessable Entity**. El cuerpo de la respuesta es un JSON con la clave `detail`, que contiene una lista de errores; cada error indica la ubicación (`loc`, por ejemplo `["query", "limit"]`), un mensaje (`msg`) y el tipo de error (`type`).

Este comportamiento se puede personalizar registrando un manejador para la excepción `RequestValidationError`:

```python
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

@app.exception_handler(RequestValidationError)
async def manejar_validacion(request, exc):
    return JSONResponse(status_code=400, content={"errores": exc.errors()})
```

Para errores de negocio propios (por ejemplo, un recurso que no existe) se lanza `HTTPException(status_code=404, detail="Item no encontrado")`.
