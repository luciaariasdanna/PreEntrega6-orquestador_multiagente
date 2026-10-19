"""Utilidades compartidas por los nodos especialistas."""

import logging
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

import config
from state import AgentState, Contribucion, LlamadaHerramienta, NombreEspecialista

log = logging.getLogger(__name__)


def texto(mensaje: BaseMessage) -> str:
    """Contenido como string plano.

    Gemini puede devolver `content` como lista de bloques (`[{'type': 'text', ...,
    'extras': {'signature': ...}}]`); `.text` se queda solo con el texto visible.
    """
    return mensaje.text.strip()


def herramientas_usadas(mensajes: list[BaseMessage]) -> list[str]:
    return [m.name for m in mensajes if isinstance(m, ToolMessage) and m.name]


def llamadas_a_herramientas(mensajes: list[BaseMessage], max_chars: int = 160) -> list[LlamadaHerramienta]:
    """Cada tool call con sus argumentos (del `AIMessage.tool_calls`) y el resultado que
    devolvió la herramienta (del `ToolMessage` con el mismo `tool_call_id`)."""
    argumentos = {
        llamada["id"]: llamada["args"]
        for m in mensajes if isinstance(m, AIMessage)
        for llamada in m.tool_calls
    }
    return [
        {
            "herramienta": m.name,
            "argumentos": argumentos.get(m.tool_call_id, {}),
            "resultado": " ".join(m.text.split())[:max_chars],
            # status="error": excepción o bloqueo del ToolCallLimitMiddleware;
            # "Error...": error controlado que devuelven nuestras propias herramientas.
            "exito": m.status != "error" and not m.text.startswith("Error"),
        }
        for m in mensajes if isinstance(m, ToolMessage) and m.name
    ]


def ejecutar_especialista(agente: Any, nombre: NombreEspecialista, state: AgentState,
                          contexto: str = "") -> dict:
    """Invoca a un especialista con CONTEXTO ACOTADO y registra su contribución.

    El especialista no recibe `state["messages"]` (todo el historial): recibe solo la
    instrucción puntual del Supervisor y, si hace falta, el contexto mínimo que el
    Supervisor/nodo decide pasarle. Esto evita la "contaminación de contexto".
    """
    instruccion = state.get("instruccion") or texto(state["messages"][0])
    entrada = f"{instruccion}\n\n{contexto}".strip()

    try:
        resultado = agente.invoke({"messages": [HumanMessage(content=entrada)]},
                                  {"recursion_limit": config.RECURSION_LIMIT_ESPECIALISTA})
        mensajes = resultado["messages"]
        aporte = texto(mensajes[-1]) or "(el especialista no devolvió contenido)"
    except Exception as e:
        # Un especialista que falla (cuota del LLM, bucle de herramientas...) no tumba el
        # grafo: queda registrado como aporte fallido y el Supervisor decide qué hacer.
        log.warning("El especialista %s falló: %s", nombre, e)
        mensajes, aporte = [], f"(el especialista falló: {type(e).__name__}: {e})"
    paso = state.get("pasos", 0) + 1

    contribucion: Contribucion = {
        "agente": nombre,
        "paso": paso,
        "instruccion": instruccion,
        "aporte": aporte,
        "herramientas": herramientas_usadas(mensajes),
        "llamadas": llamadas_a_herramientas(mensajes),
    }
    return {
        "messages": [AIMessage(content=aporte, name=nombre)],
        "contribuciones": [contribucion],
        "pasos": paso,
    }
