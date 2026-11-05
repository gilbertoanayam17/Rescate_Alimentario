"""Historial de entregas para repartir los donativos."""

from rescate.persistencia.repositorios import RepositorioDonativos


def kg_recibidos_semana(receptor_id: str, donativos: RepositorioDonativos) -> float:
    """Suma únicamente entregas de los últimos siete días."""
    return sum(d.kg_totales for d in donativos.recibidos_ultimos_dias(receptor_id, 7))
