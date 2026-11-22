"""Avisos a los participantes (CAR-06): canal (Strategy), notificador (Observer) y consulta."""
from __future__ import annotations

from abc import ABC, abstractmethod

from rescate.dominio.enums import Evento, Rol
from rescate.dominio.modelos import Actor, Aviso, Donativo, EventoDonativo
from rescate.persistencia.repositorios import (
    RepositorioAvisos,
    RepositorioDonativos,
    RepositorioParticipantes,
)

from .autorizacion import es_coordinador, participante_del_actor
from .errores import ErrorAutorizacion
from .eventos import ObservadorEventos

#: (rol del destinatario, id del destinatario, título, mensaje)
_Destino = tuple[Rol, str | None, str, str]


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
    """Observer del ciclo de vida: arma los avisos de cada cambio de estado (CAR-06).

    No sabe por dónde viajan los avisos: los manda al `CanalAvisos` que le inyecta el
    contenedor. Hoy es `AvisosEnApp`; WhatsApp o correo serían otra clase de canal, sin
    tocar este notificador.
    """

    def __init__(
        self, canal: CanalAvisos, participantes: RepositorioParticipantes, donativos: RepositorioDonativos
    ) -> None:
        self._canal = canal
        self._participantes = participantes
        self._donativos = donativos

    def al_ocurrir(self, evento: EventoDonativo) -> None:
        donativo = self._donativos.obtener(evento.donativo_id)
        if donativo is None:
            return
        armar = {
            Evento.EVALUAR_NO_APTO.value: self._no_apto,
            Evento.ASIGNAR.value: self._asignado,
            Evento.LIBERAR.value: self._liberado,
            "aceptar": self._aceptado,
            Evento.INICIAR_RECOLECCION.value: self._en_camino,
            Evento.ENTREGAR.value: self._entregado,
            Evento.CANCELAR.value: self._cancelado,
            Evento.EXPIRAR.value: self._expirado,
        }.get(evento.evento)
        if armar is None:
            return
        for rol, destinatario_id, titulo, mensaje in armar(donativo, evento):
            self._canal.enviar(
                Aviso(
                    rol=rol,
                    destinatario_id=destinatario_id,
                    donativo_id=donativo.id,
                    titulo=titulo,
                    mensaje=mensaje,
                )
            )

    # ------------------------------------------------------------ un evento cada uno

    def _no_apto(self, d: Donativo, e: EventoDonativo) -> list[_Destino]:
        return [(Rol.DONANTE, d.donante_id, "No apto", f"Tu donativo no se puede donar: {e.motivo}")]

    def _asignado(self, d: Donativo, e: EventoDonativo) -> list[_Destino]:
        if not d.receptor_id:
            return []
        return [
            (Rol.RECEPTOR, d.receptor_id, "Nuevo donativo", f"Nuevo donativo por confirmar: {d.resumen()}"),
            (Rol.DONANTE, d.donante_id, "Asignado", f"Tu donativo se asignó a {self._nombre(d.receptor_id)}"),
        ]

    def _liberado(self, d: Donativo, e: EventoDonativo) -> list[_Destino]:
        quien = d.receptores_descartados[-1] if d.receptores_descartados else None
        receptor = self._nombre(quien) if quien else "El receptor"
        return [
            (
                Rol.DONANTE,
                d.donante_id,
                "Buscamos otro receptor",
                f"{receptor} no pudo recibirlo ({e.motivo}); buscamos otro receptor",
            )
        ]

    def _aceptado(self, d: Donativo, e: EventoDonativo) -> list[_Destino]:
        donante = self._participantes.obtener(d.donante_id)
        lugar = (donante.ubicacion.direccion or donante.nombre) if donante else "el comercio"
        avisos: list[_Destino] = [
            (Rol.DONANTE, d.donante_id, "Aceptado", f"{self._nombre(d.receptor_id)} aceptó tu donativo")
        ]
        avisos += [
            (Rol.RECOLECTOR, r.id, "Listo para recoger", f"Hay un donativo listo para recoger en {lugar}")
            for r in self._participantes.recolectores()
            if r.disponible
        ]
        return avisos

    def _en_camino(self, d: Donativo, e: EventoDonativo) -> list[_Destino]:
        mensaje = f"{self._nombre(d.recolector_id)} va en camino"
        return self._donante_y_receptor(d, "En camino", mensaje)

    def _entregado(self, d: Donativo, e: EventoDonativo) -> list[_Destino]:
        return self._donante_y_receptor(d, "Entregado", "Entregado. Ya puedes descargar la constancia.")

    def _cancelado(self, d: Donativo, e: EventoDonativo) -> list[_Destino]:
        return self._involucrados(d, e, "Cancelado", "El donativo se canceló")

    def _expirado(self, d: Donativo, e: EventoDonativo) -> list[_Destino]:
        return self._involucrados(d, e, "Vencido", "El donativo venció sin recogerse")

    # ------------------------------------------------------------------ internos

    def _nombre(self, participante_id: str | None) -> str:
        participante = self._participantes.obtener(participante_id) if participante_id else None
        return participante.nombre if participante else "Alguien"

    def _donante_y_receptor(self, d: Donativo, titulo: str, mensaje: str) -> list[_Destino]:
        avisos: list[_Destino] = [(Rol.DONANTE, d.donante_id, titulo, mensaje)]
        if d.receptor_id:
            avisos.append((Rol.RECEPTOR, d.receptor_id, titulo, mensaje))
        return avisos

    def _involucrados(self, d: Donativo, e: EventoDonativo, titulo: str, mensaje: str) -> list[_Destino]:
        """Donante, receptor y recolector, salvo quien hizo la operación."""
        quien = e.actor.participante_id if e.actor else None
        candidatos = [
            (Rol.DONANTE, d.donante_id),
            (Rol.RECEPTOR, d.receptor_id),
            (Rol.RECOLECTOR, d.recolector_id),
        ]
        return [(rol, pid, titulo, mensaje) for rol, pid in candidatos if pid and pid != quien]


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
