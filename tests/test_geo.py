"""Prueba de la herramienta de distancia. Creada en la fase 0; dueño: Alejandro."""
import pytest

from rescate.dominio.modelos import Ubicacion
from rescate.herramientas.geo import haversine_km


def test_un_grado_de_latitud_son_111_km():
    assert haversine_km(Ubicacion(lat=0, lon=0), Ubicacion(lat=1, lon=0)) == pytest.approx(111.19, abs=0.1)


def test_misma_ubicacion_es_cero():
    p = Ubicacion(lat=20.67, lon=-103.34)
    assert haversine_km(p, p) == 0
