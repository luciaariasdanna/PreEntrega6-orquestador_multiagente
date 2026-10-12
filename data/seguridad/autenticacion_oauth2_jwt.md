---
titulo: Autenticación con OAuth2, contraseñas hasheadas y tokens JWT
etiquetas: [oauth2, jwt, oauth2passwordbearer, autenticacion, hash, bearer]
---

# Autenticación con OAuth2 y JWT

FastAPI incluye utilidades en `fastapi.security` para implementar los esquemas de seguridad definidos por OpenAPI. El flujo más común para una API con frontend propio es OAuth2 con *password flow* y tokens Bearer firmados como JWT.

## OAuth2PasswordBearer

```python
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
```

`OAuth2PasswordBearer` es una dependencia que busca el header `Authorization: Bearer <token>` en la petición y devuelve el token como string. Si el header falta o no tiene el formato Bearer, responde automáticamente con **401 Unauthorized**. El parámetro `tokenUrl` indica la URL relativa a la que el cliente debe enviar usuario y contraseña para obtener el token; no crea ese endpoint, solo lo documenta para que el botón "Authorize" de `/docs` funcione.

## El endpoint de login

```python
from fastapi.security import OAuth2PasswordRequestForm

@app.post("/token")
async def login(form: Annotated[OAuth2PasswordRequestForm, Depends()]):
    usuario = autenticar(form.username, form.password)
    if not usuario:
        raise HTTPException(
            status_code=401,
            detail="Usuario o contraseña incorrectos",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = crear_token_acceso({"sub": usuario.username}, expira=timedelta(minutes=30))
    return {"access_token": token, "token_type": "bearer"}
```

`OAuth2PasswordRequestForm` lee `username` y `password` como datos de formulario (no JSON), tal como exige la especificación OAuth2; por eso requiere tener instalado `python-multipart`. La respuesta debe contener `access_token` y `token_type`.

## Contraseñas: nunca en texto plano

Las contraseñas se guardan *hasheadas* con un algoritmo lento y con sal, como Argon2 o bcrypt (por ejemplo con las librerías `pwdlib` o `passlib`). Al iniciar sesión se hashea la contraseña recibida y se compara con el hash almacenado. Si la base de datos se filtra, los atacantes no obtienen las contraseñas originales.

## Tokens JWT

Un JWT (JSON Web Token) es un string con tres partes separadas por puntos: header, payload y firma. El payload no está cifrado (cualquiera puede leerlo), pero la firma garantiza que no fue modificado. Se firma con una clave secreta (`SECRET_KEY`, generada por ejemplo con `openssl rand -hex 32`) y un algoritmo como `HS256`, usando la librería PyJWT. Conviene incluir la clave `sub` (sujeto, el identificador del usuario) y `exp` (fecha de expiración).

## Obtener el usuario actual

```python
async def obtener_usuario_actual(token: Annotated[str, Depends(oauth2_scheme)]):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token inválido",
                            headers={"WWW-Authenticate": "Bearer"})
    return buscar_usuario(payload.get("sub"))

@app.get("/usuarios/yo")
async def leer_mi_usuario(usuario: Annotated[Usuario, Depends(obtener_usuario_actual)]):
    return usuario
```

Al decodificar se verifica la firma y la expiración: un token alterado o vencido lanza `InvalidTokenError` y se responde 401. La dependencia `obtener_usuario_actual` se reutiliza en todas las rutas protegidas, y otra dependencia encima de ella puede verificar, por ejemplo, que el usuario esté activo.

## Scopes y otros esquemas

Para permisos finos, OAuth2 define *scopes* (por ejemplo `items:read`, `items:write`); en FastAPI se declaran con `Security()` y `SecurityScopes`. El módulo `fastapi.security` también ofrece `APIKeyHeader`, `APIKeyQuery`, `APIKeyCookie`, `HTTPBasic` y `HTTPBearer` para otros mecanismos de autenticación.
