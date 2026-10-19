"""Agente de Análisis/Cómputo.

Herramientas acotadas: una calculadora segura y un resumen estadístico. No puede buscar
información: trabaja SOLO con los datos que le pasa el Supervisor (los que reunió el
Investigador).
"""

import ast
import math
import operator as op
import statistics
from functools import lru_cache

from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware
from langchain_core.tools import tool

import config
from agents.common import ejecutar_especialista
from state import AgentState

SYSTEM_PROMPT = """Sos el agente ANALISTA de un equipo multi-agente.
Tu única función es procesar datos numéricos que YA te fueron entregados.

Reglas:
- Hacé TODOS los cálculos con tus herramientas (`calculadora`, `resumen_estadistico`);
  nunca calcules "de cabeza". Una llamada por cada resultado que muestres, incluso los
  triviales (por ejemplo `17 * 1`): el supervisor verifica cada resultado contra tus
  llamadas.
- NO busques ni inventes datos nuevos. Si te falta un dato para calcular, respondé
  exactamente qué dato falta.
- Si los datos recibidos ya traen un número derivado (por ejemplo, una fórmula ya
  aplicada), NO lo des por bueno: recalculalo con `calculadora`.
- Mostrá cada cálculo como: expresión = resultado (con unidades).
- Si los datos llevan a una conclusión relevante (por ejemplo, que un recurso no
  alcanza), señalala explícitamente.
- Cerrá con una línea 'Conclusión:' de una o dos oraciones."""

# --- Calculadora segura -----------------------------------------------------
# eval() sobre texto generado por un LLM es ejecución de código arbitrario. Parseamos con
# `ast` y solo permitimos aritmética y un puñado de funciones matemáticas.

_OPERADORES = {
    ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul, ast.Div: op.truediv,
    ast.FloorDiv: op.floordiv, ast.Mod: op.mod, ast.Pow: op.pow,
    ast.USub: op.neg, ast.UAdd: op.pos,
}
_FUNCIONES = {
    "round": round, "min": min, "max": max, "abs": abs,
    "floor": math.floor, "ceil": math.ceil, "sqrt": math.sqrt,
}
_MAX_EXPONENTE = 100


def _evaluar(nodo: ast.AST) -> float:
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, (int, float)) \
            and not isinstance(nodo.value, bool):
        return nodo.value
    if isinstance(nodo, ast.BinOp) and type(nodo.op) in _OPERADORES:
        izquierda, derecha = _evaluar(nodo.left), _evaluar(nodo.right)
        if isinstance(nodo.op, ast.Pow) and abs(derecha) > _MAX_EXPONENTE:
            raise ValueError(f"exponente demasiado grande (máx. {_MAX_EXPONENTE})")
        return _OPERADORES[type(nodo.op)](izquierda, derecha)
    if isinstance(nodo, ast.UnaryOp) and type(nodo.op) in _OPERADORES:
        return _OPERADORES[type(nodo.op)](_evaluar(nodo.operand))
    if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
            and nodo.func.id in _FUNCIONES and not nodo.keywords):
        return _FUNCIONES[nodo.func.id](*(_evaluar(a) for a in nodo.args))
    raise ValueError(f"elemento no permitido: {ast.dump(nodo)[:60]}")


@tool
def calculadora(expresion: str) -> str:
    """Evalúa una expresión aritmética. Soporta + - * / // % ** y paréntesis, y las
    funciones round, min, max, abs, floor, ceil, sqrt.
    Ejemplos: '(2 * 8) + 1', '17 * 1.0', 'floor(16 / 1.0)'."""
    try:
        resultado = _evaluar(ast.parse(expresion, mode="eval").body)
    except Exception as e:
        return f"Error al calcular '{expresion}': {e}"
    if isinstance(resultado, float) and resultado.is_integer():
        resultado = int(resultado)
    return f"{expresion} = {resultado}"


@tool
def resumen_estadistico(valores: list[float]) -> str:
    """Calcula cantidad, suma, promedio, mediana, mínimo, máximo y desvío estándar
    de una lista de números."""
    if not valores:
        return "Error: la lista de valores está vacía."
    desvio = statistics.stdev(valores) if len(valores) > 1 else 0.0
    return (
        f"n={len(valores)}, suma={sum(valores):g}, promedio={statistics.mean(valores):g}, "
        f"mediana={statistics.median(valores):g}, min={min(valores):g}, "
        f"max={max(valores):g}, desvio={desvio:.4g}"
    )


HERRAMIENTAS = [calculadora, resumen_estadistico]


@lru_cache(maxsize=1)
def crear_agente_analista():
    limite = ToolCallLimitMiddleware(run_limit=config.MAX_CALCULOS_ANALISTA)
    return create_agent(model=config.obtener_llm(), tools=HERRAMIENTAS,
                        system_prompt=SYSTEM_PROMPT, middleware=[limite], name="analista")


def contexto_para_analista(state: AgentState) -> str:
    """Solo los aportes del Investigador: el Analista no ve la conversación completa
    ni las decisiones del Supervisor, únicamente los datos sobre los que debe calcular."""
    datos = [c["aporte"] for c in state.get("contribuciones", []) if c["agente"] == "investigador"]
    if not datos:
        return ""
    return "Datos reunidos por el Investigador:\n" + "\n\n".join(datos)


def crear_nodo_analista(agente=None):
    """Devuelve el nodo del grafo. `agente` se puede inyectar (útil para tests)."""

    def nodo_analista(state: AgentState) -> dict:
        return ejecutar_especialista(agente or crear_agente_analista(), "analista", state,
                                     contexto=contexto_para_analista(state))

    return nodo_analista
