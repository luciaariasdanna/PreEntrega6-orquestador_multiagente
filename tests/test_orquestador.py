"""Tests sin red ni API keys: herramientas, base de conocimiento y flujo del grafo con
dobles de prueba en lugar de Gemini."""

import pytest
from langchain_core.messages import AIMessage, ToolMessage

import config
from agents.analyst_agent import calculadora, resumen_estadistico
from agents.supervisor import DecisionSupervisor, RubricaValidacion
from graph import construir_grafo, enrutar
from knowledge_base import BaseDeConocimiento
from state import estado_inicial


# --- Dobles de prueba -------------------------------------------------------

class AgenteFalso:
    """Imita a un agente de `create_agent`: registra lo que recibe y devuelve un aporte fijo."""

    def __init__(self, aporte: str, herramienta: str):
        self.aporte, self.herramienta = aporte, herramienta
        self.entradas: list[str] = []

    def invoke(self, entrada):
        self.entradas.append(entrada["messages"][0].content)
        return {"messages": [*entrada["messages"],
                             ToolMessage(content="...", tool_call_id="1", name=self.herramienta),
                             AIMessage(content=self.aporte)]}


class LLMFalso:
    def invoke(self, prompt):
        return AIMessage(content="respuesta final sintetizada")


def decision(next_, instruccion="", aprobada=False):
    rubrica = RubricaValidacion(datos_con_fuente=aprobada, calculos_verificados=aprobada,
                                consistencia=aprobada, responde_pregunta=aprobada)
    return DecisionSupervisor(rubrica=rubrica, next=next_, instruccion=instruccion, razon="test")


def decisor_guionado(*decisiones):
    pendientes = list(decisiones)
    return lambda mensajes: pendientes.pop(0)


# --- Herramientas -----------------------------------------------------------

def test_calculadora_aritmetica_y_funciones():
    assert calculadora.invoke({"expresion": "(2 * 8) + 1"}) == "(2 * 8) + 1 = 17"
    assert calculadora.invoke({"expresion": "floor((16 - 2) / 1)"}).endswith("= 14")


@pytest.mark.parametrize("maliciosa", ["__import__('os').system('dir')", "open('x')", "9 ** 9 ** 9"])
def test_calculadora_rechaza_codigo_arbitrario(maliciosa):
    assert calculadora.invoke({"expresion": maliciosa}).startswith("Error")


def test_resumen_estadistico():
    assert "promedio=2" in resumen_estadistico.invoke({"valores": [1, 2, 3]})


def test_bm25_local_encuentra_el_pdf_de_despliegue():
    base = BaseDeConocimiento(usar_pinecone=False)
    documentos = base.buscar("cantidad de workers gunicorn núcleos")
    assert documentos[0].metadata["source"] == "despliegue_en_produccion.pdf"


# --- Grafo ------------------------------------------------------------------

def test_enrutar_mapea_finish_a_sintesis():
    assert enrutar({"next_agent": "FINISH"}) == "sintesis"
    assert enrutar({"next_agent": "analista"}) == "analista"


def test_flujo_completo_investigador_analista_sintesis():
    investigador = AgenteFalso("Workers: (2 x núcleos) + 1 [despliegue_en_produccion.pdf, p. 1]",
                               "buscar_documentacion_fastapi")
    analista = AgenteFalso("(2*8)+1 = 17 workers", "calculadora")
    app = construir_grafo(
        investigador=investigador, analista=analista, llm_sintesis=LLMFalso(),
        decisor=decisor_guionado(
            decision("investigador", "Buscá la regla de workers"),
            decision("analista", "Calculá con 8 núcleos"),
            decision("FINISH", aprobada=True),
        ),
    )
    final = app.invoke(estado_inicial("¿Cuántos workers con 8 núcleos?"))

    assert [c["agente"] for c in final["contribuciones"]] == ["investigador", "analista"]
    assert final["contribuciones"][1]["herramientas"] == ["calculadora"]
    assert final["pasos"] == 2 and final["task_completed"]
    assert final["motivo_cierre"] == "rúbrica de validación aprobada"
    assert final["messages"][-1].name == "sintesis"
    # Contexto acotado: el investigador solo recibe la instrucción del Supervisor...
    assert investigador.entradas == ["Buscá la regla de workers"]
    # ...y el analista la instrucción + los datos del investigador, no el historial completo.
    assert "(2 x núcleos) + 1" in analista.entradas[0]
    assert "¿Cuántos workers" not in analista.entradas[0]


def test_refinamiento_y_corte_por_visitas_maximas():
    """Un supervisor que pide refinar indefinidamente al mismo agente es cortado por la guarda."""
    investigador = AgenteFalso("dato incompleto", "buscar_documentacion_fastapi")
    app = construir_grafo(investigador=investigador, analista=AgenteFalso("", ""),
                          llm_sintesis=LLMFalso(),
                          decisor=lambda m: decision("investigador", "Refiná: citá la fuente"))
    final = app.invoke(estado_inicial("pregunta"))

    assert len(investigador.entradas) == config.MAX_VISITAS_POR_AGENTE
    assert "agotó" in final["motivo_cierre"]
    assert final["decisiones"][-1]["next"] == "FINISH"


def test_corte_por_maximo_de_pasos(monkeypatch):
    monkeypatch.setattr(config, "MAX_PASOS", 3)
    monkeypatch.setattr(config, "MAX_VISITAS_POR_AGENTE", 10)
    alternar = iter(["investigador", "analista"] * 10)
    app = construir_grafo(investigador=AgenteFalso("a", "x"), analista=AgenteFalso("b", "y"),
                          llm_sintesis=LLMFalso(), decisor=lambda m: decision(next(alternar), "seguí"))
    final = app.invoke(estado_inicial("pregunta"))

    assert final["pasos"] == 3
    assert "límite" in final["motivo_cierre"]
