"""Strategy: criterios intercambiables de asignación con cálculos verificables."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel

from rescate.dominio.modelos import Donante, Donativo, Receptor
from rescate.persistencia.repositorios import RepositorioDonativos

from .capacidad import kg_disponibles
from .equidad import kg_recibidos_semana
from .geo import haversine_km
from .horario import puede_recibir_a_tiempo


@dataclass
class ContextoPuntuacion:
    donativo: Donativo
    donante: Donante
    receptor: Receptor
    distancia_km: float
    kg_disponibles: float
    abierto_a_tiempo: bool
    kg_recibidos_semana: float
    detalle_horario: str = ""


class CriterioPuntuacion(ABC):
    nombre: str
    peso: float

    @abstractmethod
    def puntuar(self, ctx: ContextoPuntuacion) -> float: ...
    @abstractmethod
    def explicar(self, ctx: ContextoPuntuacion) -> str: ...


class CriterioDistancia(CriterioPuntuacion):
    nombre, peso = "distancia", 0.35

    def puntuar(self, ctx: ContextoPuntuacion) -> float:
        return 1 - min(ctx.distancia_km, 15) / 15

    def explicar(self, ctx: ContextoPuntuacion) -> str:
        return f"{ctx.distancia_km:.1f} km en línea recta"


class CriterioCapacidad(CriterioPuntuacion):
    nombre, peso = "capacidad", 0.25

    def puntuar(self, ctx: ContextoPuntuacion) -> float:
        return (
            min(1, ctx.kg_disponibles / ctx.donativo.kg_totales)
            if ctx.donativo.kg_totales > 0
            else 0.0
        )

    def explicar(self, ctx: ContextoPuntuacion) -> str:
        return f"le caben {ctx.kg_disponibles:g} kg"


class CriterioHorario(CriterioPuntuacion):
    nombre, peso = "horario", 0.25

    def puntuar(self, ctx: ContextoPuntuacion) -> float:
        return float(ctx.abierto_a_tiempo)

    def explicar(self, ctx: ContextoPuntuacion) -> str:
        return ctx.detalle_horario or (
            "horario compatible" if ctx.abierto_a_tiempo else "fuera de horario"
        )


class CriterioEquidad(CriterioPuntuacion):
    nombre, peso = "equidad", 0.15

    def puntuar(self, ctx: ContextoPuntuacion) -> float:
        return 1 - min(ctx.kg_recibidos_semana, 100) / 100

    def explicar(self, ctx: ContextoPuntuacion) -> str:
        return f"recibió {ctx.kg_recibidos_semana:g} kg esta semana"


class Candidato(BaseModel):
    receptor_id: str
    nombre: str
    total: float
    desglose: dict[str, float]
    explicacion: str


class Puntuador:
    def __init__(self, criterios: list[CriterioPuntuacion]) -> None:
        if not criterios or abs(sum(c.peso for c in criterios) - 1) > 1e-9:
            raise ValueError("Los pesos deben sumar uno")
        if any(c.peso < 0 for c in criterios):
            raise ValueError("Los pesos no pueden ser negativos")
        if len({c.nombre for c in criterios}) != len(criterios):
            raise ValueError("Los criterios deben tener nombres distintos")
        self.criterios = criterios

    def clasificar(self, contextos: list[ContextoPuntuacion]) -> list[Candidato]:
        """Ordena por puntaje; usa el id para desempatar de forma estable."""
        salida = []
        for ctx in contextos:
            valores = {
                c.nombre: max(0.0, min(1.0, c.puntuar(ctx))) for c in self.criterios
            }
            salida.append(
                Candidato(
                    receptor_id=ctx.receptor.id,
                    nombre=ctx.receptor.nombre,
                    total=round(
                        sum(c.peso * valores[c.nombre] for c in self.criterios), 3
                    ),
                    desglose=valores,
                    explicacion=" · ".join(c.explicar(ctx) for c in self.criterios),
                )
            )
        return sorted(salida, key=lambda c: (-c.total, c.receptor_id))


def construir_contexto(
    donativo: Donativo,
    donante: Donante,
    receptor: Receptor,
    donativos_repo: RepositorioDonativos,
    ahora: datetime,
) -> ContextoPuntuacion:
    """Reúne los cálculos que consumirán las estrategias y el modelo."""
    abierto, detalle = puede_recibir_a_tiempo(receptor, donativo, ahora)
    return ContextoPuntuacion(
        donativo,
        donante,
        receptor,
        haversine_km(donante.ubicacion, receptor.ubicacion),
        kg_disponibles(receptor, donativos_repo, ahora.date()),
        abierto,
        kg_recibidos_semana(receptor.id, donativos_repo),
        detalle,
    )


def crear_puntuador() -> Puntuador:
    """Construye la estrategia de cuatro criterios del MVP."""
    return Puntuador(
        [CriterioDistancia(), CriterioCapacidad(), CriterioHorario(), CriterioEquidad()]
    )
