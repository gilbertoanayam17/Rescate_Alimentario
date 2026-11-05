"""Implementación de ClienteLLM con Ollama local.

Archivo COMPARTIDO (fase 0).
"""
from __future__ import annotations

import ollama
from pydantic import ValidationError

from .cliente import ClienteLLM, ErrorLLM, T


class ClienteOllama(ClienteLLM):
    def __init__(
        self,
        modelo: str,
        modelo_embeddings: str = "nomic-embed-text",
        url: str = "http://localhost:11434",
        reintentos: int = 2,
    ) -> None:
        self.nombre_modelo = modelo
        self.modelo_embeddings = modelo_embeddings
        self.reintentos = reintentos
        self._cliente = ollama.Client(host=url)

    def generar_json(
        self,
        prompt: str,
        esquema: type[T],
        sistema: str | None = None,
        temperatura: float = 0.2,
    ) -> T:
        mensajes = []
        if sistema:
            mensajes.append({"role": "system", "content": sistema})
        mensajes.append({"role": "user", "content": prompt})

        ultimo_error: Exception | None = None
        for _ in range(self.reintentos + 1):  # 1 intento + hasta 2 reintentos (sección 7)
            try:
                respuesta = self._cliente.chat(
                    model=self.nombre_modelo,
                    messages=mensajes,
                    format=esquema.model_json_schema(),
                    think=False,
                    options={"temperature": temperatura},
                )
                return esquema.model_validate_json(respuesta["message"]["content"])
            except ValidationError as e:  # respondió, pero no cumplió el esquema
                ultimo_error = e
            except Exception as e:  # Ollama apagado, modelo no descargado, etc.
                ultimo_error = e
        raise ErrorLLM(f"{self.nombre_modelo} no produjo un {esquema.__name__} válido: {ultimo_error}")

    def embeber(self, textos: list[str]) -> list[list[float]]:
        try:
            respuesta = self._cliente.embed(model=self.modelo_embeddings, input=textos)
            return [list(v) for v in respuesta["embeddings"]]
        except Exception as e:
            raise ErrorLLM(f"No se pudieron calcular embeddings con {self.modelo_embeddings}: {e}") from e

    def disponible(self) -> bool:
        try:
            self._cliente.list()
            return True
        except Exception:
            return False
