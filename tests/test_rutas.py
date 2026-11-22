"""Estrategias de ruta (Strategy, CAR-04): orden, precedencia, tiempos y límites."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from rescate.dominio.modelos import Ubicacion
from rescate.herramientas.geo import haversine_km
from rescate.herramientas.rutas import (
    CAPACIDAD_KG,
    ESTRATEGIAS,
    MINUTOS_POR_PARADA,
    Parada,
    PrimeroElMasUrgente,
    VecinoMasCercano,
    capacidad,
    recorrer,
    velocidad,
)

SALIDA = datetime(2026, 11, 23, 17, 0)
ORIGEN = Ubicacion(lat=20.6700, lon=-103.3500)
CERCA = Ubicacion(lat=20.6750, lon=-103.3500)  # ~0.6 km
LEJOS = Ubicacion(lat=20.7000, lon=-103.3500)  # ~3.3 km
JUNTO_AL_ORIGEN = Ubicacion(lat=20.6705, lon=-103.3500)


def test_tablas_de_transporte():
    assert CAPACIDAD_KG == {"a pie": 5, "bicicleta": 10, "moto": 15, "auto": 60}
    assert velocidad("bicicleta") == 12 and velocidad("patineta") == 4
    assert capacidad("moto") == 15 and capacidad("desconocido") == 5
    assert set(ESTRATEGIAS) == {"vecino_mas_cercano", "primero_el_mas_urgente"}


def test_la_entrega_va_despues_de_su_recoleccion():
    paradas = [
        Parada("entregar", "d1", "Comedor junto al origen", JUNTO_AL_ORIGEN),
        Parada("recoger", "d1", "Fonda lejana", LEJOS),
    ]
    for estrategia in (VecinoMasCercano(), PrimeroElMasUrgente()):
        ruta = estrategia.ordenar(ORIGEN, paradas, "auto", SALIDA)
        assert ruta.orden() == [("recoger", "d1"), ("entregar", "d1")]


def test_lo_que_ya_lleva_se_puede_entregar_de_inmediato():
    paradas = [
        Parada("recoger", "d2", "Fonda lejana", LEJOS),
        Parada("entregar", "d1", "Comedor junto al origen", JUNTO_AL_ORIGEN),  # d1 ya va en camino
        Parada("entregar", "d2", "Comedor cerca", CERCA),
    ]
    ruta = VecinoMasCercano().ordenar(ORIGEN, paradas, "auto", SALIDA)
    assert ruta.orden() == [("entregar", "d1"), ("recoger", "d2"), ("entregar", "d2")]


def test_vecino_mas_cercano_y_primero_el_mas_urgente_difieren():
    paradas = [
        Parada("recoger", "cerca", "Cerca", CERCA, limite=SALIDA + timedelta(hours=3)),
        Parada("recoger", "lejos", "Lejos", LEJOS, limite=SALIDA + timedelta(hours=1)),
    ]
    vecino = VecinoMasCercano().ordenar(ORIGEN, paradas, "auto", SALIDA)
    urgente = PrimeroElMasUrgente().ordenar(ORIGEN, paradas, "auto", SALIDA)
    assert [p.donativo_id for p in vecino.paradas] == ["cerca", "lejos"]
    assert [p.donativo_id for p in urgente.paradas] == ["lejos", "cerca"]
    assert vecino.estrategia == "vecino_mas_cercano" and urgente.estrategia == "primero_el_mas_urgente"
    assert vecino.cumple_limites and urgente.cumple_limites


def test_kilometros_y_llegadas_los_calcula_el_codigo():
    paradas = [Parada("recoger", "d", "Lejos", LEJOS)]
    ruta = recorrer("vecino_mas_cercano", ORIGEN, paradas, "bicicleta", SALIDA)
    km = haversine_km(ORIGEN, LEJOS)
    assert ruta.km_total == pytest.approx(km, abs=0.01)
    assert ruta.llegadas[0] == (SALIDA + timedelta(hours=km / 12)).replace(microsecond=0)
    assert ruta.minutos == pytest.approx(km / 12 * 60 + MINUTOS_POR_PARADA, abs=0.1)


def test_detecta_limites_incumplidos():
    paradas = [Parada("recoger", "d", "Fonda lejana", LEJOS, limite=SALIDA + timedelta(minutes=15))]
    a_pie = recorrer("vecino_mas_cercano", ORIGEN, paradas, "a pie", SALIDA)  # 3.3 km a 4 km/h: ~50 min
    assert not a_pie.cumple_limites and "Recoger en Fonda lejana" in a_pie.retrasos[0]
    en_auto = recorrer("vecino_mas_cercano", ORIGEN, paradas, "auto", SALIDA)  # ~10 min, límite de 15
    assert en_auto.cumple_limites and en_auto.retrasos == []
