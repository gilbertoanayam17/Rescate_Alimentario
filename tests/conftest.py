"""Fixtures compartidas: una aplicación completa en memoria con el LLM falso.

Las pruebas NO dependen de datos/semilla.json (Alejandro lo puede cambiar libremente):
cada prueba crea sus propios participantes con las fixtures de abajo.

Archivo COMPARTIDO.
"""
from __future__ import annotations

import pytest

from rescate.contenedor import construir_aplicacion
from rescate.dominio.enums import Rol, TipoAlimento
from rescate.dominio.modelos import Actor, Donante, Receptor, Recolector, Ubicacion
from rescate.llm.falso import ClienteLLMFalso


@pytest.fixture
def llm_falso() -> ClienteLLMFalso:
    return ClienteLLMFalso()


@pytest.fixture
def aplicacion(llm_falso):
    """Servicios, repositorios, bitácora y orquestador (para pruebas que necesitan los internos)."""
    return construir_aplicacion(llm=llm_falso, ruta_db=":memory:", cargar_datos_semilla=False)


@pytest.fixture
def servicios(aplicacion):
    return aplicacion.servicios


@pytest.fixture
def repos(aplicacion):
    return aplicacion.repos


@pytest.fixture
def coordinador() -> Actor:
    return Actor(rol=Rol.COORDINADOR)


@pytest.fixture
def actor_de():
    """actor_de(participante) -> el Actor con el que ese participante usa los servicios."""
    return lambda p: Actor(rol=p.rol, participante_id=p.id)


@pytest.fixture
def donante(servicios, coordinador) -> Donante:
    d = Donante(
        id="don-prueba",
        nombre="Fonda de Prueba",
        ubicacion=Ubicacion(lat=20.6741, lon=-103.3404),
        hora_cierre="18:00",
    )
    servicios.participantes.registrar(coordinador, d)
    return d


@pytest.fixture
def receptores(servicios, coordinador) -> list[Receptor]:
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
        servicios.participantes.registrar(coordinador, r)
    return lista


@pytest.fixture
def recolector(servicios, coordinador) -> Recolector:
    r = Recolector(id="vol-prueba", nombre="Voluntario de Prueba", ubicacion=Ubicacion(lat=20.67, lon=-103.34))
    servicios.participantes.registrar(coordinador, r)
    return r
