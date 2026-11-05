"""Fixtures compartidas: un servicio completo en memoria con el LLM falso.

Las pruebas NO dependen de datos/semilla.json (Alejandro lo puede cambiar libremente):
cada prueba crea sus propios participantes con las fixtures de abajo.

Archivo COMPARTIDO (fase 0).
"""
from __future__ import annotations

import pytest

from rescate.contenedor import construir_servicio
from rescate.dominio.enums import TipoAlimento
from rescate.dominio.modelos import Donante, Receptor, Recolector, Ubicacion
from rescate.llm.falso import ClienteLLMFalso


@pytest.fixture
def llm_falso() -> ClienteLLMFalso:
    return ClienteLLMFalso()


@pytest.fixture
def servicio(llm_falso):
    return construir_servicio(llm=llm_falso, ruta_db=":memory:", cargar_datos_semilla=False)


@pytest.fixture
def donante(servicio) -> Donante:
    d = Donante(
        id="don-prueba",
        nombre="Fonda de Prueba",
        ubicacion=Ubicacion(lat=20.6741, lon=-103.3404),
        hora_cierre="18:00",
    )
    servicio.registrar_participante(d)
    return d


@pytest.fixture
def receptores(servicio) -> list[Receptor]:
    lista = [
        Receptor(  # cerca, sin refrigeración
            id="rec-cerca",
            nombre="Comedor Cerca",
            ubicacion=Ubicacion(lat=20.6800, lon=-103.3400),
            tipos_aceptados=[TipoAlimento.PREPARADO, TipoAlimento.PANADERIA, TipoAlimento.FRUTA_VERDURA],
            tiene_refrigeracion=False,
        ),
        Receptor(  # lejos, con refrigeración y acepta todo
            id="rec-lejos",
            nombre="Albergue Lejos",
            ubicacion=Ubicacion(lat=20.6157, lon=-103.3468),
            tiene_refrigeracion=True,
        ),
    ]
    for r in lista:
        servicio.registrar_participante(r)
    return lista


@pytest.fixture
def recolector(servicio) -> Recolector:
    r = Recolector(id="vol-prueba", nombre="Voluntario de Prueba", ubicacion=Ubicacion(lat=20.67, lon=-103.34))
    servicio.registrar_participante(r)
    return r
