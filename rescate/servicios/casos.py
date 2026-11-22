"""Bandeja de casos escalados al coordinador (CAR-10)."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from rescate.dominio.enums import EstadoCaso, Rol
from rescate.dominio.modelos import Actor, CasoEscalado, ahora
from rescate.persistencia.repositorios import RepositorioCasos

from .autorizacion import exigir_rol
from .errores import ErrorServicio


class ServicioCasos:
    def __init__(self, casos: RepositorioCasos, reloj: Callable[[], datetime] = ahora) -> None:
        self._casos = casos
        self._reloj = reloj

    def abiertos(self, actor: Actor | None) -> list[CasoEscalado]:
        exigir_rol(actor, Rol.COORDINADOR)
        return self._casos.abiertos()

    def resolver(self, actor: Actor | None, caso_id: str, nota: str) -> CasoEscalado:
        exigir_rol(actor, Rol.COORDINADOR)
        caso = self._casos.obtener(caso_id)
        if caso is None:
            raise ErrorServicio(f"No existe el caso {caso_id}.")
        caso.estado = EstadoCaso.RESUELTO
        caso.resolucion = nota.strip() or "Resuelto por el coordinador"
        caso.resuelto = self._reloj()
        self._casos.guardar(caso)
        return caso
