"""Patrón Observer: el ciclo de vida publica eventos y los observadores reaccionan.

Así las notificaciones (CAR-06) y el mediador de casos (CAR-10) se enteran de cada cambio sin
que los servicios los llamen directamente.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from rescate.dominio.modelos import EventoDonativo

registro = logging.getLogger(__name__)


class ObservadorEventos(ABC):
    @abstractmethod
    def al_ocurrir(self, evento: EventoDonativo) -> None: ...


class BusEventos:
    def __init__(self) -> None:
        self._observadores: list[ObservadorEventos] = []

    def suscribir(self, observador: ObservadorEventos) -> None:
        self._observadores.append(observador)

    def publicar(self, evento: EventoDonativo) -> None:
        """Avisa a todos. Un observador que falla no rompe la operación que publicó el evento."""
        for observador in self._observadores:
            try:
                observador.al_ocurrir(evento)
            except Exception:  # noqa: BLE001 - un aviso fallido no debe deshacer una entrega
                registro.exception("Falló el observador %s con %s", type(observador).__name__, evento)
