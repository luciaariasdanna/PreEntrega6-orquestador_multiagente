"""Fuente externa del Investigador: Vector DB de la Pre-entrega 4.

Reutiliza el diseño de la PE4 (documentación de FastAPI en castellano, 10 archivos):

- Si hay `PINECONE_API_KEY` y el índice existe -> retriever HÍBRIDO: BM25 (léxico, local)
  + Pinecone (semántico, embeddings de Gemini) fusionados con un `EnsembleRetriever` (RRF).
- Si no hay Pinecone (o no responde) -> "búsqueda simulada": solo BM25 sobre el mismo
  corpus local de `data/`. El sistema sigue funcionando sin la Vector DB.
"""

import json
import logging
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

import config

log = logging.getLogger(__name__)

SEPARADORES = ["\n## ", "\n### ", "\n\n", "\n", ". ", " ", ""]

STOPWORDS_ES = frozenset("""
a al algo algun alguna algunas alguno algunos ante antes asi aun cada como con contra
cual cuales cuando de del desde donde dos e el ella ellas ellos en entre era es esa esas
ese eso esos esta estan estas este esto estos fue fueron ha hay hace hacer la las le les
lo los mas me mi mis muy ni no nos o otra otro para pero poco por porque puede que quien
se sea segun ser si sin sobre son su sus tambien tan te tiene tienen todo todos tu un una
uno unos y ya yo
""".split())


# --- Carga del corpus (mismo formato y chunk_id que la PE4) -----------------

def _front_matter(texto: str) -> tuple[dict, str]:
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?", texto, flags=re.DOTALL)
    if not m:
        return {}, texto
    meta = {}
    for linea in m.group(1).splitlines():
        if ":" in linea:
            clave, valor = (p.strip() for p in linea.split(":", 1))
            meta[clave] = valor
    return meta, texto[m.end():]


def _cargar_archivo(ruta: Path, categoria: str) -> list[Document]:
    base = {"source": ruta.name, "categoria": categoria}
    if ruta.suffix == ".md":
        meta, cuerpo = _front_matter(ruta.read_text(encoding="utf-8"))
        return [Document(page_content=cuerpo.strip(),
                         metadata={**base, "page": 1, "titulo": meta.get("titulo", ruta.stem)})]
    if ruta.suffix == ".json":
        datos = json.loads(ruta.read_text(encoding="utf-8"))
        return [
            Document(page_content=f"Pregunta: {e['pregunta']}\nRespuesta: {e['respuesta']}",
                     metadata={**base, "page": i, "titulo": datos.get("titulo", ruta.stem)})
            for i, e in enumerate(datos["entradas"], start=1)
        ]
    if ruta.suffix == ".pdf":
        from pypdf import PdfReader

        return [
            Document(page_content=texto, metadata={**base, "page": i, "titulo": ruta.stem})
            for i, pagina in enumerate(PdfReader(str(ruta)).pages, start=1)
            if (texto := (pagina.extract_text() or "").strip())
        ]
    return []


def _chunk_id(source: str, page: int, indice: int) -> str:
    base = re.sub(r"[^A-Za-z0-9_-]+", "-", Path(source).stem).strip("-").lower()
    return f"{base}-p{page}-c{indice}"


@lru_cache(maxsize=1)
def cargar_corpus(data_dir: Path = config.DATA_DIR) -> tuple[Document, ...]:
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name="cl100k_base", chunk_size=config.CHUNK_SIZE,
        chunk_overlap=config.CHUNK_OVERLAP, separators=SEPARADORES,
    )
    chunks = []
    for ruta in sorted(Path(data_dir).rglob("*")):
        if not ruta.is_file():
            continue
        relativa = ruta.relative_to(data_dir)
        categoria = relativa.parts[0] if len(relativa.parts) > 1 else "general"
        for documento in _cargar_archivo(ruta, categoria):
            for i, chunk in enumerate(splitter.split_documents([documento])):
                chunk.id = chunk.metadata["chunk_id"] = _chunk_id(chunk.metadata["source"],
                                                                  chunk.metadata["page"], i)
                chunks.append(chunk)
    return tuple(chunks)


