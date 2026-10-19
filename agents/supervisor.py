"""Supervisor: router inteligente, validador y controlador de flujo.

En cada turno el Supervisor:
1. Evalúa una RÚBRICA de validación sobre las contribuciones acumuladas.
2. Decide el próximo nodo (`investigador`, `analista` o `FINISH`) y redacta una
   instrucción autocontenida para ese especialista (puede ser un pedido de refinamiento).
3. Contrasta la rúbrica con la EVIDENCIA de herramientas registrada en el estado: no se
   puede cerrar diciendo "datos con fuente" si nadie buscó, ni "cálculos verificados" si
   el analista no usó su calculadora.
4. Pasa por guardas deterministas en código que garantizan la parada aunque el LLM
   insista en seguir delegando (anti "Supervisor Infinito").
"""

import math
import re
from collections import Counter
from functools import lru_cache
from typing import Callable, Literal

from pydantic import BaseModel, Field

import config
from state import AgentState, Contribucion, Decision, Destino


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
1. Evaluá la RÚBRICA con lo que hay en "Contribuciones" (cada una trae las llamadas a
   herramientas que el especialista ejecutó de verdad, con argumentos y resultado):
   - datos_con_fuente: ¿están todos los datos de la documentación que la pregunta necesita,
     con fuente, y salen de una llamada a `buscar_documentacion_fastapi`?
   - calculos_verificados: ¿CADA número derivado (que no aparece textual en la pregunta ni
     en la documentación) sale de una llamada a `calculadora` del analista? Si el
     investigador hizo una cuenta por su cuenta, NO está verificada: delegá al analista.
   - consistencia: ¿los números del analista coinciden con los del investigador?
   - responde_pregunta: ¿se puede responder TODAS las partes de la pregunta?
2. Decidí:
   - Falta un dato de la documentación -> 'investigador'.
   - Están los datos pero falta un cálculo -> 'analista'.
   - Un aporte es incompleto, no cita fuente o es inconsistente -> devolvéselo al MISMO
     especialista con una instrucción de REFINAMIENTO que diga exactamente qué corregir.
   - Rúbrica aprobada -> 'FINISH'.
3. La instrucción debe ser autocontenida: el especialista NO ve la conversación, solo tu
   instrucción.
   - Al investigador pedile SOLO qué buscar (la regla, el dato, la fórmula). No le pases
     los números del usuario: aplicarlos es trabajo del analista.
   - Al analista pasale los números del usuario que necesite (núcleos, memoria, etc.) y
     qué tiene que calcular; los datos del investigador ya le llegan solos.

