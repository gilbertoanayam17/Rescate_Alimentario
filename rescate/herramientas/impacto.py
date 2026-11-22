"""Calculadora de impacto (CAR-08): kg rescatados, raciones equivalentes y emisiones evitadas.

Herramienta determinista, separada del LLM: el modelo nunca calcula estas cifras.

Fuentes de los factores (no se inventan cifras):

- **Kg por ración: 0.42 kg.** WRAP (2020), *Expressing redistributed food surplus as meal
  equivalents* (guía), que recomienda 420 g como comida "promedio" para convertir el peso de
  alimento redistribuido en comidas equivalentes (sustituye al factor previo de 500 g).
  https://wrap.ngo/resources/guide/reporting-amounts-food-surplus-redistributed-weight-and-meal-equivalents-wrap
- **CO2e evitado: 2.06 kg CO2e por kg.** FAO (2013), *Food Wastage Footprint: Impacts on Natural
  Resources. Summary Report*: la huella de carbono del alimento producido y no consumido es de
  unos 3.3 Gt CO2e (sin cambio de uso de suelo) para 1.6 Gt de desperdicio (equivalente en
  producto primario). El factor es el cociente 3.3 / 1.6. https://www.fao.org/4/i3347e/i3347e.pdf

Es un promedio mundial para todos los tipos de alimento; `co2e_evitado` recibe el tipo para
poder usar factores por tipo en el futuro sin cambiar a quien lo llama.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from rescate.dominio.enums import TipoAlimento
from rescate.dominio.modelos import Donativo

#: WRAP (2020): 420 g por comida equivalente.
KG_POR_RACION = 0.42
#: FAO (2013): 3.3 Gt CO2e / 1.6 Gt de alimento desperdiciado.
CO2E_GT_FAO = 3.3
DESPERDICIO_GT_FAO = 1.6
CO2E_POR_KG = CO2E_GT_FAO / DESPERDICIO_GT_FAO

#: Factor por tipo de alimento. Hoy todos usan el promedio de la FAO.
CO2E_POR_KG_TIPO: dict[TipoAlimento, float] = dict.fromkeys(TipoAlimento, CO2E_POR_KG)

FUENTES = (
    "Raciones: WRAP (2020), 420 g por comida equivalente. "
    "Emisiones: FAO (2013), Food Wastage Footprint, 3.3 Gt CO2e / 1.6 Gt ≈ 2.06 kg CO2e por kg."
)


@dataclass(frozen=True)
class ResumenImpacto:
    kg: float
    raciones: int
    co2e_kg: float
    donativos: int
    donantes: int
    receptores: int


def raciones(kg: float) -> int:
    """Comidas equivalentes (hacia abajo: no se reportan comidas incompletas)."""
    return int(max(kg, 0) / KG_POR_RACION + 1e-9)


def co2e_evitado(kg: float, tipo: TipoAlimento = TipoAlimento.OTRO) -> float:
    """Kg de CO2e que no se emitieron porque el alimento se comió en vez de tirarse."""
    return round(max(kg, 0) * CO2E_POR_KG_TIPO.get(tipo, CO2E_POR_KG), 2)


def co2e_de(donativo: Donativo) -> float:
    return round(sum(co2e_evitado(a.kg_estimados, a.tipo) for a in donativo.alimentos), 2)


def resumen(donativos: Iterable[Donativo]) -> ResumenImpacto:
    """Resumen de los donativos dados (quien llama decide cuáles: normalmente los ENTREGADOS)."""
    lista = list(donativos)
    kg = round(sum(d.kg_totales for d in lista), 2)
    return ResumenImpacto(
        kg=kg,
        raciones=raciones(kg),
        co2e_kg=round(sum(co2e_de(d) for d in lista), 2),
        donativos=len(lista),
        donantes=len({d.donante_id for d in lista}),
        receptores=len({d.receptor_id for d in lista if d.receptor_id}),
    )


class CalculadoraImpacto:
    """Agrupa las funciones puras para inyectarlas o sustituirlas en pruebas."""

    raciones = staticmethod(raciones)
    co2e_evitado = staticmethod(co2e_evitado)
    resumen = staticmethod(resumen)
