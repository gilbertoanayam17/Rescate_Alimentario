"""Base de conocimiento para el RAG del Agente de Inocuidad.

DUEÑO: Gilberto (flujo 1).

`BaseConocimientoVectorial` indexa los `.md` de `datos/conocimiento/` (extractos textuales de
la NOM-251-SSA1-2009 y los criterios internos de donación): los parte por encabezados `## `,
calcula embeddings con `ClienteLLM.embeber` (nomic-embed-text en Ollama) y busca por
similitud coseno con FAISS (`IndexFlatIP` sobre vectores normalizados) o, si FAISS no está
instalado, con NumPy. El índice se guarda en `datos/indice/` y se reconstruye solo cuando
cambia su huella (contenido de los `.md` + cliente LLM + modelo de embeddings).

El contenedor siempre llama a `crear_base_conocimiento`; no cambies su firma.
"""
from __future__ import annotations

import hashlib
import json
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
from pydantic import BaseModel

from rescate.llm.cliente import ClienteLLM, ErrorLLM

try:  # FAISS es opcional: sin él se usa NumPy (sección 5.5 del plan del equipo)
    import faiss
except ImportError:  # pragma: no cover - depende del entorno
    faiss = None

if TYPE_CHECKING:
    from rescate.config import Configuracion

VERSION_INDICE = "1"
MAX_CARACTERES = 1200
TAM_LOTE = 16
#: nomic-embed-text distingue documentos y consultas con estos prefijos.
PREFIJOS_NOMIC = ("search_document: ", "search_query: ")


class Fragmento(BaseModel):
    texto: str
    fuente: str  # nombre del archivo de origen
    seccion: str = ""  # p. ej. "NOM-251-SSA1-2009, numeral 7.3.3"
    puntaje: float = 0.0


class BaseConocimiento(ABC):
    @abstractmethod
    def buscar(self, consulta: str, k: int = 4) -> list[Fragmento]: ...

    def disponible(self) -> bool:
        return True


class BaseConocimientoVacia(BaseConocimiento):
    def buscar(self, consulta: str, k: int = 4) -> list[Fragmento]:
        return []

    def disponible(self) -> bool:
        return False


# ------------------------------------------------------------------ fragmentación


def _partir_en_parrafos(texto: str, maximo: int = MAX_CARACTERES) -> list[str]:
    """Agrupa párrafos completos en trozos de hasta `maximo` caracteres."""
    trozos: list[str] = []
    actual = ""
    for parrafo in (p.strip() for p in texto.split("\n\n")):
        if not parrafo:
            continue
        if actual and len(actual) + 2 + len(parrafo) > maximo:
            trozos.append(actual)
            actual = parrafo
        else:
            actual = f"{actual}\n\n{parrafo}" if actual else parrafo
    if actual:
        trozos.append(actual)
    return trozos


def fragmentar(markdown: str, fuente: str, maximo: int = MAX_CARACTERES) -> list[Fragmento]:
    """Un fragmento por encabezado `## ` (el encabezado es la sección); lo anterior al primero se omite."""
    fragmentos: list[Fragmento] = []
    for bloque in re.split(r"^## ", markdown, flags=re.MULTILINE)[1:]:
        seccion, _, cuerpo = bloque.partition("\n")
        cuerpo = cuerpo.strip()
        if not cuerpo:
            continue
        for trozo in _partir_en_parrafos(cuerpo, maximo):
            fragmentos.append(Fragmento(texto=trozo, fuente=fuente, seccion=seccion.strip()))
    return fragmentos


def _normalizar(matriz: np.ndarray) -> np.ndarray:
    normas = np.linalg.norm(matriz, axis=1, keepdims=True)
    normas[normas == 0] = 1.0
    return (matriz / normas).astype("float32")


# ------------------------------------------------------------- base vectorial


