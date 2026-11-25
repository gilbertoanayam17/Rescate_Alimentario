"""Capa de servicios: lo único que usa la interfaz.

`ServicioDonativos` hacía todo (participantes, publicación, asignación y entregas). Siguiendo el
principio de responsabilidad única se dividió en tres servicios de operación
(`ServicioParticipantes`, `ServicioPublicacion`, `ServicioDistribucion`) y servicios aparte para
consultas, avisos, casos y pronósticos. Todos reciben el `Actor` y lo validan contra la base.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .casos import ServicioCasos
from .distribucion import ServicioDistribucion
from .errores import ErrorAutorizacion, ErrorServicio
from .notificaciones import ServicioNotificaciones
from .participantes import ServicioParticipantes
from .prediccion import ServicioPrediccion
from .publicacion import ResultadoPublicacion, ServicioPublicacion
from .reportes import ServicioReportes


@dataclass(frozen=True)
class Servicios:
    """Agrupa los servicios que recibe la interfaz. No tiene lógica propia."""

    participantes: ServicioParticipantes
    publicacion: ServicioPublicacion
    distribucion: ServicioDistribucion
    reportes: ServicioReportes
    notificaciones: ServicioNotificaciones
    casos: ServicioCasos
    prediccion: ServicioPrediccion
    estado_llm: Callable[[], str]
    #: Contacto de la coordinación que ve quien todavía no tiene cuenta o PIN.
    correo_coordinacion: str = ""
    telefono_coordinacion: str = ""


__all__ = [
    "ErrorAutorizacion",
    "ErrorServicio",
    "ResultadoPublicacion",
    "ServicioCasos",
    "ServicioDistribucion",
    "ServicioNotificaciones",
    "ServicioParticipantes",
    "ServicioPrediccion",
    "ServicioPublicacion",
    "ServicioReportes",
    "Servicios",
]
