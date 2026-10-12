---
titulo: Inyección de dependencias con Depends
etiquetas: [depends, dependencias, yield, base-de-datos, dependency-overrides]
---

# Inyección de dependencias

FastAPI incluye un sistema de inyección de dependencias muy simple de usar. Una *dependencia* es cualquier función (o clase) que FastAPI ejecuta antes de la función de ruta y cuyo resultado le inyecta como parámetro. Sirve para compartir lógica: obtener una sesión de base de datos, leer el usuario autenticado, validar permisos o reutilizar parámetros comunes de paginación.

## Declarar una dependencia con Depends

```python
from typing import Annotated
from fastapi import Depends

async def parametros_comunes(q: str | None = None, skip: int = 0, limit: int = 100):
    return {"q": q, "skip": skip, "limit": limit}

ParametrosComunes = Annotated[dict, Depends(parametros_comunes)]

@app.get("/items/")
async def listar_items(params: ParametrosComunes):
    return params

@app.get("/usuarios/")
async def listar_usuarios(params: ParametrosComunes):
    return params
```

A `Depends()` se le pasa la función sin llamarla. FastAPI resuelve los parámetros de la dependencia igual que los de una ruta (query, path, body, headers) y además las dependencias pueden depender de otras dependencias, formando un árbol. Guardar el `Annotated[...]` en un alias evita repetir código.

Dentro de una misma petición, si varias partes del árbol usan la misma dependencia, se ejecuta una sola vez y el valor se reutiliza (caché por petición). Para forzar una nueva ejecución se usa `Depends(funcion, use_cache=False)`.

## Dependencias con yield: abrir y cerrar recursos

El caso típico es la conexión o sesión de base de datos: se abre antes de atender la petición y debe cerrarse siempre al terminar, incluso si hubo un error. Para eso la dependencia usa `yield` en lugar de `return`:

```python
def obtener_db():
    db = SesionLocal()
    try:
        yield db
    finally:
        db.close()

SesionDB = Annotated[Session, Depends(obtener_db)]

@app.get("/clientes/{cliente_id}")
def leer_cliente(cliente_id: int, db: SesionDB):
    return db.get(Cliente, cliente_id)
```

El código antes del `yield` se ejecuta antes de la ruta; el valor entregado por `yield` se inyecta; y el código después del `yield` (el bloque `finally`) se ejecuta al finalizar, como un *context manager*. De esta forma cada petición reutiliza el patrón de apertura y cierre sin duplicarlo en cada endpoint.

## Dependencias en el decorador y globales

Cuando una dependencia no devuelve un valor que interese usar (por ejemplo, solo verifica un header `X-Token` y lanza `HTTPException` si es inválido), se declara en el decorador: `@app.get("/items/", dependencies=[Depends(verificar_token)])`. Para aplicarla a toda la aplicación se usa `FastAPI(dependencies=[Depends(verificar_token)])`, y para un grupo de rutas, el parámetro `dependencies` de `APIRouter`.

## Clases como dependencias

Cualquier "invocable" puede ser una dependencia, incluidas las clases: `Depends(Paginador)` crea una instancia de `Paginador` usando los parámetros de su `__init__`.

## Reemplazar dependencias en tests

`app.dependency_overrides` es un diccionario que permite sustituir una dependencia por otra, por ejemplo una base de datos de prueba o un usuario falso: `app.dependency_overrides[obtener_db] = obtener_db_de_prueba`. Al terminar el test conviene limpiarlo con `app.dependency_overrides.clear()`.
