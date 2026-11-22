"""Pronósticos de excedentes (CAR-07). Dueño: Gilberto (tarea G3); por ahora, versión mínima."""
from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime

from rescate.agentes.predictor import AgentePredictor
from rescate.dominio.enums import EstadoPronostico, Rol
from rescate.dominio.modelos import Actor, Pronostico, ahora
from rescate.persistencia.repositorios import (
    RepositorioDonativos,
    RepositorioParticipantes,
    RepositorioPronosticos,
)

from .autorizacion import exigir_rol, participante_del_actor
from .errores import ErrorServicio
from .notificaciones import CanalAvisos


class ServicioPrediccion:
    def __init__(
        self,
        agente: AgentePredictor,
        participantes: RepositorioParticipantes,
        donativos: RepositorioDonativos,
        pronosticos: RepositorioPronosticos,
        canal: CanalAvisos,
        reloj: Callable[[], datetime] = ahora,
    ) -> None:
        self._agente = agente
        self._participantes = participantes
        self._donativos = donativos
        self._pronosticos = pronosticos
        self._canal = canal
        self._reloj = reloj

    def pronosticos_para_donante(self, actor: Actor | None, fecha: date | None = None) -> list[Pronostico]:
        participante_del_actor(actor, Rol.DONANTE, self._participantes)
        return []

    def pronosticos_para_receptor(self, actor: Actor | None, desde: date | None = None) -> list[Pronostico]:
        participante_del_actor(actor, Rol.RECEPTOR, self._participantes)
        return []

    def generar(self, actor: Actor | None, fecha: date) -> list[Pronostico]:
        exigir_rol(actor, Rol.COORDINADOR)
        return []

    def marcar(self, actor: Actor | None, pronostico_id: str, estado: EstadoPronostico) -> Pronostico:
        participante_del_actor(actor, Rol.DONANTE, self._participantes)
        raise ErrorServicio(f"No existe el pronóstico {pronostico_id}.")
