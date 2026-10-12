---
titulo: Testing de aplicaciones FastAPI con TestClient y pytest
etiquetas: [testing, testclient, pytest, httpx, dependency-overrides]
---

# Testing con TestClient

Una de las ventajas de FastAPI es que se pueden probar los endpoints **sin levantar un servidor** ni abrir puertos: las peticiones se envían directamente a la aplicación ASGI en memoria. La herramienta para esto es `TestClient`, que está basado en HTTPX, por lo que requiere tener instalado `httpx`.

## Un primer test

```python
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_leer_raiz():
    respuesta = client.get("/")
    assert respuesta.status_code == 200
    assert respuesta.json() == {"mensaje": "Hola mundo"}
```

Los tests son funciones normales (`def`, no `async def`) que empiezan con `test_` y usan `assert`, que es la convención de pytest. Se ejecutan con el comando `pytest`. El cliente expone los mismos métodos que `httpx`: `get`, `post`, `put`, `delete`, con argumentos como `json=`, `params=`, `headers=` o `data=` para formularios.

```python
def test_crear_item_invalido():
    respuesta = client.post("/items/", json={"nombre": "Lápiz", "precio": -5})
    assert respuesta.status_code == 422
```

## Organización de los tests

Lo habitual es tener un paquete `app/` y una carpeta `tests/` con archivos `test_*.py`. Las fixtures de pytest, ubicadas en `conftest.py`, permiten compartir el cliente u otros recursos entre tests:

```python
import pytest

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
```

Usar `TestClient` dentro de un bloque `with` es importante cuando la aplicación define un `lifespan`: así se ejecuta el código de arranque y de apagado (por ejemplo, abrir y cerrar el pool de conexiones) durante el test.

## Reemplazar dependencias

Para no tocar la base de datos real o servicios externos, se reemplazan dependencias con `app.dependency_overrides`:

```python
def obtener_usuario_falso():
    return Usuario(username="test", activo=True)

app.dependency_overrides[obtener_usuario_actual] = obtener_usuario_falso
```

Después del test se restablece con `app.dependency_overrides.clear()`, idealmente en una fixture para no contaminar otros tests.

## Tests asíncronos

Si el propio test necesita usar `await` (por ejemplo para consultar una base de datos asíncrona), se usa `httpx.AsyncClient` con `ASGITransport(app=app)` y un plugin como `pytest-anyio` o `pytest-asyncio`, marcando el test como asíncrono. Para la mayoría de los casos el `TestClient` sincrónico alcanza, incluso si las rutas están definidas con `async def`.

## WebSockets

`TestClient` también puede probar endpoints WebSocket con `client.websocket_connect("/ws")`, que se usa como context manager y ofrece métodos como `send_text`, `receive_text` y `receive_json`.