class BaseConocimientoVectorial(BaseConocimiento):
    """RAG local: fragmentos de los `.md`, embeddings normalizados y búsqueda por coseno."""

    def __init__(
        self,
        ruta_conocimiento: str | Path,
        ruta_indice: str | Path,
        llm: ClienteLLM,
        modelo_embeddings: str = "",
        prefijos: tuple[str, str] = ("", ""),
        forzar: bool = False,
    ) -> None:
        self.ruta_conocimiento = Path(ruta_conocimiento)
        self.ruta_indice = Path(ruta_indice)
        self.llm = llm
        self.modelo_embeddings = modelo_embeddings
        self.prefijo_documento, self.prefijo_consulta = prefijos
        self.motor = "faiss" if faiss is not None else "numpy"
        self.reconstruido = False
        self.fragmentos: list[Fragmento] = []
        self._vectores: np.ndarray | None = None
        self._indice = None
        self._cargar_o_construir(forzar)

    # ------------------------------------------------------------- construcción

    def _archivos(self) -> list[Path]:
        return sorted(self.ruta_conocimiento.glob("*.md")) if self.ruta_conocimiento.exists() else []

    def huella(self) -> str:
        sha = hashlib.sha256()
        for archivo in self._archivos():
            sha.update(archivo.name.encode())
            sha.update(archivo.read_bytes())
        for parte in (type(self.llm).__name__, self.modelo_embeddings, self.prefijo_documento, self.motor, VERSION_INDICE):
            sha.update(b"\0" + parte.encode())
        return sha.hexdigest()

    def _cargar_o_construir(self, forzar: bool) -> None:
        huella = self.huella()
        if not forzar and self._cargar(huella):
            return
        self._construir()
        self._guardar(huella)
        self.reconstruido = True

    def _construir(self) -> None:
        self.fragmentos = [
            f for archivo in self._archivos() for f in fragmentar(archivo.read_text(encoding="utf-8"), archivo.name)
        ]
        if not self.fragmentos:
            self._vectores = np.zeros((0, 0), dtype="float32")
            return
        textos = [f"{self.prefijo_documento}{f.seccion}\n{f.texto}" for f in self.fragmentos]
        vectores: list[list[float]] = []
        for inicio in range(0, len(textos), TAM_LOTE):
            vectores.extend(self.llm.embeber(textos[inicio : inicio + TAM_LOTE]))  # puede lanzar ErrorLLM
        self._vectores = _normalizar(np.array(vectores, dtype="float32"))
        if self.motor == "faiss":
            self._indice = faiss.IndexFlatIP(self._vectores.shape[1])
            self._indice.add(self._vectores)

    def _guardar(self, huella: str) -> None:
        self.ruta_indice.mkdir(parents=True, exist_ok=True)
        (self.ruta_indice / "fragmentos.json").write_text(
            json.dumps([f.model_dump(exclude={"puntaje"}) for f in self.fragmentos], ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        if self._indice is not None:
            # serialize_index + escritura desde Python: write_index falla con rutas no ASCII en Windows
            (self.ruta_indice / "indice.faiss").write_bytes(faiss.serialize_index(self._indice).tobytes())
        else:
            with open(self.ruta_indice / "vectores.npy", "wb") as archivo:
                np.save(archivo, self._vectores)
        (self.ruta_indice / "huella.txt").write_text(huella, encoding="utf-8")

    def _cargar(self, huella: str) -> bool:
        """Carga el índice guardado si su huella coincide. Devuelve False si hay que reconstruir."""
        try:
            if (self.ruta_indice / "huella.txt").read_text(encoding="utf-8").strip() != huella:
                return False
            datos = json.loads((self.ruta_indice / "fragmentos.json").read_text(encoding="utf-8"))
            self.fragmentos = [Fragmento(**d) for d in datos]
            if self.motor == "faiss":
                crudo = np.frombuffer((self.ruta_indice / "indice.faiss").read_bytes(), dtype="uint8")
                self._indice = faiss.deserialize_index(crudo)
                return self._indice.ntotal == len(self.fragmentos)
            with open(self.ruta_indice / "vectores.npy", "rb") as archivo:
                self._vectores = np.load(archivo)
            return len(self._vectores) == len(self.fragmentos)
        except (OSError, ValueError, RuntimeError, TypeError, KeyError):
            return False

    # ---------------------------------------------------------------- búsqueda

    def buscar(self, consulta: str, k: int = 4) -> list[Fragmento]:
        k = min(k, len(self.fragmentos))
        if k <= 0 or not consulta.strip():
            return []
        vector = _normalizar(np.array(self.llm.embeber([f"{self.prefijo_consulta}{consulta}"]), dtype="float32"))
        if self._indice is not None:
            puntajes, indices = self._indice.search(vector, k)
            pares = zip(indices[0].tolist(), puntajes[0].tolist())
        else:
            similitudes = self._vectores @ vector[0]
            orden = np.argsort(-similitudes)[:k]
            pares = ((int(i), float(similitudes[i])) for i in orden)
        return [
            self.fragmentos[i].model_copy(update={"puntaje": round(p, 4)}) for i, p in pares if i >= 0
        ]

    def disponible(self) -> bool:
        return bool(self.fragmentos)

    @classmethod
    def desde_config(cls, config: "Configuracion", llm: ClienteLLM, forzar: bool = False) -> "BaseConocimientoVectorial":
        prefijos = PREFIJOS_NOMIC if "nomic" in config.modelo_embeddings else ("", "")
        return cls(config.ruta_conocimiento, config.ruta_indice, llm, config.modelo_embeddings, prefijos, forzar)


def crear_base_conocimiento(config: "Configuracion", llm: ClienteLLM) -> BaseConocimiento:
    """Fábrica que usa el contenedor. Si no hay embeddings (Ollama apagado), regresa una base vacía."""
    try:
        return BaseConocimientoVectorial.desde_config(config, llm)
    except ErrorLLM as e:
        print(f"[RAG] Advertencia: no se pudo construir la base de conocimiento ({e}). Sigo sin RAG.")
        return BaseConocimientoVacia()
