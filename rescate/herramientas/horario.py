"""Ventanas de recepción; el reloj se recibe para poder probar los límites."""

from datetime import datetime, time, timedelta

from rescate.dominio.modelos import Donativo, Receptor


def limite_recoleccion(donativo: Donativo, ahora: datetime) -> datetime:
    """Usa el plazo más estricto entre recolección y vida útil."""
    limite = donativo.recoger_antes_de or ahora + timedelta(hours=4)
    if donativo.dictamen and donativo.dictamen.vida_util_horas is not None:
        limite = min(
            limite,
            (donativo.hora_preparacion or donativo.creado)
            + timedelta(hours=donativo.dictamen.vida_util_horas),
        )
    return limite


def puede_recibir_a_tiempo(
    receptor: Receptor, donativo: Donativo, ahora: datetime
) -> tuple[bool, str]:
    """Busca un cruce de ventanas, incluso para turnos nocturnos."""
    limite = limite_recoleccion(donativo, ahora)
    apertura = time.fromisoformat(receptor.hora_apertura)
    cierre = time.fromisoformat(receptor.hora_cierre)
    # Incluye el turno que pudo comenzar ayer y cruzar medianoche.
    for desplazamiento in (-1, 0, 1):
        dia = ahora.date() + timedelta(days=desplazamiento)
        inicio = datetime.combine(dia, apertura)
        fin = datetime.combine(dia, cierre)
        if cierre <= apertura:
            fin += timedelta(days=1)
        if max(ahora, inicio) < min(limite, fin):
            return (
                True,
                f"puede recibir entre {max(ahora, inicio):%d/%m %H:%M} "
                f"y {min(limite, fin):%H:%M}",
            )
    return False, "su horario no coincide con la ventana de recolección"
