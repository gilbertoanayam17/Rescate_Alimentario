"""Interfaz común de los agentes.

Todos los agentes:
- reciben un ClienteLLM (abstracción, no Ollama) y la Bitácora por constructor;
- exponen `ejecutar(entrada) -> salida` con tipos del dominio;
- anotan su razonamiento en la bitácora (CAR-11);
- tienen un camino de respaldo determinista si el LLM falla (sección 7 de la visión).

Archivo COMPARTIDO (fase 0).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from rescate.bitacora import Bitacora
from rescate.dominio.enums import TipoEntradaBitacora
from rescate.llm.cliente import ClienteLLM

E = TypeVar("E")
S = TypeVar("S")


class Agente(ABC, Generic[E, S]):
    nombre: str = "Agente"

    def __init__(self, llm: ClienteLLM, bitacora: Bitacora) -> None:
        self.llm = llm
        self.bitacora = bitacora

    @abstractmethod
    def ejecutar(self, entrada: E) -> S: ...

    def _anotar(
        self,
        tipo: TipoEntradaBitacora,
        contenido: str,
        donativo_id: str | None = None,
        paso: int = 0,
        datos: dict | None = None,
    ) -> None:
        self.bitacora.registrar(self.nombre, tipo, contenido, donativo_id, paso, datos)
