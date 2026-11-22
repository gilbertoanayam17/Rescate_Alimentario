"""Agente Logístico (CAR-04): candidatos, elección del LLM validada, respaldo y servicio."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from rescate.agentes.logistico import AgenteLogistico, SolicitudRuta
from rescate.dominio.enums import EstadoDonativo, TipoEntradaBitacora
from rescate.dominio.modelos import (
    Alimento,
    Asignacion,
    Donante,
    Donativo,
    Receptor,
    Recolector,
    Ubicacion,
)
from rescate.servicios import ErrorAutorizacion

SALIDA = datetime(2026, 11, 23, 17, 0)
BASE = Ubicacion(lat=20.6700, lon=-103.3500)


def ubicacion(dlat: float) -> Ubicacion:
    return Ubicacion(lat=BASE.lat + dlat, lon=BASE.lon)


def donativo(id_: str, donante: str, receptor: str, kg: float, horas: float) -> Donativo:
    return Donativo(
        id=id_,
        donante_id=donante,
        texto_original="x",
        alimentos=[Alimento(nombre="guisado", cantidad=kg, unidad="kg", kg_estimados=kg)],
        recoger_antes_de=SALIDA + timedelta(hours=horas),
        estado=EstadoDonativo.ASIGNADO,
        asignacion=Asignacion(receptor_id=receptor, aceptada=True),
    )


PARTICIPANTES = {
    "don-cerca": Donante(id="don-cerca", nombre="Fonda Cerca", ubicacion=ubicacion(0.005)),
    "don-lejos": Donante(id="don-lejos", nombre="Fonda Lejos", ubicacion=ubicacion(0.03)),
    "don-muy-lejos": Donante(id="don-muy-lejos", nombre="Fonda Muy Lejos", ubicacion=ubicacion(0.2)),
    "rec": Receptor(id="rec", nombre="Comedor", ubicacion=ubicacion(0.01)),
}


def solicitud(transporte="auto", tomados=(), disponibles=()) -> SolicitudRuta:
    return SolicitudRuta(
        recolector=Recolector(id="vol", nombre="Iván", ubicacion=BASE, transporte=transporte),
        tomados=list(tomados),
        disponibles=list(disponibles),
        participantes=PARTICIPANTES,
        salida=SALIDA,
    )


@pytest.fixture
def agente(llm_falso, aplicacion):
    return AgenteLogistico(llm_falso, aplicacion.bitacora)


def tipos_en_bitacora(aplicacion) -> set:
    return {e.tipo for e in aplicacion.bitacora.recientes() if e.agente == "Logístico"}


def test_sin_donativos_no_hay_ruta(agente):
    assert agente.ejecutar(solicitud()) is None
    lejano = donativo("d", "don-muy-lejos", "rec", 2, 3)  # ~22 km: fuera del radio
    assert agente.ejecutar(solicitud(disponibles=[lejano])) is None


def test_capacidad_por_transporte(agente):
    a, b = donativo("a", "don-cerca", "rec", 6, 3), donativo("b", "don-lejos", "rec", 6, 4)
    en_bici = agente.ejecutar(solicitud("bicicleta", disponibles=[a, b]))  # 10 kg
    assert en_bici.por_tomar == ["a"] and en_bici.sin_capacidad == ["b"]
    en_auto = agente.ejecutar(solicitud("auto", disponibles=[a, b]))  # 60 kg
    assert sorted(en_auto.por_tomar) == ["a", "b"] and en_auto.sin_capacidad == []
    assert [p.tipo for p in en_auto.paradas].count("recoger") == 2
    assert [p.tipo for p in en_auto.paradas].count("entregar") == 2


def test_lo_que_ya_lleva_cuenta_para_la_capacidad(agente):
    llevo = donativo("llevo", "don-cerca", "rec", 9, 3)
    llevo.estado = EstadoDonativo.EN_RECOLECCION
    ruta = agente.ejecutar(solicitud("bicicleta", tomados=[llevo], disponibles=[donativo("b", "don-lejos", "rec", 2, 4)]))
    assert ruta.por_tomar == [] and ruta.sin_capacidad == ["b"]
    assert [(p.tipo, p.donativo_id) for p in ruta.paradas] == [("entregar", "llevo")]


def test_rutas_iguales_se_eligen_sin_llm(agente, llm_falso, aplicacion):
    ruta = agente.ejecutar(solicitud(disponibles=[donativo("a", "don-cerca", "rec", 2, 3)]))
    assert ruta.cumple_limites and "mismo orden" in ruta.explicacion
    assert llm_falso.llamadas == []
    assert {
        TipoEntradaBitacora.PENSAMIENTO,
        TipoEntradaBitacora.ACCION,
        TipoEntradaBitacora.OBSERVACION,
        TipoEntradaBitacora.RESULTADO,
    } <= tipos_en_bitacora(aplicacion)


def test_si_solo_una_cumple_se_elige_sin_llm(agente, llm_falso):
    # A pie: ir primero a la cercana hace que la lejana llegue tarde; la urgente primero sí cumple.
    cerca = donativo("cerca", "don-cerca", "rec", 1, 5)
    lejos = donativo("lejos", "don-lejos", "rec", 1, 1)
    ruta = agente.ejecutar(solicitud("a pie", disponibles=[cerca, lejos]))
    assert ruta.estrategia == "primero_el_mas_urgente" and ruta.cumple_limites
    assert "única ruta" in ruta.explicacion and llm_falso.llamadas == []


def dos_rutas_validas():
    return [donativo("cerca", "don-cerca", "rec", 1, 5), donativo("lejos", "don-lejos", "rec", 1, 3)]


def test_el_llm_elige_entre_dos_rutas_que_cumplen(agente, llm_falso):
    llm_falso.programar(
        "DecisionRuta",
        {"razonamiento": "La lejana vence antes", "estrategia": "primero_el_mas_urgente", "explicacion": "Primero lo que vence."},
    )
    ruta = agente.ejecutar(solicitud(disponibles=dos_rutas_validas()))
    assert ruta.estrategia == "primero_el_mas_urgente" and ruta.explicacion == "Primero lo que vence."
    nombre, prompt = llm_falso.llamadas[0]
    assert nombre == "DecisionRuta" and "<datos_ruta>" in prompt


def test_respaldo_con_error_del_llm(agente, llm_falso, aplicacion):
    ruta = agente.ejecutar(solicitud(disponibles=dos_rutas_validas()))  # sin respuesta programada
    assert ruta.estrategia == "vecino_mas_cercano"  # la de menos km
    assert "menos kilómetros" in ruta.explicacion
    assert TipoEntradaBitacora.ERROR in tipos_en_bitacora(aplicacion)


def test_respaldo_con_respuesta_invalida_del_llm(agente, llm_falso):
    llm_falso.programar("DecisionRuta", {"razonamiento": "x", "estrategia": "la_mas_bonita", "explicacion": "x"})
    assert agente.ejecutar(solicitud(disponibles=dos_rutas_validas())).estrategia == "vecino_mas_cercano"


def test_si_ninguna_cumple_el_llm_puede_elegir(agente, llm_falso):
    tarde = [donativo("cerca", "don-cerca", "rec", 1, 0.01), donativo("lejos", "don-lejos", "rec", 1, 0.02)]
    llm_falso.programar(
        "DecisionRuta", {"razonamiento": "x", "estrategia": "primero_el_mas_urgente", "explicacion": "Ambas tarde."}
    )
    ruta = agente.ejecutar(solicitud("a pie", disponibles=tarde))
    assert not ruta.cumple_limites and ruta.retrasos and ruta.explicacion == "Ambas tarde."


# ------------------------------------------------------------------ servicio


@pytest.fixture
def dos_aceptados(servicios, actor_de, coordinador, donante, receptores):
    otro = Donante(id="don-otro", nombre="Panadería Vecina", ubicacion=Ubicacion(lat=20.6760, lon=-103.3420))
    servicios.participantes.registrar(coordinador, otro)
    ids = []
    for quien, texto in ((donante, "20 bolillos"), (otro, "15 bolillos")):
        d = servicios.publicacion.publicar(actor_de(quien), texto).donativo
        receptor = next(r for r in receptores if r.id == d.receptor_id)
        servicios.distribucion.aceptar(actor_de(receptor), d.id)
        ids.append(d.id)
    return ids


def test_ruta_sugerida_con_dos_recolecciones_y_sus_entregas(servicios, actor_de, recolector, dos_aceptados):
    ruta = servicios.distribucion.ruta_sugerida(actor_de(recolector))
    assert sorted(ruta.por_tomar) == sorted(dos_aceptados)
    tipos = [p.tipo for p in ruta.paradas]
    assert tipos.count("recoger") == 2 and tipos.count("entregar") == 2
    for donativo_id in dos_aceptados:
        orden = [p.tipo for p in ruta.paradas if p.donativo_id == donativo_id]
        assert orden == ["recoger", "entregar"]


def test_ruta_sugerida_valida_el_rol(servicios, actor_de, donante, recolector):
    with pytest.raises(ErrorAutorizacion):
        servicios.distribucion.ruta_sugerida(actor_de(donante))
    assert servicios.distribucion.ruta_sugerida(actor_de(recolector)) is None


def test_tomar_ruta_parcial_si_otro_voluntario_gano_uno(servicios, actor_de, coordinador, recolector, dos_aceptados):
    rival = Recolector(id="vol-rival", nombre="Rival", ubicacion=recolector.ubicacion)
    servicios.participantes.registrar(coordinador, rival)
    servicios.distribucion.iniciar_recoleccion(actor_de(rival), dos_aceptados[0])
    perdidos = servicios.distribucion.tomar_ruta(actor_de(recolector), dos_aceptados)
    assert perdidos == [dos_aceptados[0]]
    assert servicios.reportes.donativo(coordinador, dos_aceptados[1]).recolector_id == recolector.id


def test_pestana_mi_ruta(servicios, actor_de, coordinador, recolector, dos_aceptados):
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string(
        "import streamlit as st\n"
        "from ui import recolector\n"
        "recolector.mostrar(st.session_state['prueba_servicios'], st.session_state['prueba_actor'])\n",
        default_timeout=30,
    )
    app.session_state["prueba_servicios"] = servicios
    app.session_state["prueba_actor"] = actor_de(recolector)
    app.run()
    app.button(key="recolector_calcular_ruta").click().run()
    assert not app.exception
    assert next(m.value for m in app.metric if m.label == "Paradas") == "4"
    app.button(key="recolector_tomar_ruta").click().run()
    assert not app.exception
    for donativo_id in dos_aceptados:
        assert servicios.reportes.donativo(coordinador, donativo_id).estado == EstadoDonativo.EN_RECOLECCION
    assert any("Tomaste 2 donativo(s)." in s.value for s in app.success)
