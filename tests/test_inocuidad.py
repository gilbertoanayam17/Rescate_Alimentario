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
CITA_VALIDA = re.compile(
    r"^(NOM-251-SSA1-2009, numeral (5\.5\.2|7\.3\.2|7\.3\.3)|Criterio interno CI-0[1-7])$"
)


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
    assert esperados.count("no_apto") >= 30  # meta de la visión: 30 no aptos, ninguno aprobado
    assert len(esperados) - esperados.count("no_apto") >= 8
    # cada criterio de rechazo tiene casos propios
    _, dictamenes = zip(
        *(evaluar_con_reglas(donativo_de(c), AHORA) for c in CASOS if c["esperado"] == "no_apto")
    )
    reglas = {cita for d in dictamenes for cita in d.reglas_citadas if cita.startswith("Criterio interno")}
    assert {f"Criterio interno CI-0{i}" for i in (1, 2, 3, 6, 7)} <= reglas


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
    _, d = evaluar_con_reglas(
        donativo_de(_caso("Me quedaron 3 litros de leche que dejé afuera desde la mañana")), AHORA
    )
    assert d.dictamen == Dictamen.NO_APTO
    assert "Criterio interno CI-02" in d.reglas_citadas
    assert d.condiciones == []  # en un no apto ya no aplican condiciones de manejo


def test_mole_refrigerado_pide_frio_y_cita_la_nom():
    hallazgos, d = evaluar_con_reglas(
        donativo_de(_caso("2 charolas de pollo en mole que hice hace una hora y está en el refri")), AHORA
    )
    assert d.dictamen == Dictamen.APTO_CON_CONDICIONES
    assert d.requiere_refrigeracion
    assert CONDICION_FRIO in d.condiciones
    assert "NOM-251-SSA1-2009, numeral 7.3.3" in d.reglas_citadas
    # Vida TOTAL de un preparado refrigerado: el Asignador le suma la hora de preparación
    assert d.vida_util_horas == 12
    vida = next(h for h in hallazgos if h.regla == "CI-06")
    assert "le quedan 11 h" in vida.motivo


def test_vida_util_es_total_y_el_limite_del_asignador_queda_en_el_futuro():
    from rescate.herramientas.horario import limite_recoleccion

    donativo = donativo_de(_caso("Medio kilo de queso fresco en el refri desde ayer a las 10"))  # hace 19 h
    _, d = evaluar_con_reglas(donativo, AHORA)
    assert d.vida_util_horas == 24  # lácteo
    donativo.dictamen = d
    donativo.recoger_antes_de = AHORA + timedelta(hours=12)  # para que mande la vida útil
    assert limite_recoleccion(donativo, AHORA) == AHORA + timedelta(hours=5)  # 24 h - 19 h transcurridas


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
        "alimentos": [
            {
                "nombre": "pollo agridulce",
                "cantidad": 2,
                "unidad": "charola",
                "tipo": "preparado",
                "conservacion": "refrigerado",
            }
        ],
        "hora_preparacion_horas_antes": 1,
    }
    _, d = evaluar_con_reglas(donativo_de(caso), AHORA)
    assert d.dictamen == Dictamen.APTO_CON_CONDICIONES


