"""CAR-05 Ciclo de vida del donativo, con el patrón State.

Cada clase de estado sabe a qué estados puede pasar y con qué evento.
El donativo (contexto) delega en su estado actual para decidir la transición.

    PUBLICADO --evaluar_apto--> EVALUADO --asignar--> ASIGNADO --iniciar_recoleccion--> EN_RECOLECCION --entregar--> ENTREGADO
        |                           ^                     |
        +--evaluar_no_apto--> RECHAZADO                    +--liberar (receptor rechaza)--+
    Desde los estados no finales también se puede cancelar; EVALUADO y ASIGNADO pueden expirar.

Archivo COMPARTIDO (fase 0).
"""
from __future__ import annotations

from .enums import EstadoDonativo, Evento
from .modelos import Donativo, ahora


class TransicionInvalida(Exception):
    """Se intentó un evento que el estado actual no permite."""


class EstadoBase:
    nombre: EstadoDonativo
    transiciones: dict[Evento, EstadoDonativo] = {}

    def siguiente(self, evento: Evento) -> EstadoDonativo:
        if evento not in self.transiciones:
            raise TransicionInvalida(
                f"No se puede '{evento.value}' un donativo en estado '{self.nombre.value}'."
            )
        return self.transiciones[evento]

    def eventos_permitidos(self) -> list[Evento]:
        return list(self.transiciones)

    @property
    def es_final(self) -> bool:
        return not self.transiciones


class Publicado(EstadoBase):
    nombre = EstadoDonativo.PUBLICADO
    transiciones = {
        Evento.EVALUAR_APTO: EstadoDonativo.EVALUADO,
        Evento.EVALUAR_NO_APTO: EstadoDonativo.RECHAZADO,
        Evento.CANCELAR: EstadoDonativo.CANCELADO,
    }


class Evaluado(EstadoBase):
    nombre = EstadoDonativo.EVALUADO
    transiciones = {
        Evento.ASIGNAR: EstadoDonativo.ASIGNADO,
        Evento.EXPIRAR: EstadoDonativo.EXPIRADO,
        Evento.CANCELAR: EstadoDonativo.CANCELADO,
    }


class Asignado(EstadoBase):
    nombre = EstadoDonativo.ASIGNADO
    transiciones = {
        Evento.INICIAR_RECOLECCION: EstadoDonativo.EN_RECOLECCION,
        Evento.LIBERAR: EstadoDonativo.EVALUADO,
        Evento.EXPIRAR: EstadoDonativo.EXPIRADO,
        Evento.CANCELAR: EstadoDonativo.CANCELADO,
    }


class EnRecoleccion(EstadoBase):
    nombre = EstadoDonativo.EN_RECOLECCION
    transiciones = {
        Evento.ENTREGAR: EstadoDonativo.ENTREGADO,
        Evento.CANCELAR: EstadoDonativo.CANCELADO,
    }


class Entregado(EstadoBase):
    nombre = EstadoDonativo.ENTREGADO


class Rechazado(EstadoBase):
    nombre = EstadoDonativo.RECHAZADO


class Expirado(EstadoBase):
    nombre = EstadoDonativo.EXPIRADO


class Cancelado(EstadoBase):
    nombre = EstadoDonativo.CANCELADO


ESTADOS: dict[EstadoDonativo, EstadoBase] = {
    e.nombre: e
    for e in (
        Publicado(),
        Evaluado(),
        Asignado(),
        EnRecoleccion(),
        Entregado(),
        Rechazado(),
        Expirado(),
        Cancelado(),
    )
}


def estado_de(donativo: Donativo) -> EstadoBase:
    return ESTADOS[donativo.estado]


def aplicar_evento(donativo: Donativo, evento: Evento) -> tuple[EstadoDonativo, EstadoDonativo]:
    """Mueve el donativo al siguiente estado. Devuelve (anterior, nuevo).

    Lanza TransicionInvalida si el evento no está permitido en el estado actual.
    """
    anterior = donativo.estado
    nuevo = estado_de(donativo).siguiente(evento)
    donativo.estado = nuevo
    donativo.actualizado = ahora()
    return anterior, nuevo
