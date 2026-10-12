"""Nodo de síntesis: redacta la respuesta final combinando los aportes de los especialistas."""

from typing import Any

from langchain_core.messages import AIMessage

import config
from state import AgentState

SINTESIS_PROMPT = """Sos el redactor final de un equipo multi-agente.
Respondé la pregunta del usuario usando ÚNICAMENTE los aportes del equipo (no agregues
datos propios). Reglas:
- Respuesta clara, en castellano y breve (máximo ~200 palabras).
- Conservá las citas de fuente del investigador con el formato [archivo, p. N].
- Mostrá los cálculos clave del analista.
- Si los aportes se contradicen o falta información, decilo explícitamente en vez de inventar.

Pregunta original:
{pregunta}

Aportes del equipo (en orden):
{aportes}

Estado de la validación del supervisor: {motivo}"""


def crear_nodo_sintesis(llm: Any = None):
    def nodo_sintesis(state: AgentState) -> dict:
        aportes = "\n\n".join(
            f"- [{c['agente']}, paso {c['paso']}] {c['aporte']}" for c in state.get("contribuciones", [])
        ) or "(ningún especialista aportó información)"
        prompt = SINTESIS_PROMPT.format(
            pregunta=state["messages"][0].text,
            aportes=aportes,
            motivo=state.get("motivo_cierre") or "sin datos",
        )
        respuesta = (llm or config.obtener_llm()).invoke(prompt)
        return {
            "messages": [AIMessage(content=respuesta.text.strip(), name="sintesis")],
            "task_completed": True,
        }

    return nodo_sintesis
