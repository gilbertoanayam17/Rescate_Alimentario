"""Agente Predictor (CAR-07): detecta patrones de excedentes y avisa al donante.

Versión mínima de la fase F0. La tarea G3 agrega la detección de patrones, la decisión del LLM
con validación y la plantilla de respaldo.
"""
from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from rescate.agentes.base import Agente
from rescate.dominio.modelos import Donante, Pronostico


class SolicitudPronostico(BaseModel):
    donante: Donante
    fecha: date
    patrones: list[dict] = []


class AgentePredictor(Agente[SolicitudPronostico, list[Pronostico]]):
    nombre = "Predictor"

    def ejecutar(self, entrada: SolicitudPronostico) -> list[Pronostico]:
        return []
