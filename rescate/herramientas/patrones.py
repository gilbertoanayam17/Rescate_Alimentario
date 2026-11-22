"""Patrones de excedentes por día de la semana (CAR-07). Herramienta determinista del Predictor.

"Los lunes sobran guisados": se cuentan las semanas en que el donante donó ese tipo de alimento
el mismo día de la semana. Los kilos y la confianza los calcula este código, nunca el LLM.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from rescate.dominio.enums import EstadoDonativo, TipoAlimento
from rescate.dominio.modelos import Donativo

DIAS_PLURAL = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábados", "domingos")
EXCLUIDOS = {EstadoDonativo.RECHAZADO, EstadoDonativo.CANCELADO}


@dataclass(frozen=True)
class Patron:
    donante_id: str
    dia_semana: int  # 0 = lunes
    tipo: TipoAlimento
    descripcion: str  # los 2 nombres más frecuentes: "pan dulce y bolillo"
    semanas_con_donativo: int
    semanas_observadas: int
    kg_promedio: float
    confianza: float  # semanas_con_donativo / semanas_observadas


def detectar_patrones(
    donativos: list[Donativo], fecha: date, semanas: int = 8, minimo: int = 3
) -> list[Patron]:
    """Donativos con `creado` en [fecha - semanas*7, fecha), sin RECHAZADO ni CANCELADO, del mismo
    día de la semana que `fecha`. Agrupa por tipo; conserva los que aparecen en al menos `minimo`
    semanas distintas y los ordena por confianza (mayor primero).

    Las semanas observadas cuentan desde el primer donativo del donante (como máximo `semanas`):
    un comercio que empezó hace 3 semanas y donó los 3 lunes tiene confianza 3/3, no 3/8."""
    inicio = fecha - timedelta(days=semanas * 7)
    primero: dict[str, date] = {}
    kg_por_semana: dict[tuple[str, TipoAlimento], dict[int, float]] = defaultdict(lambda: defaultdict(float))
    nombres: dict[tuple[str, TipoAlimento], Counter[str]] = defaultdict(Counter)
    for d in donativos:
        dia = d.creado.date()
        if d.estado in EXCLUIDOS or dia >= fecha:
            continue
        primero[d.donante_id] = min(dia, primero.get(d.donante_id, dia))
        if dia < inicio or dia.weekday() != fecha.weekday():
            continue
        semana = (fecha - dia).days // 7
        for a in d.alimentos:
            clave = (d.donante_id, a.tipo)
            kg_por_semana[clave][semana] += a.kg_estimados
            nombres[clave][a.nombre.strip().lower()] += 1

    patrones = []
    for (donante_id, tipo), por_semana in kg_por_semana.items():
        if len(por_semana) < minimo:
            continue
        frecuentes = [n for n, _ in nombres[(donante_id, tipo)].most_common(2)]
        observadas = max(len(por_semana), min(semanas, (fecha - primero[donante_id]).days // 7))
        patrones.append(
            Patron(
                donante_id=donante_id,
                dia_semana=fecha.weekday(),
                tipo=tipo,
                descripcion=" y ".join(frecuentes),
                semanas_con_donativo=len(por_semana),
                semanas_observadas=observadas,
                kg_promedio=round(sum(por_semana.values()) / len(por_semana), 1),
                confianza=round(len(por_semana) / observadas, 2),
            )
        )
    return sorted(patrones, key=lambda p: (-p.confianza, -p.kg_promedio, p.tipo.value))
