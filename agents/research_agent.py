"""Agente de Búsqueda/Investigación.

Herramienta acotada: SOLO puede consultar la Vector DB de la Pre-entrega 4 (documentación
de FastAPI). No tiene calculadora: si necesita un número derivado, lo deja para el Analista.
"""

from functools import lru_cache

from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain_core.tools import tool

import config
from agents.common import ejecutar_especialista
from knowledge_base import obtener_base
from state import AgentState

SYSTEM_PROMPT = """Sos el agente INVESTIGADOR de un equipo multi-agente.
Tu única función es encontrar datos concretos en la documentación técnica de FastAPI
usando la herramienta `buscar_documentacion_fastapi`.

Reglas:
- Buscá SIEMPRE con la herramienta antes de responder; no respondas de memoria.
- Si la primera búsqueda no alcanza, reformulá la consulta (máximo 3 búsquedas).
- NO hagas cálculos ni inventes números: transcribí los datos tal como aparecen
  (valores, fórmulas, unidades). Aunque la instrucción mencione datos del usuario
  (núcleos, memoria, etc.), NO apliques las fórmulas a esos datos: los cálculos los hace
  otro agente con su calculadora.
- Respondé en viñetas breves y citá la fuente de cada dato con el formato [archivo, p. N].
- Si un dato no aparece en la documentación, decilo explícitamente."""


@tool
def buscar_documentacion_fastapi(consulta: str) -> str:
    """Busca en la documentación técnica de FastAPI (instalación, parámetros, Pydantic,
    dependencias, middleware/CORS, tareas en segundo plano, OAuth2/JWT, testing,
    despliegue en producción con workers/Docker/HTTPS y FAQ). Devuelve los fragmentos
    más relevantes con su fuente."""
    try:
        documentos = obtener_base().buscar(consulta)
    except Exception as e:  # Pinecone/embeddings caídos: el agente recibe el error y puede reintentar
        return f"Error al buscar en la documentación: {e}"
    if not documentos:
        return "No se encontraron fragmentos relevantes para esa consulta."
    return "\n\n".join(
        f"[{d.metadata.get('source', '?')}, p. {d.metadata.get('page', '?')}]\n{d.page_content}"
        for d in documentos
    )


HERRAMIENTAS = [buscar_documentacion_fastapi]


@lru_cache(maxsize=1)
def crear_agente_investigador():
    # El límite hace cumplir en código el "máximo 3 búsquedas" del prompt: las llamadas
    # excedentes se bloquean y el agente tiene que responder con lo que ya encontró.
    limite = ToolCallLimitMiddleware(run_limit=config.MAX_BUSQUEDAS_INVESTIGADOR)
    return create_agent(model=config.obtener_llm(), tools=HERRAMIENTAS,
                        system_prompt=SYSTEM_PROMPT, middleware=[limite], name="investigador")


def crear_nodo_investigador(agente=None):
    """Devuelve el nodo del grafo. `agente` se puede inyectar (útil para tests)."""

    def nodo_investigador(state: AgentState) -> dict:
        return ejecutar_especialista(agente or crear_agente_investigador(), "investigador", state)

    return nodo_investigador
