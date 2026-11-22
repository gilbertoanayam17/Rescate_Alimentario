"""Aplica el ciclo de vida (patrón State), guarda el historial y publica eventos.

Lo comparten ServicioPublicacion y ServicioDistribucion para no duplicar la lógica de las
transiciones.
"""
from __future__ import annotations

from rescate.dominio.enums import EstadoDonativo, Evento
from rescate.dominio.estados import TransicionInvalida, aplicar_evento
from rescate.dominio.modelos import Actor, Asignacion, Donativo, EventoDonativo
from rescate.persistencia.repositorios import RepositorioDonativos

from .errores import ErrorServicio
from .eventos import BusEventos


class CicloDeVida:
    def __init__(self, donativos: RepositorioDonativos, bus: BusEventos) -> None:
        self._donativos = donativos
        self._bus = bus

    def _registrar(
        self,
        donativo: Donativo,
        anterior: EstadoDonativo | None,
        evento: str,
        motivo: str,
        actor: Actor | None,
    ) -> None:
        self._donativos.registrar_transicion(donativo.id, anterior, donativo.estado, evento, motivo)
        self._bus.publicar(
            EventoDonativo(
                donativo_id=donativo.id,
                evento=evento,
                anterior=anterior,
                nuevo=donativo.estado,
                motivo=motivo,
                actor=actor,
            )
        )

    def registrar_publicacion(self, donativo: Donativo, actor: Actor | None = None) -> None:
        self._donativos.guardar(donativo)
        self._registrar(donativo, None, "publicar", "Publicado por el donante", actor)

    def transicionar(
        self, donativo: Donativo, evento: Evento, motivo: str = "", actor: Actor | None = None
    ) -> None:
        try:
            anterior, _ = aplicar_evento(donativo, evento)
        except TransicionInvalida as e:
            raise ErrorServicio(str(e)) from e
        self._donativos.guardar(donativo)
        self._registrar(donativo, anterior, evento.value, motivo, actor)

    def registrar_aceptacion(self, donativo: Donativo, actor: Actor) -> None:
        """Aceptar no cambia de estado: marca la asignación y deja constancia en el historial."""
        self._donativos.guardar(donativo)
        self._registrar(donativo, donativo.estado, "aceptar", "El receptor aceptó", actor)

    def registrar_tomado(self, donativo: Donativo, actor: Actor) -> None:
        """Historial y evento después de que el repositorio tomó el donativo de forma atómica."""
        self._registrar(
            donativo, EstadoDonativo.ASIGNADO, Evento.INICIAR_RECOLECCION.value, "Recolector en camino", actor
        )

    def aplicar_asignacion(self, donativo: Donativo, asignacion: Asignacion, actor: Actor | None = None) -> bool:
        """Guarda la asignación; si hay receptor, pasa a ASIGNADO. Regresa False si nadie es compatible."""
        donativo.asignacion = asignacion
        if asignacion.receptor_id:
            self.transicionar(donativo, Evento.ASIGNAR, asignacion.justificacion, actor)
            return True
        self._donativos.guardar(donativo)  # queda EVALUADO para el coordinador
        return False
