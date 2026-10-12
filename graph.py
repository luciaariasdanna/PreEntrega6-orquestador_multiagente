"""Construcción del grafo jerárquico (Supervisor -> especialistas -> Supervisor -> Síntesis).

    START -> supervisor --(condicional)--> investigador -> supervisor
                                      |--> analista     -> supervisor
                                      |--> sintesis     -> END
"""

from typing import Literal

from langgraph.graph import END, START, StateGraph

from agents.analyst_agent import crear_nodo_analista
from agents.research_agent import crear_nodo_investigador
from agents.supervisor import crear_nodo_supervisor
from agents.synthesizer import crear_nodo_sintesis
from state import AgentState


def enrutar(state: AgentState) -> Literal["investigador", "analista", "sintesis"]:
    """Mapea la decisión del Supervisor a los nombres de los nodos del grafo."""
    destino = state.get("next_agent")
    if destino in ("investigador", "analista"):
        return destino
    return "sintesis"  # FINISH (o cualquier valor inesperado) cierra el flujo


def construir_grafo(investigador=None, analista=None, decisor=None, llm_sintesis=None):
    """Arma y compila el grafo. Los parámetros permiten inyectar dobles de prueba;
    por defecto cada nodo usa Gemini."""
    grafo = StateGraph(AgentState)
    grafo.add_node("supervisor", crear_nodo_supervisor(decisor))
    grafo.add_node("investigador", crear_nodo_investigador(investigador))
    grafo.add_node("analista", crear_nodo_analista(analista))
    grafo.add_node("sintesis", crear_nodo_sintesis(llm_sintesis))

    grafo.add_edge(START, "supervisor")
    grafo.add_conditional_edges("supervisor", enrutar, {
        "investigador": "investigador",
        "analista": "analista",
        "sintesis": "sintesis",
    })
    # Topología jerárquica: los especialistas nunca hablan entre sí, siempre vuelven al Supervisor.
    grafo.add_edge("investigador", "supervisor")
    grafo.add_edge("analista", "supervisor")
    grafo.add_edge("sintesis", END)
    return grafo.compile()


app = construir_grafo()
