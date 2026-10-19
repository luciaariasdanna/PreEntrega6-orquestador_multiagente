"""Tests sin red ni API keys: herramientas, base de conocimiento y flujo del grafo con
dobles de prueba en lugar de Gemini."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import config
from agents.analyst_agent import calculadora, resumen_estadistico
from agents.supervisor import DecisionSupervisor, RubricaValidacion
from graph import construir_grafo, enrutar
from knowledge_base import BaseDeConocimiento
from state import estado_inicial


# --- Dobles de prueba -------------------------------------------------------

class AgenteFalso:
    """Imita a un agente de `create_agent`: registra lo que recibe y devuelve un aporte fijo."""

    def __init__(self, aporte: str, herramienta: str, argumentos: dict | None = None,
                 resultado: str = "resultado"):
        self.aporte, self.herramienta = aporte, herramienta
        self.argumentos, self.resultado = argumentos or {}, resultado
        self.entradas: list[str] = []

    def invoke(self, entrada, config=None):
        self.entradas.append(entrada["messages"][0].content)
        llamada = {"name": self.herramienta, "args": self.argumentos, "id": "1", "type": "tool_call"}
        return {"messages": [*entrada["messages"],
                             AIMessage(content="", tool_calls=[llamada]),
                             ToolMessage(content=self.resultado, tool_call_id="1", name=self.herramienta),
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


def test_herramientas_disjuntas_entre_especialistas():
    """Especialización: ningún especialista puede hacer el trabajo del otro."""
    from agents.analyst_agent import HERRAMIENTAS as H_ANA
    from agents.research_agent import HERRAMIENTAS as H_INV

    assert [t.name for t in H_INV] == ["buscar_documentacion_fastapi"]
    assert [t.name for t in H_ANA] == ["calculadora", "resumen_estadistico"]
    assert not {t.name for t in H_INV} & {t.name for t in H_ANA}


def test_agente_analista_real_ejecuta_su_herramienta():
    """El agente de `create_agent` (no un doble) ejecuta la calculadora real cuando el
    modelo pide la tool call; solo el LLM está reemplazado por uno guionado."""
    from langchain.agents import create_agent
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    from agents.analyst_agent import HERRAMIENTAS, SYSTEM_PROMPT
    from agents.common import ejecutar_especialista

    class ModeloGuionado(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    modelo = ModeloGuionado(messages=iter([
        AIMessage(content="", tool_calls=[{"name": "calculadora", "args": {"expresion": "(2 * 8) + 1"},
                                           "id": "c1", "type": "tool_call"}]),
        AIMessage(content="Conclusión: 17 workers."),
    ]))
    agente = create_agent(model=modelo, tools=HERRAMIENTAS, system_prompt=SYSTEM_PROMPT)
    salida = ejecutar_especialista(agente, "analista", {"instruccion": "Calculá (2*8)+1", "pasos": 0})

    llamada = salida["contribuciones"][0]["llamadas"][0]
    assert llamada["herramienta"] == "calculadora"
    assert llamada["resultado"] == "(2 * 8) + 1 = 17"  # salida real de la herramienta


def test_investigador_real_no_supera_el_limite_de_busquedas(monkeypatch):
    """ToolCallLimitMiddleware hace cumplir en código el 'máximo 3 búsquedas' del prompt."""
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel

    from agents import research_agent

    class BaseContada:
        consultas: list[str] = []

        def buscar(self, consulta):
            self.consultas.append(consulta)
            return []

    class ModeloInsistente(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    pedidos = [AIMessage(content="", tool_calls=[{"name": "buscar_documentacion_fastapi",
                                                  "args": {"consulta": f"intento {i}"},
                                                  "id": f"b{i}", "type": "tool_call"}])
               for i in range(5)]
    base = BaseContada()
    monkeypatch.setattr(research_agent, "obtener_base", lambda: base)
    monkeypatch.setattr(config, "obtener_llm",
                        lambda: ModeloInsistente(messages=iter([*pedidos, AIMessage(content="listo")])))
    research_agent.crear_agente_investigador.cache_clear()
    try:
        research_agent.crear_agente_investigador().invoke(
            {"messages": [{"role": "user", "content": "buscá"}]})
    finally:
        research_agent.crear_agente_investigador.cache_clear()

    assert len(base.consultas) == config.MAX_BUSQUEDAS_INVESTIGADOR


# --- Grafo ------------------------------------------------------------------

def test_enrutar_mapea_finish_a_sintesis():
    assert enrutar({"next_agent": "FINISH"}) == "sintesis"
    assert enrutar({"next_agent": "analista"}) == "analista"


def test_flujo_completo_investigador_analista_sintesis():
    investigador = AgenteFalso("Workers: (2 x núcleos) + 1 [despliegue_en_produccion.pdf, p. 1]",
                               "buscar_documentacion_fastapi")
    analista = AgenteFalso("(2*8)+1 = 17 workers", "calculadora", {"expresion": "(2*8)+1"},
                           resultado="(2*8)+1 = 17")
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
    assert final["contribuciones"][1]["llamadas"] == [
        {"herramienta": "calculadora", "argumentos": {"expresion": "(2*8)+1"}, "resultado": "(2*8)+1 = 17",
         "exito": True}]
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


def test_evidencia_impide_cerrar_si_el_analista_no_uso_su_calculadora():
    """El LLM dice 'cálculos verificados' pero el analista respondió sin herramientas:
    el control en código lo redirige al analista en vez de cerrar."""
    class SinHerramientas(AgenteFalso):
        def invoke(self, entrada, config=None):
            self.entradas.append(entrada["messages"][0].content)
            return {"messages": [*entrada["messages"], AIMessage(content=self.aporte)]}

    analista = SinHerramientas("17 workers (calculado de cabeza)", "")
    app = construir_grafo(
        investigador=AgenteFalso("dato [despliegue_en_produccion.pdf, p. 1]", "buscar_documentacion_fastapi"),
        analista=analista, llm_sintesis=LLMFalso(),
        decisor=decisor_guionado(
            decision("investigador", "Buscá la regla de workers"),
            decision("analista", "Calculá"),
            decision("FINISH", aprobada=True),   # el LLM quiere cerrar...
            decision("FINISH", aprobada=True),
        ),
    )
    final = app.invoke(estado_inicial("¿Cuántos workers?"))

    redireccion = final["decisiones"][2]
    assert redireccion["next"] == "analista"           # ...pero se lo redirige
    assert redireccion["rubrica"]["calculos_verificados"] is False
    assert "Recalculá con `calculadora`" in analista.entradas[1]
    assert "agotó" in final["motivo_cierre"]           # y la guarda corta el reintento


def test_numeros_sin_respaldo_detecta_resultados_inventados():
    from agents.supervisor import numeros_sin_respaldo

    llamada = {"herramienta": "calculadora", "argumentos": {"expresion": "(2 * 8) + 1"},
               "resultado": "(2 * 8) + 1 = 17", "exito": True}
    state = {
        "messages": [HumanMessage(content="Servidor de 8 núcleos y 16 GB")],
        "contribuciones": [{"agente": "analista", "llamadas": [llamada],
                            "aporte": "(2*8)+1 = **17** workers · 17 * 1 = 17 GB · "
                                      "16 = 16 GB · (16 - 2) / 1 = 14 workers"}],
    }
    # 17 sale de la calculadora y 16 de la pregunta; 14 no tiene respaldo.
    assert numeros_sin_respaldo(state) == ["14"]


def test_evidencia_redirige_si_el_analista_muestra_resultados_sin_calcular():
    analista = AgenteFalso("(2*8)+1 = 17 · (16-2)/1 = 14", "calculadora",
                           {"expresion": "(2*8)+1"}, resultado="(2*8)+1 = 17")
    app = construir_grafo(
        investigador=AgenteFalso("dato [despliegue_en_produccion.pdf, p. 1]", "buscar_documentacion_fastapi"),
        analista=analista, llm_sintesis=LLMFalso(),
        decisor=decisor_guionado(decision("investigador", "Buscá"), decision("analista", "Calculá"),
                                 decision("FINISH", aprobada=True), decision("FINISH", aprobada=True)),
    )
    final = app.invoke(estado_inicial("¿Cuántos workers con 8 núcleos y 16 GB?"))

    assert final["decisiones"][2]["next"] == "analista"
    assert "14" in final["decisiones"][2]["razon"]
    assert "Los resultados 14" in analista.entradas[1]


def test_evidencia_impide_cerrar_sin_ninguna_busqueda():
    investigador = AgenteFalso("dato", "buscar_documentacion_fastapi")
    app = construir_grafo(investigador=investigador, analista=AgenteFalso("", ""),
                          llm_sintesis=LLMFalso(),
                          decisor=decisor_guionado(decision("FINISH", aprobada=True),
                                                   decision("FINISH", aprobada=True)))
    final = app.invoke(estado_inicial("pregunta"))

    assert [d["next"] for d in final["decisiones"]] == ["investigador", "FINISH"]
    assert final["motivo_cierre"] == "rúbrica de validación aprobada"
    assert len(investigador.entradas) == 1


def test_especialista_que_falla_no_tumba_el_grafo():
    class AgenteRoto:
        def invoke(self, entrada, config=None):
            raise RuntimeError("429 RESOURCE_EXHAUSTED")

    app = construir_grafo(investigador=AgenteRoto(), analista=AgenteFalso("", ""),
                          llm_sintesis=LLMFalso(),
                          decisor=decisor_guionado(decision("investigador", "Buscá"),
                                                   decision("FINISH")))
    final = app.invoke(estado_inicial("pregunta"))

    assert "falló" in final["contribuciones"][0]["aporte"]
    assert final["contribuciones"][0]["llamadas"] == []
    assert final["messages"][-1].name == "sintesis"


def test_busqueda_devuelve_error_en_vez_de_lanzar(monkeypatch):
    from agents import research_agent

    class BaseCaida:
        def buscar(self, consulta):
            raise ConnectionError("Pinecone no responde")

    monkeypatch.setattr(research_agent, "obtener_base", lambda: BaseCaida())
    salida = research_agent.buscar_documentacion_fastapi.invoke({"consulta": "workers"})
    assert salida.startswith("Error al buscar")


def test_corte_por_maximo_de_pasos(monkeypatch):
    monkeypatch.setattr(config, "MAX_PASOS", 3)
    monkeypatch.setattr(config, "MAX_VISITAS_POR_AGENTE", 10)
    alternar = iter(["investigador", "analista"] * 10)
    app = construir_grafo(investigador=AgenteFalso("a", "x"), analista=AgenteFalso("b", "y"),
                          llm_sintesis=LLMFalso(), decisor=lambda m: decision(next(alternar), "seguí"))
    final = app.invoke(estado_inicial("pregunta"))

    assert final["pasos"] == 3
    assert "límite" in final["motivo_cierre"]
