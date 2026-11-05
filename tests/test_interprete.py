"""Pruebas del Agente Intérprete (CAR-01) con el LLM falso y un reloj fijo."""
from __future__ import annotations

from datetime import datetime

import pytest

from rescate.agentes.interprete import (
    MARCA_ACLARACION,
    AgenteInterprete,
    calcular_recoger_antes_de,
    hora_relativa,
)
from rescate.bitacora import Bitacora
from rescate.dominio.enums import Conservacion, TipoAlimento, TipoEntradaBitacora
from rescate.dominio.modelos import Donante, SolicitudInterpretacion, Ubicacion
from rescate.persistencia.db import conectar
from rescate.persistencia.repositorios import BitacoraDuckDB

AHORA = datetime(2026, 11, 5, 17, 0)
MOLE = "2 charolas de pollo en mole"


@pytest.fixture
def bitacora() -> Bitacora:
    return Bitacora(BitacoraDuckDB(conectar(":memory:")))


@pytest.fixture
def donante() -> Donante:
    return Donante(id="don-prueba", nombre="Fonda de Prueba", ubicacion=Ubicacion(lat=20.67, lon=-103.34), hora_cierre="18:00")


@pytest.fixture
def agente(llm_falso, bitacora) -> AgenteInterprete:
    return AgenteInterprete(llm_falso, bitacora, reloj=lambda: AHORA)


def alimento(nombre, cantidad, unidad, tipo, conservacion="desconocida", observaciones=""):
    return {
        "nombre": nombre,
        "cantidad": cantidad,
        "unidad": unidad,
        "tipo": tipo,
        "conservacion": conservacion,
        "observaciones": observaciones,
    }


def respuesta(alimentos, hora=None, recoger=None, faltantes=(), pregunta=None, razonamiento="Entendí el mensaje."):
    return {
        "razonamiento": razonamiento,
        "alimentos": alimentos,
        "hora_preparacion": hora,
        "recoger_antes_de": recoger,
        "datos_faltantes": list(faltantes),
        "pregunta": pregunta,
    }


MOLE_SIN_DATOS = respuesta(
    [alimento("pollo en mole", 2, "charola", "preparado")],
    faltantes=["hora de preparación", "conservación"],
    pregunta="¿A qué hora preparaste el mole y cómo lo has guardado?",
)


def solicitud(texto, donante):
    return SolicitudInterpretacion(texto=texto, donante=donante, donativo_id="don-1")


def test_frase_completa_calcula_kilos_en_codigo(agente, llm_falso, donante):
    llm_falso.programar(
        "InterpretacionLLM",
        respuesta([alimento("bolillos", 15, "pieza", "panaderia"), alimento("manzana", 2, "kg", "fruta_verdura")]),
    )
    r = agente.ejecutar(solicitud("15 bolillos y 2 kg de manzana", donante))
    assert r.completo and r.preguntas == []
    assert [(a.nombre, a.kg_estimados) for a in r.alimentos] == [("bolillos", 1.05), ("manzana", 2.0)]


def test_guisado_sin_hora_ni_conservacion_pregunta(agente, llm_falso, donante):
    llm_falso.programar("InterpretacionLLM", MOLE_SIN_DATOS)
    r = agente.ejecutar(solicitud(MOLE, donante))
    assert not r.completo
    assert r.preguntas == ["¿A qué hora preparaste el mole y cómo lo has guardado?"]


def test_aclaracion_completa_hora_y_conservacion(agente, llm_falso, donante):
    llm_falso.programar(
        "InterpretacionLLM",
        respuesta([alimento("pollo en mole", 2, "charola", "preparado", "refrigerado")], hora="14:00"),
    )
    r = agente.ejecutar(solicitud(MOLE + MARCA_ACLARACION + "lo hice a las 2 y está en el refri", donante))
    assert r.completo
    assert r.hora_preparacion == datetime(2026, 11, 5, 14, 0)
    assert r.alimentos[0].conservacion == Conservacion.REFRIGERADO
    # El prompt lleva la hora actual y el contexto del comercio
    prompt = llm_falso.llamadas[0][1]
    assert "Hora actual: 17:00" in prompt and "Fonda de Prueba (fonda), cierra a las 18:00" in prompt


def test_tras_dos_aclaraciones_ya_no_pregunta(agente, llm_falso, donante):
    llm_falso.programar("InterpretacionLLM", MOLE_SIN_DATOS)
    texto = MOLE + MARCA_ACLARACION + "no sé" + MARCA_ACLARACION + "no me acuerdo"
    r = agente.ejecutar(solicitud(texto, donante))
    assert r.completo and r.preguntas == []
    assert r.alimentos[0].tipo == TipoAlimento.PREPARADO


def test_sin_respuesta_del_llm_usa_reglas_y_anota_error(agente, bitacora, donante):
    r = agente.ejecutar(solicitud("15 bolillos y 2 kg de manzana", donante))
    assert r.completo and len(r.alimentos) == 2
    tipos = [e.tipo for e in bitacora.de_donativo("don-1")]
    assert TipoEntradaBitacora.ERROR in tipos


