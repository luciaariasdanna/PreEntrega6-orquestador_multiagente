---
titulo: Tareas en segundo plano con BackgroundTasks
etiquetas: [backgroundtasks, segundo-plano, email, celery, asincronia]
---

# Tareas en segundo plano

Muchas operaciones no necesitan terminar antes de responderle al cliente: enviar un correo de confirmación después de un registro, escribir un log de auditoría, generar una miniatura o notificar a otro servicio. Hacer esperar al usuario por esas tareas empeora el tiempo de respuesta. FastAPI permite programarlas para que se ejecuten **después** de enviar la respuesta.

## Uso de BackgroundTasks

Se declara un parámetro de tipo `BackgroundTasks` en la función de ruta y se agregan tareas con `add_task`:

```python
from fastapi import BackgroundTasks

def enviar_email_bienvenida(destinatario: str, nombre: str) -> None:
    # Conexión SMTP lenta; el cliente no tiene que esperarla.
    ...

@app.post("/registro/", status_code=201)
async def registrar_usuario(usuario: NuevoUsuario, background_tasks: BackgroundTasks):
    guardar_usuario(usuario)
    background_tasks.add_task(enviar_email_bienvenida, usuario.email, usuario.nombre)
    return {"mensaje": "Usuario registrado. Te enviamos un correo de confirmación."}
```

`add_task` recibe la función a ejecutar seguida de sus argumentos posicionales y por nombre. La función de tarea puede ser `async def` o `def` normal; en el segundo caso FastAPI la ejecuta en el threadpool. El cliente recibe la respuesta inmediatamente y la tarea corre a continuación.

## Tareas desde dependencias

`BackgroundTasks` también puede declararse en dependencias y subdependencias. FastAPI usa el mismo objeto en toda la petición, así que todas las tareas agregadas desde distintos lugares se ejecutan juntas al final, en el orden en que se agregaron.

## Limitaciones: cuándo usar otra herramienta

Las tareas en segundo plano corren **en el mismo proceso** que la aplicación, después de la respuesta. Esto implica:

- Si el proceso se reinicia o cae, las tareas pendientes se pierden: no hay reintentos ni persistencia.
- Una tarea pesada en CPU compite con las peticiones que atiende el mismo worker.
- No hay una cola compartida entre varias réplicas ni forma de consultar el estado de una tarea.

Para trabajos pesados, de larga duración o que requieren reintentos y monitoreo (procesar video, entrenar un modelo, enviar miles de correos), conviene una cola de tareas dedicada como Celery (con Redis o RabbitMQ como broker), RQ o ARQ, donde workers separados consumen los trabajos.

## Diferencia con los eventos de ciclo de vida

Las tareas en segundo plano están ligadas a una petición. Para lógica que debe correr una sola vez al iniciar o al apagar la aplicación (cargar un modelo de machine learning en memoria, abrir un pool de conexiones), FastAPI ofrece el parámetro `lifespan`: una función asíncrona decorada con `@asynccontextmanager` cuyo código antes del `yield` corre al arrancar y el posterior al apagar. Los antiguos eventos `@app.on_event("startup")` y `"shutdown"` están deprecados en favor de `lifespan`.
