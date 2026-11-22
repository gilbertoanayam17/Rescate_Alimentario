"""Agente Logístico (CAR-04): agrupa donativos cercanos en una ruta para el recolector.

Versión mínima de la fase F0. La tarea A5 agrega las estrategias de ruta (Strategy), la elección
del LLM con validación y su respaldo determinista.
"""
from __future__ import annotations

from pydantic import BaseModel

from rescate.agentes.base import Agente
from rescate.dominio.modelos import Donativo, Recolector


class SolicitudRuta(BaseModel):
    recolector: Recolector
    tomados: list[Donativo] = []  # los que ya lleva
    disponibles: list[Donativo] = []  # aceptados, sin recolector


class AgenteLogistico(Agente[SolicitudRuta, object]):
    nombre = "Logístico"

    def ejecutar(self, entrada: SolicitudRuta) -> None:
        return None
