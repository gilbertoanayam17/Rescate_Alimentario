"""Patrón Mediator: coordina a los agentes, al coordinador y a los participantes (CAR-10).

Los agentes y servicios no se llaman entre sí para escalar un caso: le avisan al mediador, que
decide qué hacer. El mediador:

- abre el caso sin duplicarlo (mismo tipo y donativo) y avisa a la coordinación;
- escucha el bus de eventos (Observer) para cerrar solo los casos que ya no aplican: con
  `asignar` resuelve el SIN_RECEPTOR del donativo; con `cancelar` o `expirar`, los abiertos del
  donativo; y con el segundo `liberar` del mismo donativo abre RECHAZOS_REPETIDOS.
"""
from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from rescate.dominio.enums import EstadoCaso, Evento, Rol, TipoCaso
from rescate.dominio.modelos import Aviso, CasoEscalado, EventoDonativo, ahora
from rescate.persistencia.repositorios import RepositorioCasos

if TYPE_CHECKING:
    from rescate.servicios.eventos import BusEventos
    from rescate.servicios.notificaciones import CanalAvisos

#: Cómo se nombra cada tipo de caso en los avisos y en la bandeja.
TITULO_CASO = {
    TipoCaso.SIN_RECEPTOR: "Sin receptor",
    TipoCaso.POSIBLE_INYECCION: "Posible manipulación del agente",
    TipoCaso.INTERPRETACION_CORREGIDA: "Interpretación corregida",
    TipoCaso.INOCUIDAD_DUDOSA: "Inocuidad dudosa",
    TipoCaso.RECOLECCION_VENCIDA: "Recolección vencida",
    TipoCaso.RECHAZOS_REPETIDOS: "Rechazos repetidos",
}

#: Desde el segundo rechazo de un mismo donativo se avisa a la coordinación.
RECHAZOS_PARA_ESCALAR = 2


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
        self._candado = threading.Lock()
        self._liberaciones: Counter[str] = Counter()  # rechazos por donativo en esta sesión
        bus.suscribir(self)

    def notificar(self, emisor: str, tipo: TipoCaso, donativo_id: str | None, motivo: str) -> CasoEscalado | None:
        """Abre un caso y avisa a la coordinación, salvo que ya haya uno abierto igual."""
        with self._candado:
            if self._casos.abierto_de(tipo, donativo_id) is not None:
                return None
            caso = CasoEscalado(
                tipo=tipo, donativo_id=donativo_id, motivo=motivo, emisor=emisor, creado=self._reloj()
            )
            self._casos.guardar(caso)
        self._canal.enviar(
            Aviso(
                rol=Rol.COORDINADOR,
                donativo_id=donativo_id,
                titulo=f"Caso: {TITULO_CASO[tipo]}",
                mensaje=f"{emisor}: {motivo}",
            )
        )
        return caso

    # ---------------------------------------------------------- Observer del bus

    def al_ocurrir(self, evento: EventoDonativo) -> None:
        if evento.evento == Evento.ASIGNAR.value:
            self._resolver(evento.donativo_id, f"Resuelto: se asignó un receptor. {evento.motivo}".strip(),
                           {TipoCaso.SIN_RECEPTOR})
        elif evento.evento in (Evento.CANCELAR.value, Evento.EXPIRAR.value):
            nota = "Resuelto: el donativo se canceló" if evento.evento == Evento.CANCELAR.value else (
                "Resuelto: el donativo venció"
            )
            self._resolver(evento.donativo_id, nota)
        elif evento.evento == Evento.LIBERAR.value:
            self._liberaciones[evento.donativo_id] += 1
            if self._liberaciones[evento.donativo_id] >= RECHAZOS_PARA_ESCALAR:
                self.notificar(
                    "Distribución",
                    TipoCaso.RECHAZOS_REPETIDOS,
                    evento.donativo_id,
                    f"{self._liberaciones[evento.donativo_id]} receptores lo rechazaron. "
                    f"Último motivo: {evento.motivo}",
                )

    def _resolver(self, donativo_id: str, nota: str, tipos: set[TipoCaso] | None = None) -> None:
        with self._candado:
            for caso in self._casos.de_donativo(donativo_id):
                if caso.estado == EstadoCaso.ABIERTO and (tipos is None or caso.tipo in tipos):
                    caso.estado = EstadoCaso.RESUELTO
                    caso.resolucion = nota
                    caso.resuelto = self._reloj()
                    self._casos.guardar(caso)
