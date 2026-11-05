"""Herramienta determinista de distancia (Haversine).

DUEÑO: Alejandro (flujo 2). Creada en la fase 0 porque el asignador mínimo la usa.
"""
from __future__ import annotations

import math

from rescate.dominio.modelos import Ubicacion

RADIO_TIERRA_KM = 6371.0


def haversine_km(a: Ubicacion, b: Ubicacion) -> float:
    """Distancia en línea recta entre dos puntos, en km."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * RADIO_TIERRA_KM * math.asin(math.sqrt(h))
