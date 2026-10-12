"""Utilidades compartidas por los nodos especialistas."""

from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from state import AgentState, Contribucion, NombreEspecialista


def texto(mensaje: BaseMessage) -> str:
    """Contenido como string plano.

    Gemini puede devolver `content` como lista de bloques (`[{'type': 'text', ...,
    'extras': {'signature': ...}}]`); `.text` se queda solo con el texto visible.
    """
    return mensaje.text.strip()


def herramientas_usadas(mensajes: list[BaseMessage]) -> list[str]:
    return [m.name for m in mensajes if isinstance(m, ToolMessage) and m.name]


def ejecutar_especialista(agente: Any, nombre: NombreEspecialista, state: AgentState,
                          contexto: str = "") -> dict:
    """Invoca a un especialista con CONTEXTO ACOTADO y registra su contribución.

    El especialista no recibe `state["messages"]` (todo el historial): recibe solo la
    instrucción puntual del Supervisor y, si hace falta, el contexto mínimo que el
    Supervisor/nodo decide pasarle. Esto evita la "contaminación de contexto".
    """
    instruccion = state.get("instruccion") or texto(state["messages"][0])
    entrada = f"{instruccion}\n\n{contexto}".strip()

    resultado = agente.invoke({"messages": [HumanMessage(content=entrada)]})
    mensajes = resultado["messages"]
    aporte = texto(mensajes[-1]) or "(el especialista no devolvió contenido)"
    paso = state.get("pasos", 0) + 1

    contribucion: Contribucion = {
        "agente": nombre,
        "paso": paso,
        "instruccion": instruccion,
        "aporte": aporte,
        "herramientas": herramientas_usadas(mensajes),
    }
    return {
        "messages": [AIMessage(content=aporte, name=nombre)],
        "contribuciones": [contribucion],
        "pasos": paso,
    }
