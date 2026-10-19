"""Configuración central: modelo, límites del orquestador y conexión al Vector DB.

Todo se lee del `.env` (ver `.env.example`) para que ningún módulo hardcodee valores.
"""

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

RAIZ = Path(__file__).resolve().parent
DATA_DIR = RAIZ / "data"

# --- LLM --------------------------------------------------------------------
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest")

# --- Límites del orquestador (anti "Supervisor Infinito") --------------------
# Cantidad máxima de delegaciones a especialistas en una misma consulta.
MAX_PASOS = int(os.getenv("MAX_PASOS", "6"))
# Veces que un mismo especialista puede ser invocado (1ra vez + refinamientos).
MAX_VISITAS_POR_AGENTE = int(os.getenv("MAX_VISITAS_POR_AGENTE", "2"))
# Tope de tool calls de cada especialista DENTRO de una visita (ToolCallLimitMiddleware).
MAX_BUSQUEDAS_INVESTIGADOR = int(os.getenv("MAX_BUSQUEDAS_INVESTIGADOR", "3"))
MAX_CALCULOS_ANALISTA = int(os.getenv("MAX_CALCULOS_ANALISTA", "8"))
# Red de seguridad del bucle ReAct interno de cada especialista (pasos del subgrafo).
RECURSION_LIMIT_ESPECIALISTA = int(os.getenv("RECURSION_LIMIT_ESPECIALISTA", "25"))

# --- Vector DB de la Pre-entrega 4 (Pinecone) -------------------------------
# Mismos valores que la PE4: el índice ya está cargado, acá solo se consulta.
INDEX_NAME = os.getenv("INDEX_NAME", "fastapi-docs-rag")
NAMESPACE = os.getenv("PINECONE_NAMESPACE", "fastapi-docs")
EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIM = 768

# Chunking idéntico al de la PE4: así los chunk_id locales coinciden con los de Pinecone
# y el EnsembleRetriever puede deduplicar resultados de BM25 y del vectorial.
CHUNK_SIZE = 600
CHUNK_OVERLAP = 100
TOP_K = 4
CANDIDATOS_POR_RETRIEVER = 10


def requerir_variable(nombre: str) -> str:
    valor = os.getenv(nombre, "").strip()
    if not valor:
        raise RuntimeError(
            f"Falta la variable de entorno {nombre}. Copiá .env.example a .env y completala."
        )
    return valor


def pinecone_habilitado() -> bool:
    return bool(os.getenv("PINECONE_API_KEY", "").strip())


@lru_cache(maxsize=1)
def obtener_llm():
    """Instancia única del chat model (import perezoso: los tests no necesitan la API key)."""
    from langchain_google_genai import ChatGoogleGenerativeAI

    if not os.getenv("GEMINI_API_KEY", "").strip():
        requerir_variable("GOOGLE_API_KEY")
    return ChatGoogleGenerativeAI(model=GEMINI_MODEL, temperature=0)
