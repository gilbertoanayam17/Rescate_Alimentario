"""ClienteLLM falso para pruebas y para correr la app sin Ollama (USAR_LLM_FALSO=1).

- generar_json devuelve respuestas programadas por nombre de esquema; si no hay, lanza
  ErrorLLM, con lo que los agentes usan su camino de respaldo determinista.
- embeber devuelve vectores deterministas por palabras (sirven para probar el RAG).

Archivo COMPARTIDO (fase 0).
"""
from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Callable

from .cliente import ClienteLLM, ErrorLLM, T

DIMENSION_FALSA = 256


class ClienteLLMFalso(ClienteLLM):
    nombre_modelo = "llm-falso"

    def __init__(
        self,
        respuestas: dict[str, list[dict[str, Any]]] | None = None,
        por_defecto: Callable[[str, type], dict[str, Any]] | None = None,
    ) -> None:
        # respuestas: {"NombreDelEsquema": [respuesta1, respuesta2, ...]} se consumen en orden
        self.respuestas = {k: list(v) for k, v in (respuestas or {}).items()}
        self.por_defecto = por_defecto
        self.llamadas: list[tuple[str, str]] = []  # (nombre del esquema, prompt)

    def programar(self, esquema: str, *respuestas: dict[str, Any]) -> None:
        self.respuestas.setdefault(esquema, []).extend(respuestas)

    def generar_json(self, prompt: str, esquema: type[T], sistema: str | None = None, temperatura: float = 0.2) -> T:
        self.llamadas.append((esquema.__name__, prompt))
        cola = self.respuestas.get(esquema.__name__)
        if cola:
            return esquema.model_validate(cola.pop(0))
        if self.por_defecto:
            return esquema.model_validate(self.por_defecto(prompt, esquema))
        raise ErrorLLM(f"LLM falso: sin respuesta programada para {esquema.__name__}")

    def embeber(self, textos: list[str]) -> list[list[float]]:
        return [_vector_por_palabras(t) for t in textos]

    def disponible(self) -> bool:
        return False  # para que la interfaz avise que no hay LLM real


def _vector_por_palabras(texto: str) -> list[float]:
    vector = [0.0] * DIMENSION_FALSA
    for palabra in re.findall(r"\w+", texto.lower()):
        indice = int(hashlib.md5(palabra.encode()).hexdigest(), 16) % DIMENSION_FALSA
        vector[indice] += 1.0
    norma = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [x / norma for x in vector]