# --- Retrievers -------------------------------------------------------------

def tokenizar(texto: str) -> list[str]:
    """Minúsculas, sin tildes y sin stopwords (el BM25 por defecto hace solo `split()`)."""
    texto = unicodedata.normalize("NFKD", texto.lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return [t for t in re.findall(r"[a-z0-9_]+", texto) if t not in STOPWORDS_ES]


def _crear_bm25(corpus: list[Document]):
    from langchain_community.retrievers import BM25Retriever

    class BM25SinCeros(BM25Retriever):
        """Descarta documentos con puntaje 0 (el original siempre devuelve k)."""

        def _get_relevant_documents(self, query, *, run_manager):
            puntajes = self.vectorizer.get_scores(self.preprocess_func(query))
            orden = sorted(range(len(puntajes)), key=lambda i: puntajes[i], reverse=True)
            return [self.docs[i] for i in orden[: self.k] if puntajes[i] > 0]

    return BM25SinCeros.from_documents(corpus, k=config.CANDIDATOS_POR_RETRIEVER,
                                       preprocess_func=tokenizar)


class PineconeRetriever(BaseRetriever):
    """Retriever semántico sobre el índice de la PE4 (SDK nativo de Pinecone)."""

    index: Any
    embeddings: Any
    namespace: str = config.NAMESPACE
    k: int = config.CANDIDATOS_POR_RETRIEVER

    def _get_relevant_documents(self, query: str, *,
                                run_manager: CallbackManagerForRetrieverRun) -> list[Document]:
        respuesta = self.index.query(vector=self.embeddings.embed_query(query), top_k=self.k,
                                     namespace=self.namespace, include_metadata=True)
        documentos = []
        for match in respuesta.matches:
            metadata = dict(match.metadata or {})
            texto = metadata.pop("text", "")
            metadata.setdefault("chunk_id", match.id)
            documentos.append(Document(id=match.id, page_content=texto, metadata=metadata))
        return documentos


def _crear_pinecone() -> PineconeRetriever:
    from langchain_google_genai import GoogleGenerativeAIEmbeddings
    from pinecone import Pinecone

    pc = Pinecone(api_key=config.requerir_variable("PINECONE_API_KEY"))
    if not pc.has_index(config.INDEX_NAME):
        raise RuntimeError(f"El índice '{config.INDEX_NAME}' no existe (corré la ingesta de la PE4).")
    embeddings = GoogleGenerativeAIEmbeddings(model=config.EMBEDDING_MODEL,
                                              output_dimensionality=config.EMBEDDING_DIM)
    return PineconeRetriever(index=pc.Index(config.INDEX_NAME), embeddings=embeddings)


class BaseDeConocimiento:
    """Encapsula el retriever (híbrido o solo BM25) y expone `buscar()`."""

    def __init__(self, usar_pinecone: bool | None = None):
        corpus = list(cargar_corpus())
        bm25 = _crear_bm25(corpus)
        self.modo = "bm25 (local)"
        self.retriever: BaseRetriever = bm25

        if usar_pinecone if usar_pinecone is not None else config.pinecone_habilitado():
            try:
                from langchain_classic.retrievers import EnsembleRetriever

                self.retriever = EnsembleRetriever(retrievers=[bm25, _crear_pinecone()],
                                                   weights=[0.5, 0.5], id_key="chunk_id")
                self.modo = "híbrido (BM25 + Pinecone)"
            except Exception as e:  # sin red, índice borrado, key inválida...
                log.warning("Pinecone no disponible (%s). Se usa solo BM25 local.", e)

    def buscar(self, consulta: str, k: int = config.TOP_K) -> list[Document]:
        return self.retriever.invoke(consulta)[:k]


@lru_cache(maxsize=1)
def obtener_base() -> BaseDeConocimiento:
    base = BaseDeConocimiento()
    log.info("Base de conocimiento lista en modo %s", base.modo)
    return base
