"""Base de conocimiento para el RAG del Agente de Inocuidad.

DUEÑO: Gilberto (flujo 1).
FASE 0: solo define la interfaz y una base vacía. La tarea G2 agrega la implementación con
FAISS + nomic-embed-text y cambia `crear_base_conocimiento` para devolverla.
El contenedor siempre llama a `crear_base_conocimiento`; no cambies su firma.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from pydantic import BaseModel

from rescate.llm.cliente import ClienteLLM

if TYPE_CHECKING:
    from rescate.config import Configuracion


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


def crear_base_conocimiento(config: "Configuracion", llm: ClienteLLM) -> BaseConocimiento:
    """Fábrica que usa el contenedor. FASE 0: base vacía."""
    return BaseConocimientoVacia()
