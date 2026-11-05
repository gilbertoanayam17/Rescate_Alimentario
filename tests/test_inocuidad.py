"""Pruebas de inocuidad (CAR-02): la cadena de reglas deterministas y el agente."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from rescate.agentes.interprete import estimar_kg
from rescate.agentes.reglas_inocuidad import (
    CONDICION_FRIO,
    Hallazgo,
    ReglaCadenaFrio,
    ReglaSenalesDeterioro,
    ReglaVidaUtil,
    combinar,
    crear_cadena,
    evaluar_con_reglas,
)
from rescate.dominio.enums import Conservacion, Dictamen, TipoAlimento
from rescate.dominio.modelos import Alimento, Donativo

AHORA = datetime(2026, 11, 5, 17, 0)
CASOS = json.loads((Path(__file__).parent / "casos_inocuidad.json").read_text(encoding="utf-8"))
CITA_VALIDA = re.compile(r"^(NOM-251-SSA1-2009, numeral (5\.5\.2|7\.3\.2|7\.3\.3)|Criterio interno CI-0[1-7])$")


def donativo_de(caso: dict) -> Donativo:
    alimentos = []
    for a in caso["alimentos"]:
        tipo = TipoAlimento(a["tipo"])
        alimentos.append(
            Alimento(
                nombre=a["nombre"],
                cantidad=a["cantidad"],
                unidad=a["unidad"],
                tipo=tipo,
                conservacion=Conservacion(a["conservacion"]),
                kg_estimados=estimar_kg(a["cantidad"], a["unidad"], tipo),
                observaciones=a.get("observaciones", ""),
            )
        )
    horas = caso["hora_preparacion_horas_antes"]
    return Donativo(
        donante_id="don-prueba",
        texto_original=caso["texto"],
        alimentos=alimentos,
        hora_preparacion=None if horas is None else AHORA - timedelta(hours=horas),
    )


def test_hay_suficientes_casos():
    esperados = [c["esperado"] for c in CASOS]
    assert esperados.count("no_apto") >= 8
    assert len(esperados) - esperados.count("no_apto") >= 8


@pytest.mark.parametrize("caso", CASOS, ids=[c["texto"][:40] for c in CASOS])
def test_casos_de_inocuidad(caso):
    _, dictamen = evaluar_con_reglas(donativo_de(caso), AHORA)
    if caso["esperado"] == "no_apto":
        # Meta de la visión: cero no aptos aprobados
        assert dictamen.dictamen == Dictamen.NO_APTO, dictamen.motivo
    assert dictamen.dictamen.value == caso["esperado"], dictamen.motivo
    assert dictamen.reglas_citadas, "todo dictamen debe citar su fundamento"
    assert all(CITA_VALIDA.match(c) for c in dictamen.reglas_citadas), dictamen.reglas_citadas


def _caso(texto: str) -> dict:
    return next(c for c in CASOS if c["texto"] == texto)


def test_leche_afuera_cita_ci02():
    _, d = evaluar_con_reglas(donativo_de(_caso("Me quedaron 3 litros de leche que dejé afuera desde la mañana")), AHORA)
    assert d.dictamen == Dictamen.NO_APTO
    assert "Criterio interno CI-02" in d.reglas_citadas
    assert d.condiciones == []  # en un no apto ya no aplican condiciones de manejo


def test_mole_refrigerado_pide_frio_y_cita_la_nom():
    _, d = evaluar_con_reglas(donativo_de(_caso("2 charolas de pollo en mole que hice hace una hora y está en el refri")), AHORA)
    assert d.dictamen == Dictamen.APTO_CON_CONDICIONES
    assert d.requiere_refrigeracion
    assert CONDICION_FRIO in d.condiciones
    assert "NOM-251-SSA1-2009, numeral 7.3.3" in d.reglas_citadas
    assert d.vida_util_horas == 11  # 12 h de un preparado refrigerado - 1 h transcurrida


def test_comida_caliente_pide_60_grados_y_recalentar():
    _, d = evaluar_con_reglas(donativo_de(_caso("10 porciones de pozole recién hecho, calientito")), AHORA)
    assert any("60 °C" in c and "74 °C" in c for c in d.condiciones)
    assert "NOM-251-SSA1-2009, numeral 7.3.2" in d.reglas_citadas
    assert d.requiere_refrigeracion


def test_bajo_riesgo_es_apto_con_vida_util_minima():
    _, d = evaluar_con_reglas(donativo_de(_caso("Me sobraron 15 bolillos y 5 kg de jitomate")), AHORA)
    assert d.dictamen == Dictamen.APTO and d.motivo == "Alimentos de bajo riesgo."
    assert d.vida_util_horas == 24  # mínimo entre panadería (24) y fruta (48)
    assert not d.requiere_refrigeracion


def test_la_cadena_respeta_el_orden_de_la_tabla():
    donativo = donativo_de(_caso("2 kg de queso que ya huele mal"))
    reglas = [h.regla for h in crear_cadena().evaluar(donativo, AHORA)]
    assert reglas == ["CI-01", "CI-04", "CI-06"]


def test_enlazar_devuelve_el_siguiente_eslabon():
    primera, segunda, tercera = ReglaSenalesDeterioro(), ReglaCadenaFrio(), ReglaVidaUtil()
    assert primera.enlazar(segunda) is segunda
    assert segunda.enlazar(tercera) is tercera


def test_agridulce_no_es_senal_de_deterioro():
    caso = {
        "texto": "2 charolas de pollo agridulce en el refri",
        "alimentos": [{"nombre": "pollo agridulce", "cantidad": 2, "unidad": "charola", "tipo": "preparado", "conservacion": "refrigerado"}],
        "hora_preparacion_horas_antes": 1,
    }
    _, d = evaluar_con_reglas(donativo_de(caso), AHORA)
    assert d.dictamen == Dictamen.APTO_CON_CONDICIONES


def test_combinar_toma_lo_mas_estricto_y_no_repite():
    hallazgos = [
        Hallazgo(regla="CI-04", dictamen=Dictamen.APTO_CON_CONDICIONES, motivo="frío", condiciones=["A"], requiere_refrigeracion=True, citas=["X"]),
        Hallazgo(regla="CI-05", dictamen=Dictamen.APTO_CON_CONDICIONES, motivo="caliente", condiciones=["A", "B"], citas=["X", "Y"]),
        Hallazgo(regla="CI-06", dictamen=Dictamen.APTO, motivo="vida", vida_util_horas=4, citas=["Z"]),
    ]
    d = combinar(hallazgos)
    assert d.dictamen == Dictamen.APTO_CON_CONDICIONES
    assert d.motivo == "frío"
    assert d.condiciones == ["A", "B"]
    assert d.reglas_citadas == ["X", "Y", "Z"]
    assert d.vida_util_horas == 4 and d.requiere_refrigeracion


def test_combinar_sin_hallazgos_es_apto():
    d = combinar([])
    assert d.dictamen == Dictamen.APTO and d.motivo == "Alimentos de bajo riesgo."


# ------------------------------------------------------------------- agente


@pytest.fixture
def bitacora():
    from rescate.bitacora import Bitacora
    from rescate.persistencia.db import conectar
    from rescate.persistencia.repositorios import BitacoraDuckDB

    return Bitacora(BitacoraDuckDB(conectar(":memory:")))


@pytest.fixture
def agente(llm_falso, bitacora):
    from rescate.agentes.inocuidad import AgenteInocuidad

    return AgenteInocuidad(llm_falso, bitacora, None, reloj=lambda: AHORA)


def test_agente_anota_una_observacion_por_hallazgo(agente, bitacora):
    donativo = donativo_de(_caso("Me quedaron 3 litros de leche que dejé afuera desde la mañana"))
    dictamen = agente.ejecutar(donativo)
    assert dictamen.dictamen == Dictamen.NO_APTO
    observaciones = [e.contenido for e in bitacora.de_donativo(donativo.id) if e.tipo.value == "observacion"]
    assert any(o.startswith("CI-02:") for o in observaciones)
