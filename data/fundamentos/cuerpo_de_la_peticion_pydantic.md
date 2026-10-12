---
titulo: Cuerpo de la petición y modelos de Pydantic
etiquetas: [pydantic, basemodel, request-body, response-model, field]
---

# Cuerpo de la petición con Pydantic

Cuando un cliente necesita enviar datos a la API (por ejemplo en un POST o un PUT), esos datos viajan en el *cuerpo* (body) de la petición, normalmente como JSON. En FastAPI el cuerpo se declara con un modelo de Pydantic.

## Declarar un modelo con BaseModel

```python
from pydantic import BaseModel, Field

class Item(BaseModel):
    nombre: str
    descripcion: str | None = None
    precio: float = Field(gt=0, description="Precio en pesos")
    impuesto: float = 0.21
    etiquetas: list[str] = []
```

Las reglas son las mismas que para los parámetros de consulta: un campo sin valor por defecto es obligatorio; un campo con valor por defecto es opcional. Para declarar un campo opcional que puede faltar se usa `str | None = None`. `Field()` permite agregar validaciones (`gt`, `max_length`, etc.), descripciones y ejemplos que luego aparecen en la documentación.

## Recibir el modelo en una ruta

```python
@app.post("/items/", status_code=201)
async def crear_item(item: Item):
    datos = item.model_dump()
    datos["precio_final"] = item.precio * (1 + item.impuesto)
    return datos
```

Con solo anotar el parámetro como `Item`, FastAPI lee el cuerpo como JSON, convierte los tipos, valida los datos (si son inválidos responde con un error 422 que indica exactamente qué campo falló) y entrega un objeto `item` con autocompletado en el editor. En Pydantic v2 el método para convertir el modelo a diccionario es `model_dump()` (en v1 era `.dict()`).

FastAPI decide de dónde sale cada parámetro: si aparece en la ruta es parámetro de ruta; si es de un tipo simple (`int`, `str`, `bool`...) es de consulta; si está anotado con un modelo de Pydantic es parte del cuerpo. Se pueden combinar los tres en la misma función.

## Modelos anidados y varios cuerpos

Los modelos pueden contener otros modelos (`imagen: Imagen | None = None`) o listas de modelos (`imagenes: list[Imagen]`). Si una función recibe dos modelos, FastAPI espera un JSON con una clave por cada uno. Para incluir un valor simple dentro del cuerpo se usa `Body()`, y `Body(embed=True)` obliga a envolver un único modelo bajo su nombre.

## Modelo de respuesta (response_model)

El tipo de retorno de la función, o el argumento `response_model` del decorador, define la forma de la respuesta. FastAPI lo usa para validar y, sobre todo, **filtrar** los datos de salida: si el modelo de respuesta no tiene el campo `password`, ese campo nunca se envía aunque el objeto interno lo tenga.

```python
class UsuarioEntrada(BaseModel):
    usuario: str
    password: str

class UsuarioSalida(BaseModel):
    usuario: str

@app.post("/usuarios/", response_model=UsuarioSalida)
async def crear_usuario(usuario: UsuarioEntrada):
    return usuario
```

Otras opciones útiles son `response_model_exclude_unset=True`, que omite los campos que no fueron asignados explícitamente, y `status_code` para fijar el código de respuesta (por ejemplo 201 Created para recursos creados).
