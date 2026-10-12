"""Esquema del estado compartido del grafo.

`AgentState` hereda de `MessagesState` (el campo `messages` con el reducer `add_messages`)
y le suma campos estructurados para que el Supervisor no dependa de "leer" el historial
de chat para saber qué pasó:

- `contribuciones`: registro de QUÉ aportó CADA especialista, con la instrucción que
  recibió, las herramientas que usó y en qué paso. Usa `operator.add` como reducer: cada
  nodo devuelve una lista con su contribución y LangGraph la SUMA a la existente en vez de
  pisarla. Así no se pierde contexto aunque los nodos se ejecuten en distintos turnos.
- `decisiones`: bitácora del Supervisor (a quién delegó, por qué y cómo evaluó la rúbrica).
- `next_agent` / `instruccion`: el "despacho" del Supervisor hacia el próximo nodo.
- `pasos` / `task_completed` / `motivo_cierre`: control de flujo y condición de parada.
"""

import operator
from typing import Annotated, Literal, Optional, TypedDict

from langgraph.graph import MessagesState

NombreEspecialista = Literal["investigador", "analista"]
Destino = Literal["investigador", "analista", "FINISH"]


class Contribucion(TypedDict):
    agente: NombreEspecialista
    paso: int
    instruccion: str          # lo que el Supervisor le pidió (contexto acotado)
    aporte: str               # lo que el especialista devolvió
    herramientas: list[str]   # herramientas que efectivamente invocó


class Decision(TypedDict):
    paso: int
    next: Destino
    razon: str
    rubrica: dict[str, bool]  # criterios de validación evaluados en esa decisión


class AgentState(MessagesState):
    next_agent: Optional[Destino]
    instruccion: str
    contribuciones: Annotated[list[Contribucion], operator.add]
    decisiones: Annotated[list[Decision], operator.add]
    pasos: int
    task_completed: bool
    motivo_cierre: str


def estado_inicial(pregunta: str) -> dict:
    """Estado de arranque para `app.invoke` / `app.stream`."""
    from langchain_core.messages import HumanMessage

    return {
        "messages": [HumanMessage(content=pregunta)],
        "next_agent": None,
        "instruccion": "",
        "contribuciones": [],
        "decisiones": [],
        "pasos": 0,
        "task_completed": False,
        "motivo_cierre": "",
    }
