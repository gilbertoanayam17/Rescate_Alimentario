"""Filtros de tipo y condiciones del dictamen, independientes del LLM."""

from dataclasses import dataclass

from rescate.dominio.enums import Dictamen
from rescate.dominio.modelos import Donativo, Receptor


@dataclass
class ResultadoCompatibilidad:
    compatible: bool
    motivos: list[str]


def evaluar_compatibilidad(
    donativo: Donativo, receptor: Receptor
) -> ResultadoCompatibilidad:
    """Explica todos los filtros duros que incumple un receptor."""
    motivos = []
    if receptor.id in donativo.receptores_descartados:
        motivos.append("El receptor ya rechazó este donativo")
    for tipo in sorted({a.tipo for a in donativo.alimentos}, key=lambda t: t.value):
        if tipo not in receptor.tipos_aceptados:
            motivos.append(f"No acepta {tipo.value}")
    if donativo.dictamen:
        if donativo.dictamen.dictamen == Dictamen.NO_APTO:
            motivos.append("Donativo no apto")
        if (
            donativo.dictamen.requiere_refrigeracion
            and not receptor.tiene_refrigeracion
        ):
            motivos.append("No tiene refrigeración")
    return ResultadoCompatibilidad(not motivos, motivos)