def test_bitacora_muestra_el_razonamiento(agente, llm_falso, bitacora, donante):
    llm_falso.programar("InterpretacionLLM", {**MOLE_SIN_DATOS, "razonamiento": "Es un guisado sin hora."})
    agente.ejecutar(solicitud(MOLE, donante))
    entradas = bitacora.de_donativo("don-1")
    assert [e.tipo for e in entradas] == [
        TipoEntradaBitacora.ACCION,
        TipoEntradaBitacora.PENSAMIENTO,
        TipoEntradaBitacora.OBSERVACION,
        TipoEntradaBitacora.RESULTADO,
    ]
    assert "InterpretacionLLM" in entradas[0].contenido
    assert entradas[1].contenido == "Es un guisado sin hora."
    assert entradas[3].contenido.startswith("Pregunto:")


def test_hora_en_el_futuro_es_de_ayer(agente, llm_falso, donante):
    llm_falso.programar(
        "InterpretacionLLM",
        respuesta([alimento("frijoles", 3, "kg", "preparado", "refrigerado")], hora="21:00"),
    )
    r = agente.ejecutar(solicitud("3 kg de frijoles de anoche en el refri", donante))
    assert r.hora_preparacion == datetime(2026, 11, 4, 21, 0)


def test_hace_una_hora_lo_calcula_el_codigo(agente, llm_falso, donante):
    llm_falso.programar(  # el LLM se equivoca en la resta; manda el cálculo del código
        "InterpretacionLLM",
        respuesta([alimento("pollo en mole", 2, "charola", "preparado", "refrigerado")], hora="15:00"),
    )
    r = agente.ejecutar(solicitud(MOLE + MARCA_ACLARACION + "lo hice hace una hora y lo tengo en el refri", donante))
    assert r.completo and r.hora_preparacion == datetime(2026, 11, 5, 16, 0)


def test_sin_pregunta_del_llm_usa_una_por_defecto(agente, llm_falso, donante):
    llm_falso.programar("InterpretacionLLM", respuesta([alimento("arroz", 1.5, "kg", "preparado")]))
    r = agente.ejecutar(solicitud("kilo y medio de arroz", donante))
    assert not r.completo
    assert "arroz" in r.preguntas[0] and "hora" in r.preguntas[0]


def test_sin_alimentos_pregunta_que_le_sobro(agente, llm_falso, donante):
    llm_falso.programar("InterpretacionLLM", respuesta([]))
    r = agente.ejecutar(solicitud("hola", donante))
    assert not r.completo and "sobraron" in r.preguntas[0]


def test_cantidades_no_positivas_se_descartan(agente, llm_falso, donante):
    llm_falso.programar(
        "InterpretacionLLM",
        respuesta([alimento("conchas", 0, "pieza", "panaderia"), alimento("bolillos", 10, "pieza", "panaderia")]),
    )
    r = agente.ejecutar(solicitud("10 bolillos", donante))
    assert [a.nombre for a in r.alimentos] == ["bolillos"]


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("lo hice hace una hora", datetime(2026, 11, 5, 16, 0)),
        ("hace media hora", datetime(2026, 11, 5, 16, 30)),
        ("hace 2 horas y media", datetime(2026, 11, 5, 14, 30)),
        ("hace 45 minutos", datetime(2026, 11, 5, 16, 15)),
        ("lo hice a las 2", None),
    ],
)
def test_hora_relativa(texto, esperado):
    assert hora_relativa(texto, AHORA) == esperado


def test_recoger_antes_de(donante):
    # Sin dato del donante: cierre (18:00) + 1 h
    assert calcular_recoger_antes_de(None, donante, AHORA) == datetime(2026, 11, 5, 19, 0)
    # El donante dijo hasta qué hora
    assert calcular_recoger_antes_de("19:30", donante, AHORA) == datetime(2026, 11, 5, 19, 30)
    # Ya pasó la hora de cierre + 1 h: ahora + 2 h
    tarde = datetime(2026, 11, 5, 20, 0)
    assert calcular_recoger_antes_de(None, donante, tarde) == datetime(2026, 11, 5, 22, 0)


def test_arroz_de_fonda_marcado_como_abarrote_se_trata_como_preparado(agente, llm_falso, bitacora, donante):
    llm_falso.programar(
        "InterpretacionLLM",
        respuesta([alimento("bolillos", 15, "pieza", "panaderia"), alimento("arroz", 1.5, "kg", "abarrote")]),
    )
    r = agente.ejecutar(solicitud("Me sobraron 15 bolis y kilo y medio de arroz", donante))
    assert r.alimentos[1].tipo == TipoAlimento.PREPARADO
    assert not r.completo and "arroz" in r.preguntas[0]
    assert any("como preparado" in e.contenido for e in bitacora.de_donativo("don-1"))


@pytest.mark.parametrize(
    "nombre, observaciones, tipo_comercio",
    [
        ("arroz crudo", "", "fonda"),
        ("arroz", "bolsa cerrada", "fonda"),
        ("arroz", "", "panadería"),
    ],
)
def test_arroz_crudo_o_fuera_de_fonda_sigue_como_abarrote(agente, llm_falso, donante, nombre, observaciones, tipo_comercio):
    donante.tipo_comercio = tipo_comercio
    llm_falso.programar("InterpretacionLLM", respuesta([alimento(nombre, 2, "kg", "abarrote", observaciones=observaciones)]))
    r = agente.ejecutar(solicitud(f"2 kg de {nombre} {observaciones}", donante))
    assert r.completo and r.alimentos[0].tipo == TipoAlimento.ABARROTE
