"""Abstracción del LLM (inversión de dependencias).

Los agentes dependen de ClienteLLM, nunca de Ollama directamente. Así se cambia de
modelo (o se usa el cliente falso en pruebas) sin tocar la lógica de los agentes.

Archivo COMPARTIDO (fase 0).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class ErrorLLM(Exception):
    """El LLM no respondió o su respuesta no cumplió el esquema tras los reintentos."""


class ClienteLLM(ABC):
    nombre_modelo: str = "desconocido"

    @abstractmethod
    def generar_json(
        self,
        prompt: str,
        esquema: type[T],
        sistema: str | None = None,
        temperatura: float = 0.2,
    ) -> T:
        """Pide al LLM una respuesta que cumpla `esquema` (modelo Pydantic) y la valida.

        Lanza ErrorLLM si no lo logra. Quien llama debe tener un camino de respaldo.
        """

    @abstractmethod
    def embeber(self, textos: list[str]) -> list[list[float]]:
        """Devuelve un vector por texto (para el RAG)."""

    def disponible(self) -> bool:
        return True
