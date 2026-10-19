"""Punto de entrada: corre una consulta mostrando el flujo de delegación paso a paso.

    python main.py                       # consulta de demo (requiere investigador + analista)
    python main.py "tu pregunta"         # consulta propia
    python main.py --grafo               # exporta el diagrama a docs/grafo.mmd (y .png)
"""

import argparse
import logging
import sys

from state import estado_inicial

PREGUNTA_DEMO = (
    "Voy a desplegar mi API de FastAPI en un servidor de 8 núcleos con Gunicorn y workers de "
    "Uvicorn. La app carga un modelo de machine learning de 1 GB en memoria. Según la "
    "documentación, ¿cuántos workers conviene levantar para empezar y cuánta memoria "
    "consumirían en total? Si el servidor tiene 16 GB de RAM, ¿alcanza? Si no alcanza, "
    "¿cuál es la cantidad máxima de workers que entra dejando 2 GB libres para el sistema?"
)

ICONOS = {"supervisor": "🧭", "investigador": "🔎", "analista": "🧮", "sintesis": "📝"}


def imprimir_evento(nodo: str, actualizacion: dict) -> None:
    print(f"{ICONOS.get(nodo, '•')} {nodo.upper()}")
    if nodo == "supervisor":
        for d in actualizacion.get("decisiones", []):
            rubrica = " ".join(f"{k}={'✔' if v else '✘'}" for k, v in d["rubrica"].items())
            print(f"   rúbrica: {rubrica}")
            print(f"   decisión: -> {d['next']}  ({d['razon']})")
        if actualizacion.get("instruccion"):
            print(f"   instrucción: {actualizacion['instruccion']}")
        if actualizacion.get("motivo_cierre"):
            print(f"   cierre: {actualizacion['motivo_cierre']}")
    for c in actualizacion.get("contribuciones", []):
        print(f"   herramientas usadas: {', '.join(c['herramientas']) or 'ninguna'}")
        for ll in c.get("llamadas", []):
            args = ", ".join(f"{k}={v!r}" for k, v in ll["argumentos"].items())
            print(f"     ↳ {ll['herramienta']}({args}) -> {'' if ll['exito'] else '[FALLÓ] '}{ll['resultado']}")
        print("   aporte: " + c["aporte"].replace("\n", "\n           "))
    if nodo == "sintesis":
        print("\n" + "=" * 70 + "\nRESPUESTA FINAL\n" + "=" * 70)
        print(actualizacion["messages"][-1].text)
    print()


def ejecutar(pregunta: str) -> dict:
    from graph import app

    print(f"❓ {pregunta}\n")
    estado_final = None
    for modo, datos in app.stream(estado_inicial(pregunta), stream_mode=["updates", "values"]):
        if modo == "updates":
            for nodo, actualizacion in datos.items():
                imprimir_evento(nodo, actualizacion)
        else:
            estado_final = datos

    recorrido = " -> ".join(["supervisor"] + [
        x for d in estado_final["decisiones"]
        for x in ((d["next"], "supervisor") if d["next"] != "FINISH" else ("sintesis",))
    ])
    print(f"\n🗺️  Recorrido: {recorrido}")
    print(f"   Delegaciones: {estado_final['pasos']} | Motivo de cierre: {estado_final['motivo_cierre']}")
    return estado_final


def exportar_grafo() -> None:
    from pathlib import Path

    from graph import app

    docs = Path(__file__).parent / "docs"
    docs.mkdir(exist_ok=True)
    grafo = app.get_graph()
    (docs / "grafo.mmd").write_text(grafo.draw_mermaid(), encoding="utf-8")
    print(f"Mermaid guardado en {docs / 'grafo.mmd'}")
    try:
        (docs / "grafo.png").write_bytes(grafo.draw_mermaid_png())  # usa la API de mermaid.ink
        print(f"PNG guardado en {docs / 'grafo.png'}")
    except Exception as e:
        print(f"No se pudo generar el PNG ({e}); el .mmd se puede pegar en https://mermaid.live")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # emojis en la consola de Windows
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Orquestador multi-agente (Supervisor + especialistas)")
    parser.add_argument("pregunta", nargs="?", default=PREGUNTA_DEMO)
    parser.add_argument("--grafo", action="store_true", help="exporta el diagrama del grafo y sale")
    args = parser.parse_args()

    if args.grafo:
        exportar_grafo()
    else:
        ejecutar(args.pregunta)


if __name__ == "__main__":
    main()
