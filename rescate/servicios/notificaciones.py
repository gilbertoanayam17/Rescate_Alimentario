"""Avisos a los participantes (CAR-06): canal (Strategy), notificador (Observer) y consulta."""
from __future__ import annotations

from abc import ABC, abstractmethod

from rescate.dominio.enums import Rol
from rescate.dominio.modelos import Actor, Aviso, EventoDonativo
from rescate.persistencia.repositorios import (
    RepositorioAvisos,
    RepositorioDonativos,
    RepositorioParticipantes,
)

from .autorizacion import es_coordinador, participante_del_actor
from .errores import ErrorAutorizacion
from .eventos import ObservadorEventos


class CanalAvisos(ABC):
    """Strategy del canal: hoy dentro de la app; WhatsApp o correo serían otra clase."""

    @abstractmethod
    def enviar(self, aviso: Aviso) -> None: ...


class AvisosEnApp(CanalAvisos):
    def __init__(self, avisos: RepositorioAvisos) -> None:
        self._avisos = avisos

    def enviar(self, aviso: Aviso) -> None:
        self._avisos.agregar(aviso)


class NotificadorEstados(ObservadorEventos):
    """Observer del ciclo de vida: arma los avisos de cada cambio de estado (tarea A1)."""

    def __init__(
        self, canal: CanalAvisos, participantes: RepositorioParticipantes, donativos: RepositorioDonativos
    ) -> None:
        self._canal = canal
        self._participantes = participantes
        self._donativos = donativos

    def al_ocurrir(self, evento: EventoDonativo) -> None:
        """Los mensajes por evento los escribe la tarea A1."""


class ServicioNotificaciones:
    def __init__(self, avisos: RepositorioAvisos, participantes: RepositorioParticipantes) -> None:
        self._avisos = avisos
        self._participantes = participantes

    def _destino(self, actor: Actor | None) -> tuple[Rol, str | None]:
        if es_coordinador(actor):
            return Rol.COORDINADOR, None
        if actor is None:
            raise ErrorAutorizacion("Inicia sesión para ver tus avisos.")
        participante = participante_del_actor(actor, actor.rol, self._participantes)
        return participante.rol, participante.id

    def avisos(self, actor: Actor | None, solo_no_leidos: bool = False) -> list[Aviso]:
        rol, destinatario = self._destino(actor)
        return self._avisos.de_destinatario(rol, destinatario, solo_no_leidos)

    def no_leidos(self, actor: Actor | None) -> int:
        return len(self.avisos(actor, solo_no_leidos=True))

    def marcar_leido(self, actor: Actor | None, aviso_id: str) -> None:
        rol, destinatario = self._destino(actor)
        if not self._avisos.marcar_leido(aviso_id, rol, destinatario):
            raise ErrorAutorizacion("Ese aviso no es tuyo.")
