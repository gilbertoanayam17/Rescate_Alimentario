"""Patrón Mediator: coordina a los agentes, al coordinador y a los participantes (CAR-10).

Los servicios no se llaman entre sí para escalar un caso: le avisan al mediador, que decide qué
hacer. En esta versión solo guarda el caso sin duplicarlo; la tarea A2 agrega los avisos a la
coordinación y la resolución automática con el bus de eventos.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from rescate.dominio.enums import TipoCaso
from rescate.dominio.modelos import CasoEscalado, ahora
from rescate.persistencia.repositorios import RepositorioCasos

if TYPE_CHECKING:
    from rescate.servicios.eventos import BusEventos
    from rescate.servicios.notificaciones import CanalAvisos


class MediadorCasos:
    def __init__(
        self,
        casos: RepositorioCasos,
        canal: CanalAvisos,
        bus: BusEventos,
        reloj: Callable[[], datetime] = ahora,
    ) -> None:
        self._casos = casos
        self._canal = canal
        self._bus = bus
        self._reloj = reloj

    def notificar(self, emisor: str, tipo: TipoCaso, donativo_id: str | None, motivo: str) -> CasoEscalado | None:
        """Abre un caso, salvo que ya haya uno abierto del mismo tipo para ese donativo."""
        if self._casos.abierto_de(tipo, donativo_id) is not None:
            return None
        caso = CasoEscalado(tipo=tipo, donativo_id=donativo_id, motivo=motivo, emisor=emisor, creado=self._reloj())
        self._casos.guardar(caso)
        return caso
