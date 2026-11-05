"""Capacidad restante calculada a partir de donativos comprometidos."""

from datetime import date

from rescate.dominio.modelos import Receptor
from rescate.persistencia.repositorios import RepositorioDonativos


def kg_disponibles(
    receptor: Receptor, donativos: RepositorioDonativos, dia: date | None = None
) -> float:
    """Descuenta compromisos del día sin devolver capacidad negativa."""
    return max(
        0.0, receptor.capacidad_kg_dia - donativos.kg_asignados(receptor.id, dia)
    )