Restricciones: quedan {pasos_restantes} delegaciones en total. Visitas restantes por
especialista: {visitas_restantes}. No delegues a un especialista sin visitas restantes.
"""


def formatear_llamadas(contribucion: Contribucion) -> str:
    llamadas = contribucion.get("llamadas", [])
    if not llamadas:
        return "  (ninguna: el aporte NO está respaldado por herramientas)"
    return "\n".join(
        f"  - {ll['herramienta']}({', '.join(f'{k}={v!r}' for k, v in ll['argumentos'].items())})"
        f" -> {'' if ll['exito'] else '[FALLÓ] '}{ll['resultado']}"
        for ll in llamadas
    )


def formatear_contribuciones(state: AgentState, max_chars: int = 1500) -> str:
    contribuciones = state.get("contribuciones", [])
    if not contribuciones:
        return "(ninguna todavía)"
    return "\n\n".join(
        f"[paso {c['paso']}] {c['agente']}\n"
        f"Instrucción recibida: {c['instruccion']}\n"
        f"Llamadas a herramientas:\n{formatear_llamadas(c)}\n"
        f"Aporte: {c['aporte'][:max_chars]}"
        for c in contribuciones
    )


def visitas_por_agente(state: AgentState) -> Counter:
    return Counter(c["agente"] for c in state.get("contribuciones", []))


HERRAMIENTAS_DE_BUSQUEDA = {"buscar_documentacion_fastapi"}
HERRAMIENTAS_DE_CALCULO = {"calculadora", "resumen_estadistico"}


def _uso(state: AgentState, agente: str, herramientas: set[str]) -> bool | None:
    """True/False si `agente` usó alguna de `herramientas` sin error; None si nunca participó."""
    aportes = [c for c in state.get("contribuciones", []) if c["agente"] == agente]
    if not aportes:
        return None
    return any(ll["herramienta"] in herramientas and ll["exito"]
               for c in aportes for ll in c.get("llamadas", []))


_NUMERO = r"-?\d+(?:[.,]\d+)?"


def _a_float(texto: str) -> float:
    return float(texto.replace(",", "."))


def numeros_sin_respaldo(state: AgentState) -> list[str]:
    """Resultados (`= N`) que muestra el último aporte del analista y que no salen de
    ninguna llamada exitosa a sus herramientas ni aparecen en la pregunta del usuario."""
    aportes = [c for c in state.get("contribuciones", []) if c["agente"] == "analista"]
    if not aportes:
        return []
    respaldados = [_a_float(n) for n in re.findall(_NUMERO, state["messages"][0].text)]
    respaldados += [_a_float(n) for c in aportes for ll in c.get("llamadas", []) if ll["exito"]
                    for n in re.findall(_NUMERO, ll["resultado"].split("=")[-1])]
    afirmados = re.findall(rf"=\s*\**\s*({_NUMERO})", aportes[-1]["aporte"])
    return [n for n in dict.fromkeys(afirmados)
            if not any(math.isclose(_a_float(n), r, rel_tol=1e-2, abs_tol=1e-6) for r in respaldados)]


def contrastar_con_evidencia(state: AgentState, decision: DecisionSupervisor) -> DecisionSupervisor:
    """La rúbrica la evalúa un LLM; acá se contrasta en código con las tool calls registradas.

    Si el Supervisor quiere cerrar afirmando algo que la evidencia no respalda, se corrige la
    rúbrica y se redirige al especialista que tiene que aportarlo. Las guardas de visitas y
    pasos se aplican después, así que esta corrección nunca genera un bucle.
    """
    if decision.next != "FINISH" or not decision.rubrica.aprobada():
        return decision
    pregunta = state["messages"][0].text

    if not _uso(state, "investigador", HERRAMIENTAS_DE_BUSQUEDA):  # nunca buscó o falló
        return decision.model_copy(update={
            "rubrica": decision.rubrica.model_copy(update={"datos_con_fuente": False}),
            "next": "investigador",
            "instruccion": "Buscá con `buscar_documentacion_fastapi` los datos de la documentación "
                           f"que responden esta pregunta y citá la fuente de cada uno: {pregunta}",
            "razon": f"{decision.razon} [evidencia: no hay búsquedas que respalden los datos]",
        })

    if _uso(state, "analista", HERRAMIENTAS_DE_CALCULO) is False:  # participó sin calcular
        return decision.model_copy(update={
            "rubrica": decision.rubrica.model_copy(update={"calculos_verificados": False}),
            "next": "analista",
            "instruccion": "Recalculá con `calculadora` cada número de tu respuesta anterior; "
                           f"no respondas sin usar la herramienta. Pregunta: {pregunta}",
            "razon": f"{decision.razon} [evidencia: el analista no usó su calculadora]",
        })

    if sin_respaldo := numeros_sin_respaldo(state):
        return decision.model_copy(update={
            "rubrica": decision.rubrica.model_copy(update={"calculos_verificados": False}),
            "next": "analista",
            "instruccion": f"Los resultados {', '.join(sin_respaldo)} de tu respuesta anterior no "
                           "salen de ninguna llamada a `calculadora`. Recalculá cada uno con la "
                           f"herramienta y corregí la respuesta. Pregunta: {pregunta}",
            "razon": f"{decision.razon} [evidencia: resultados sin respaldo: {', '.join(sin_respaldo)}]",
        })
    return decision


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
        decision = contrastar_con_evidencia(state, (decisor or _decisor_llm().invoke)(mensajes))
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
