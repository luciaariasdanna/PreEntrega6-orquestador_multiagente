"""Supervisor: router inteligente, validador y controlador de flujo.

En cada turno el Supervisor:
1. Evalúa una RÚBRICA de validación sobre las contribuciones acumuladas.
2. Decide el próximo nodo (`investigador`, `analista` o `FINISH`) y redacta una
   instrucción autocontenida para ese especialista (puede ser un pedido de refinamiento).
3. Pasa por guardas deterministas en código que garantizan la parada aunque el LLM
   insista en seguir delegando (anti "Supervisor Infinito").
"""

from collections import Counter
from functools import lru_cache
from typing import Callable, Literal

from pydantic import BaseModel, Field

import config
from state import AgentState, Decision, Destino


class RubricaValidacion(BaseModel):
    """Criterio de "suficiencia" que se debe cumplir antes de dar el END."""

    datos_con_fuente: bool = Field(
        description="El investigador aportó los datos concretos que pide la pregunta, "
                    "citando la fuente de cada uno.")
    calculos_verificados: bool = Field(
        description="El analista hizo con su herramienta todos los cálculos que pide la "
                    "pregunta (True también si la pregunta no requiere cálculos).")
    consistencia: bool = Field(
        description="Los números que usó el analista coinciden con los datos del "
                    "investigador y no hay contradicciones entre aportes.")
    responde_pregunta: bool = Field(
        description="Con lo reunido se puede responder TODAS las partes de la pregunta.")

    def aprobada(self) -> bool:
        return all(self.model_dump().values())


class DecisionSupervisor(BaseModel):
    rubrica: RubricaValidacion = Field(description="Evaluación de lo reunido HASTA AHORA.")
    next: Literal["investigador", "analista", "FINISH"] = Field(
        description="Próximo especialista, o FINISH si la rúbrica está aprobada.")
    instruccion: str = Field(
        description="Instrucción autocontenida para el especialista elegido: qué tiene que "
                    "hacer y, si es un refinamiento, qué faltó o qué corregir. Vacía si FINISH.")
    razon: str = Field(description="Justificación breve de la decisión.")


SUPERVISOR_PROMPT = """Sos el SUPERVISOR de un equipo multi-agente. No respondés vos: coordinás.

Especialistas disponibles (cada uno tiene herramientas acotadas):
- investigador: busca datos en la documentación técnica de FastAPI (Vector DB). NO calcula.
- analista: hace cálculos/estadísticas con los datos ya obtenidos. NO busca información.

Proceso:
1. Evaluá la RÚBRICA con lo que hay en "Contribuciones":
   - datos_con_fuente: ¿están todos los datos de la documentación que la pregunta necesita, con fuente?
   - calculos_verificados: ¿el analista calculó con su herramienta todo lo que pide la pregunta?
   - consistencia: ¿los números del analista coinciden con los del investigador?
   - responde_pregunta: ¿se puede responder TODAS las partes de la pregunta?
2. Decidí:
   - Falta un dato de la documentación -> 'investigador'.
   - Están los datos pero falta un cálculo -> 'analista'.
   - Un aporte es incompleto, no cita fuente o es inconsistente -> devolvéselo al MISMO
     especialista con una instrucción de REFINAMIENTO que diga exactamente qué corregir.
   - Rúbrica aprobada -> 'FINISH'.
3. La instrucción debe ser autocontenida: el especialista NO ve la conversación, solo tu
   instrucción. Incluí los datos numéricos que necesite (por ejemplo, los núcleos o la
   memoria que dio el usuario).

Restricciones: quedan {pasos_restantes} delegaciones en total. Visitas restantes por
especialista: {visitas_restantes}. No delegues a un especialista sin visitas restantes.
"""


def formatear_contribuciones(state: AgentState, max_chars: int = 1500) -> str:
    contribuciones = state.get("contribuciones", [])
    if not contribuciones:
        return "(ninguna todavía)"
    return "\n\n".join(
        f"[paso {c['paso']}] {c['agente']} (herramientas: {', '.join(c['herramientas']) or 'ninguna'})\n"
        f"Instrucción recibida: {c['instruccion']}\n"
        f"Aporte: {c['aporte'][:max_chars]}"
        for c in contribuciones
    )


def visitas_por_agente(state: AgentState) -> Counter:
    return Counter(c["agente"] for c in state.get("contribuciones", []))


def aplicar_guardas(state: AgentState, decision: DecisionSupervisor) -> tuple[Destino, str]:
    """Reglas deterministas que tienen la última palabra sobre la decisión del LLM.

    Devuelve (destino, motivo_cierre). `motivo_cierre` queda vacío si se sigue delegando.
    """
    if decision.next == "FINISH":
        if decision.rubrica.aprobada():
            return "FINISH", "rúbrica de validación aprobada"
        return "FINISH", "el supervisor cerró con la rúbrica incompleta"

    if state.get("pasos", 0) >= config.MAX_PASOS:
        return "FINISH", f"se alcanzó el límite de {config.MAX_PASOS} delegaciones"

    if visitas_por_agente(state)[decision.next] >= config.MAX_VISITAS_POR_AGENTE:
        return "FINISH", (f"'{decision.next}' ya agotó sus {config.MAX_VISITAS_POR_AGENTE} "
                          "intentos (refinamientos)")
    return decision.next, ""


@lru_cache(maxsize=1)
def _decisor_llm():
    return config.obtener_llm().with_structured_output(DecisionSupervisor)


def crear_nodo_supervisor(decisor: Callable[[list[dict]], DecisionSupervisor] | None = None):
    """Devuelve el nodo del grafo. `decisor` se puede inyectar (útil para tests)."""

    def nodo_supervisor(state: AgentState) -> dict:
        pasos = state.get("pasos", 0)
        # Guarda previa: si ya no quedan pasos ni siquiera se consulta al LLM.
        if pasos >= config.MAX_PASOS:
            return {"next_agent": "FINISH", "task_completed": True, "instruccion": "",
                    "motivo_cierre": f"se alcanzó el límite de {config.MAX_PASOS} delegaciones"}

        visitas = visitas_por_agente(state)
        restantes = {a: config.MAX_VISITAS_POR_AGENTE - visitas[a] for a in ("investigador", "analista")}
        prompt = SUPERVISOR_PROMPT.format(
            pasos_restantes=config.MAX_PASOS - pasos,
            visitas_restantes=", ".join(f"{a}={n}" for a, n in restantes.items()),
        )
        # El Supervisor tampoco lee el historial de chat: trabaja sobre el estado estructurado.
        mensajes = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": f"Pregunta original del usuario:\n{state['messages'][0].text}\n\n"
                                        f"Contribuciones:\n{formatear_contribuciones(state)}"},
        ]
        decision = (decisor or _decisor_llm().invoke)(mensajes)
        destino, motivo = aplicar_guardas(state, decision)

        registro: Decision = {
            "paso": pasos,
            "next": destino,
            "razon": decision.razon if destino == decision.next else f"{decision.razon} -> forzado: {motivo}",
            "rubrica": decision.rubrica.model_dump(),
        }
        return {
            "next_agent": destino,
            "instruccion": decision.instruccion if destino != "FINISH" else "",
            "decisiones": [registro],
            "task_completed": destino == "FINISH",
            "motivo_cierre": motivo,
        }

    return nodo_supervisor
