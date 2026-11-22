"""Rutas de recolección (CAR-04) con el patrón Strategy.

Herramienta determinista: el orden de las paradas, los kilómetros, las horas de llegada y si se
cumplen los límites los calcula este código. El Agente Logístico solo elige entre las rutas que
calculan las estrategias y explica la elección.

Cada estrategia decide el orden con una regla distinta; las dos respetan la precedencia: la
entrega de un donativo va después de su recolección (salvo que el recolector ya lo lleve).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from rescate.dominio.modelos import Ubicacion
from rescate.herramientas.geo import haversine_km

VELOCIDAD_KMH = {"a pie": 4, "bicicleta": 12, "moto": 25, "auto": 20}
CAPACIDAD_KG = {"a pie": 5, "bicicleta": 10, "moto": 15, "auto": 60}
#: Tiempo de carga o descarga en cada parada.
MINUTOS_POR_PARADA = 5
#: Transporte que se supone cuando el perfil trae uno desconocido (el más lento).
TRANSPORTE_POR_DEFECTO = "a pie"


@dataclass(frozen=True)
class Parada:
    tipo: Literal["recoger", "entregar"]
    donativo_id: str
    nombre: str
    ubicacion: Ubicacion
    limite: datetime | None = None  # hora máxima para llegar (las recolecciones)


@dataclass(frozen=True)
class RutaCalculada:
    estrategia: str
    paradas: list[Parada]
    km_por_tramo: list[float]
    llegadas: list[datetime]
    km_total: float
    minutos: float
    cumple_limites: bool
    retrasos: list[str]  # "Recoger en Fonda Doña Lupe: llega 19:10, límite 19:00"

    def orden(self) -> list[tuple[str, str]]:
        return [(p.tipo, p.donativo_id) for p in self.paradas]


def velocidad(transporte: str) -> float:
    return VELOCIDAD_KMH.get(transporte, VELOCIDAD_KMH[TRANSPORTE_POR_DEFECTO])


def capacidad(transporte: str) -> float:
    return CAPACIDAD_KG.get(transporte, CAPACIDAD_KG[TRANSPORTE_POR_DEFECTO])


def recorrer(
    estrategia: str, origen: Ubicacion, paradas: list[Parada], transporte: str, salida: datetime
) -> RutaCalculada:
    """Kilómetros, horas de llegada y retrasos de un orden de paradas ya decidido."""
    kmh = velocidad(transporte)
    tramos, llegadas, retrasos = [], [], []
    posicion, reloj = origen, salida
    for parada in paradas:
        km = haversine_km(posicion, parada.ubicacion)
        reloj = reloj + timedelta(hours=km / kmh)
        tramos.append(round(km, 2))
        llegadas.append(reloj.replace(microsecond=0))
        if parada.limite is not None and reloj > parada.limite:
            accion = "Recoger en" if parada.tipo == "recoger" else "Entregar en"
            retrasos.append(
                f"{accion} {parada.nombre}: llega {reloj:%H:%M}, límite {parada.limite:%H:%M}"
            )
        reloj += timedelta(minutes=MINUTOS_POR_PARADA)
        posicion = parada.ubicacion
    return RutaCalculada(
        estrategia=estrategia,
        paradas=list(paradas),
        km_por_tramo=tramos,
        llegadas=llegadas,
        km_total=round(sum(tramos), 2),
        minutos=round((reloj - salida).total_seconds() / 60, 1),
        cumple_limites=not retrasos,
        retrasos=retrasos,
    )


class EstrategiaRuta(ABC):
    """Strategy: cada estrategia elige la siguiente parada con su propia regla."""

    nombre: str = "estrategia"

    def ordenar(
        self, origen: Ubicacion, paradas: list[Parada], transporte: str, salida: datetime
    ) -> RutaCalculada:
        recolecciones = {p.donativo_id for p in paradas if p.tipo == "recoger"}
        pendientes = list(paradas)
        recogidos: set[str] = set()
        orden: list[Parada] = []
        posicion = origen
        while pendientes:
            habilitadas = [
                p
                for p in pendientes
                if p.tipo == "recoger" or p.donativo_id in recogidos or p.donativo_id not in recolecciones
            ]
            siguiente = self.siguiente(posicion, habilitadas)
            pendientes.remove(siguiente)
            orden.append(siguiente)
            if siguiente.tipo == "recoger":
                recogidos.add(siguiente.donativo_id)
            posicion = siguiente.ubicacion
        return recorrer(self.nombre, origen, orden, transporte, salida)

    @abstractmethod
    def siguiente(self, posicion: Ubicacion, habilitadas: list[Parada]) -> Parada:
        """La próxima parada entre las que ya se pueden visitar."""


class VecinoMasCercano(EstrategiaRuta):
    """Siempre a la parada habilitada más cercana: suele dar menos kilómetros."""

    nombre = "vecino_mas_cercano"

    def siguiente(self, posicion: Ubicacion, habilitadas: list[Parada]) -> Parada:
        return min(habilitadas, key=lambda p: (haversine_km(posicion, p.ubicacion), p.donativo_id, p.tipo))


class PrimeroElMasUrgente(EstrategiaRuta):
    """Primero la recolección con el límite más próximo; las entregas, por cercanía."""

    nombre = "primero_el_mas_urgente"

    def siguiente(self, posicion: Ubicacion, habilitadas: list[Parada]) -> Parada:
        lejano = datetime.max
        return min(
            habilitadas,
            key=lambda p: (
                p.limite or lejano,
                haversine_km(posicion, p.ubicacion),
                p.donativo_id,
                p.tipo,
            ),
        )


ESTRATEGIAS: dict[str, EstrategiaRuta] = {e.nombre: e for e in (VecinoMasCercano(), PrimeroElMasUrgente())}
