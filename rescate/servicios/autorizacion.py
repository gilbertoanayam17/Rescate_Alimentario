"""Autorización dentro de los servicios (observación del profesor a la segunda entrega).

La interfaz solo dice QUIÉN pide la operación (un `Actor`); el servicio verifica en la base que
ese participante exista y tenga el rol que la operación exige. Nunca se confía en un id o en un
rol que venga de la barra lateral.
"""
from __future__ import annotations

from rescate.dominio.enums import Rol
from rescate.dominio.modelos import Actor, Participante
from rescate.persistencia.repositorios import RepositorioParticipantes

from .errores import ErrorAutorizacion


def exigir_rol(actor: Actor | None, *roles: Rol) -> Actor:
    """Regresa el actor si su rol está entre `roles`; si no, ErrorAutorizacion."""
    if actor is None or actor.rol not in roles:
        raise ErrorAutorizacion("No tienes permiso para esta operación.")
    return actor


def es_coordinador(actor: Actor | None) -> bool:
    return actor is not None and actor.rol == Rol.COORDINADOR


def participante_del_actor(actor: Actor | None, rol: Rol, participantes: RepositorioParticipantes) -> Participante:
    """Busca al participante del actor EN LA BASE y verifica que su rol guardado sea `rol`."""
    exigir_rol(actor, rol)
    participante = participantes.obtener(actor.participante_id) if actor.participante_id else None
    if participante is None or participante.rol != rol:
        raise ErrorAutorizacion(f"Tu sesión no corresponde a un {rol.value} registrado.")
    return participante