def test_combinar_toma_lo_mas_estricto_y_no_repite():
    hallazgos = [
        Hallazgo(
            regla="CI-04",
            dictamen=Dictamen.APTO_CON_CONDICIONES,
            motivo="frío",
            condiciones=["A"],
            requiere_refrigeracion=True,
            citas=["X"],
        ),
        Hallazgo(
            regla="CI-05",
            dictamen=Dictamen.APTO_CON_CONDICIONES,
            motivo="caliente",
            condiciones=["A", "B"],
            citas=["X", "Y"],
        ),
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


# ------------------------------------------------------- agente con RAG y LLM

from rescate.rag.base_conocimiento import BaseConocimiento, Fragmento  # noqa: E402

FRAGMENTOS = [
    Fragmento(
        texto="b) Los que se sirven fríos a una temperatura de 7°C (45°F) o menos.",
        fuente="nom251_extracto.md",
        seccion="NOM-251-SSA1-2009, numeral 7.3.3: temperatura de alimentos preparados calientes y fríos",
    ),
    Fragmento(
        texto="Cadena de frío...",
        fuente="criterios_donacion.md",
        seccion="Criterio interno CI-04: cadena de frío",
    ),
]
MOLE_FRIO = "2 charolas de pollo en mole que hice hace una hora y está en el refri"


class BaseFija(BaseConocimiento):
    def __init__(self, fragmentos):
        self.fragmentos = fragmentos
        self.consultas: list[str] = []

    def buscar(self, consulta, k=4):
        self.consultas.append(consulta)
        return self.fragmentos[:k]


@pytest.fixture
def base_fija():
    return BaseFija(FRAGMENTOS)


@pytest.fixture
def agente_rag(llm_falso, bitacora, base_fija):
    from rescate.agentes.inocuidad import AgenteInocuidad

    return AgenteInocuidad(llm_falso, bitacora, base_fija, reloj=lambda: AHORA)


def evaluacion(dictamen, citas=(), condiciones=(), motivo="Motivo del LLM."):
    return {
        "razonamiento": "Revisé la temperatura y el tiempo.",
        "dictamen": dictamen,
        "motivo": motivo,
        "condiciones": list(condiciones),
        "citas": list(citas),
    }


def test_el_llm_no_puede_relajar_el_dictamen(agente_rag, llm_falso, bitacora):
    llm_falso.programar("EvaluacionLLM", evaluacion("apto", motivo="Es apto."))
    donativo = donativo_de(_caso(MOLE_FRIO))
    d = agente_rag.ejecutar(donativo)
    assert d.dictamen == Dictamen.APTO_CON_CONDICIONES
    assert d.motivo != "Es apto."  # no se muestra un motivo que contradice el dictamen
    assert CONDICION_FRIO in d.condiciones and d.requiere_refrigeracion
    assert any("no puede relajar" in e.contenido for e in bitacora.de_donativo(donativo.id))


def test_el_llm_puede_endurecer_a_no_apto(agente_rag, llm_falso):
    llm_falso.programar("EvaluacionLLM", evaluacion("no_apto", motivo="El mole huele raro según el texto."))
    d = agente_rag.ejecutar(donativo_de(_caso(MOLE_FRIO)))
    assert d.dictamen == Dictamen.NO_APTO
    assert d.motivo == "El mole huele raro según el texto."
    assert d.condiciones == []


def test_cita_inventada_se_descarta_y_la_valida_se_conserva(agente_rag, llm_falso, bitacora):
    llm_falso.programar(
        "EvaluacionLLM",
        evaluacion(
            "apto_con_condiciones",
            citas=[
                "NOM-251-SSA1-2009, numeral 7.3.3: temperatura de alimentos preparados calientes y fríos",
                "NOM-251-SSA1-2009, numeral 9.9.9",
            ],
            condiciones=["Transportar en hielera"],
        ),
    )
    donativo = donativo_de(_caso(MOLE_FRIO))
    d = agente_rag.ejecutar(donativo)
    assert "NOM-251-SSA1-2009, numeral 7.3.3" in d.reglas_citadas
    assert not any("9.9.9" in c for c in d.reglas_citadas)
    assert "Transportar en hielera" in d.condiciones and CONDICION_FRIO in d.condiciones
    assert d.motivo == "Motivo del LLM."
    assert any(
        "Descarto citas" in e.contenido and "9.9.9" in e.contenido for e in bitacora.de_donativo(donativo.id)
    )


def test_cita_sin_tema_tambien_se_acepta_si_coincide_con_un_fragmento(agente_rag, llm_falso):
    llm_falso.programar("EvaluacionLLM", evaluacion("apto_con_condiciones", citas=["Criterio interno CI-04"]))
    d = agente_rag.ejecutar(donativo_de(_caso(MOLE_FRIO)))
    assert d.reglas_citadas.count("Criterio interno CI-04") == 1


def test_con_no_apto_de_reglas_el_llm_ni_se_llama(agente_rag, llm_falso, base_fija):
    d = agente_rag.ejecutar(
        donativo_de(_caso("Me quedaron 3 litros de leche que dejé afuera desde la mañana"))
    )
    assert d.dictamen == Dictamen.NO_APTO
    assert llm_falso.llamadas == [] and base_fija.consultas == []


def test_sin_llm_queda_el_dictamen_de_las_reglas(agente_rag, llm_falso, bitacora):
    donativo = donativo_de(_caso(MOLE_FRIO))
    d = agente_rag.ejecutar(donativo)
    _, esperado = evaluar_con_reglas(donativo, AHORA)
    assert d == esperado
    assert any(e.tipo.value == "error" for e in bitacora.de_donativo(donativo.id))


def test_el_prompt_lleva_horas_calculadas_hallazgos_y_fragmentos(agente_rag, llm_falso, base_fija):
    llm_falso.programar("EvaluacionLLM", evaluacion("apto_con_condiciones"))
    agente_rag.ejecutar(donativo_de(_caso(MOLE_FRIO)))
    prompt = llm_falso.llamadas[0][1]
    assert "hace 1 h, calculado por el sistema" in prompt
    assert "CI-04:" in prompt and "Vida útil (calculada): 12 h desde su preparación; le quedan 11 h" in prompt
    assert "Sección: NOM-251-SSA1-2009, numeral 7.3.3" in prompt
    assert "refrigeración a 7 °C" in base_fija.consultas[0]


def test_si_el_rag_falla_sigue_sin_fragmentos(llm_falso, bitacora):
    from rescate.agentes.inocuidad import AgenteInocuidad
    from rescate.llm.cliente import ErrorLLM

    class BaseRota(BaseConocimiento):
        def buscar(self, consulta, k=4):
            raise ErrorLLM("sin embeddings")

    llm_falso.programar(
        "EvaluacionLLM", evaluacion("apto_con_condiciones", citas=["NOM-251-SSA1-2009, numeral 7.3.3"])
    )
    d = AgenteInocuidad(llm_falso, bitacora, BaseRota(), reloj=lambda: AHORA).ejecutar(
        donativo_de(_caso(MOLE_FRIO))
    )
    assert d.dictamen == Dictamen.APTO_CON_CONDICIONES
    # sin fragmentos, ninguna cita del LLM se puede verificar; quedan solo las de las reglas
    assert d.reglas_citadas == evaluar_con_reglas(donativo_de(_caso(MOLE_FRIO)), AHORA)[1].reglas_citadas


@pytest.mark.parametrize(
    "cita, clave",
    [
        ("NOM-251-SSA1-2009, numeral 7.3.3: temperatura de alimentos", "NOM-251-SSA1-2009, numeral 7.3.3"),
        ("NOM-251, numeral 5.5.2", "NOM-251-SSA1-2009, numeral 5.5.2"),
        ("Criterio interno CI-04: cadena de frío", "Criterio interno CI-04"),
        ("CI-04: Pollo en mole: necesita cadena de frío", "Criterio interno CI-04"),
    ],
)
def test_clave_cita_normaliza(cita, clave):
    from rescate.agentes.inocuidad import clave_cita

    assert clave_cita(cita) == clave


def test_cita_con_formato_de_hallazgo_se_acepta_si_el_criterio_se_recupero(agente_rag, llm_falso):
    llm_falso.programar(
        "EvaluacionLLM",
        evaluacion("apto_con_condiciones", citas=["CI-04: Pollo en mole: necesita cadena de frío"]),
    )
    d = agente_rag.ejecutar(donativo_de(_caso(MOLE_FRIO)))
    assert "Criterio interno CI-04" in d.reglas_citadas


def test_condiciones_casi_repetidas_no_se_duplican(agente_rag, llm_falso):
    llm_falso.programar(
        "EvaluacionLLM",
        evaluacion(
            "apto_con_condiciones",
            condiciones=[
                "Mantener a 7 °C o menos durante la recolección y la entrega.",
                "El receptor debe contar con refrigeración.",
                "Llevarlo en hielera.",
                "Entregarlo antes de las 20:00.",
            ],
        ),
    )
    d = agente_rag.ejecutar(donativo_de(_caso(MOLE_FRIO)))
    assert d.condiciones == [
        CONDICION_FRIO,
        "El receptor debe contar con refrigeración.",
        "Llevarlo en hielera.",
    ]


def test_clave_cita_ignora_la_etiqueta_seccion():
    from rescate.agentes.inocuidad import clave_cita

    assert clave_cita("Sección: Criterio interno CI-04: cadena de frío") == "Criterio interno CI-04"
    assert (
        clave_cita("[2] Sección: NOM-251-SSA1-2009, numeral 7.3.3: tema")
        == "NOM-251-SSA1-2009, numeral 7.3.3"
    )


def test_un_apto_no_lleva_condiciones_del_llm(agente_rag, llm_falso):
    llm_falso.programar("EvaluacionLLM", evaluacion("apto", condiciones=["Lavar los jitomates"]))
    d = agente_rag.ejecutar(donativo_de(_caso("Me sobraron 15 bolillos y 5 kg de jitomate")))
    assert d.dictamen == Dictamen.APTO and d.condiciones == []
