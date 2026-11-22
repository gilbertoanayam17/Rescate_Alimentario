"""Tablero de impacto (CAR-08): calculadora, filtros, autorización, historial y rendimiento."""
from __future__ import annotations

import time
from datetime import date, datetime, timedelta

import pytest

from rescate.config import cargar_configuracion
from rescate.dominio.enums import EstadoDonativo, Rol, TipoAlimento
from rescate.dominio.modelos import Actor, Alimento, Asignacion, Donativo, ahora
from rescate.herramientas import impacto
from rescate.semilla import cargar_semilla
from rescate.servicios import ErrorAutorizacion
from scripts import generar_historial as gh

HOY = ahora().date()


def entregado(donante_id, receptor_id, kg, dia: date, tipo=TipoAlimento.PREPARADO) -> Donativo:
    momento = datetime.combine(dia, datetime.min.time()).replace(hour=18)
    return Donativo(
        donante_id=donante_id,
        texto_original="prueba",
        alimentos=[Alimento(nombre="guisado", cantidad=kg, unidad="kg", tipo=tipo, kg_estimados=kg)],
        estado=EstadoDonativo.ENTREGADO,
        asignacion=Asignacion(receptor_id=receptor_id, aceptada=True),
        creado=momento,
        actualizado=momento,
    )


# --------------------------------------------------------------- calculadora


def test_factores_con_fuente_publicada():
    assert impacto.KG_POR_RACION == 0.42  # WRAP (2020)
    assert impacto.CO2E_POR_KG == pytest.approx(3.3 / 1.6)  # FAO (2013)
    assert "WRAP" in impacto.FUENTES and "FAO" in impacto.FUENTES


def test_raciones_y_co2e():
    assert impacto.raciones(4.2) == 10
    assert impacto.raciones(0.41) == 0
    assert impacto.raciones(-3) == 0
    assert impacto.co2e_evitado(1.6) == 3.3
    assert impacto.co2e_evitado(10, TipoAlimento.PANADERIA) == pytest.approx(20.62)
    assert impacto.CalculadoraImpacto.raciones(8.4) == 20


def test_resumen_cuenta_donantes_y_receptores():
    lista = [entregado("a", "r1", 2, HOY), entregado("a", "r2", 1.36, HOY), entregado("b", None, 1, HOY)]
    r = impacto.resumen(lista)
    assert (r.kg, r.raciones, r.donativos, r.donantes, r.receptores) == (4.36, 10, 3, 2, 2)
    assert r.co2e_kg == pytest.approx(4.36 * 3.3 / 1.6, abs=0.02)
    assert impacto.resumen([]).kg == 0


# ------------------------------------------------------------------ tablero


@pytest.fixture
def con_entregas(aplicacion, donante, receptores):
    lunes = HOY - timedelta(days=HOY.weekday() + 14)  # lunes de hace dos semanas
    guardar = aplicacion.repos.donativos.guardar
    guardar(entregado(donante.id, "rec-cerca", 4.2, lunes))
    guardar(entregado(donante.id, "rec-lejos", 2.0, lunes + timedelta(days=2), TipoAlimento.PANADERIA))
    guardar(entregado("otro-donante", "rec-cerca", 1.0, lunes + timedelta(days=7)))
    guardar(entregado(donante.id, "rec-cerca", 50, HOY - timedelta(days=400)))  # fuera del periodo
    no_entregado = entregado(donante.id, "rec-cerca", 9, lunes)
    no_entregado.estado = EstadoDonativo.ASIGNADO
    guardar(no_entregado)
    return lunes


def test_tablero_del_coordinador(servicios, coordinador, donante, con_entregas):
    lunes = con_entregas
    t = servicios.reportes.tablero(coordinador, HOY - timedelta(days=30), HOY)
    assert t.resumen.kg == 7.2 and t.resumen.donativos == 3 and t.resumen.donantes == 2
    assert [p.participante_id for p in t.top_receptores] == ["rec-cerca", "rec-lejos"]
    assert t.top_receptores[0].kg == 5.2 and t.top_receptores[0].nombre == "Comedor Cerca"
    assert t.top_donantes[0].nombre == "Fonda de Prueba" and t.top_donantes[1].nombre == "otro-donante"
    assert t.kg_por_tipo == {"preparado": 5.2, "panaderia": 2.0}
    semanas = {p.semana: p.kg for p in t.serie_semanal}
    assert semanas[lunes] == 6.2 and semanas[lunes + timedelta(days=7)] == 1.0
    assert all(s.weekday() == 0 for s in semanas)
    assert sum(semanas.values()) == pytest.approx(7.2)  # semanas vacías en cero


def test_filtros_del_tablero(servicios, coordinador, donante, con_entregas):
    desde = HOY - timedelta(days=30)
    assert servicios.reportes.tablero(coordinador, desde, HOY, donante_id=donante.id).resumen.kg == 6.2
    assert servicios.reportes.tablero(coordinador, desde, HOY, receptor_id="rec-lejos").resumen.kg == 2.0
    assert servicios.reportes.tablero(coordinador, HOY - timedelta(days=500), HOY).resumen.kg == 57.2
    assert servicios.reportes.tablero(coordinador, con_entregas, con_entregas).resumen.kg == 4.2


def test_donante_y_receptor_solo_ven_lo_suyo(servicios, actor_de, donante, receptores, con_entregas):
    desde = HOY - timedelta(days=30)
    del_donante = servicios.reportes.tablero(actor_de(donante), desde, HOY, donante_id="otro-donante")
    assert del_donante.donante_id == donante.id and del_donante.resumen.kg == 6.2
    lejos = next(r for r in receptores if r.id == "rec-lejos")
    del_receptor = servicios.reportes.tablero(actor_de(lejos), desde, HOY, receptor_id="rec-cerca")
    assert del_receptor.receptor_id == "rec-lejos" and del_receptor.resumen.kg == 2.0


def test_autorizacion_del_tablero(servicios, actor_de, donante, recolector):
    with pytest.raises(ErrorAutorizacion):
        servicios.reportes.tablero(actor_de(recolector), HOY, HOY)
    with pytest.raises(ErrorAutorizacion):
        servicios.reportes.tablero(None, HOY, HOY)
    with pytest.raises(ErrorAutorizacion):  # rol falso: el id es de un donante
        servicios.reportes.tablero(Actor(rol=Rol.RECEPTOR, participante_id=donante.id), HOY, HOY)


# ---------------------------------------------------------------- historial


@pytest.fixture
def con_historial(aplicacion):
    cargar_semilla(aplicacion.repos.participantes, cargar_configuracion().ruta_semilla)
    con = aplicacion.repos.donativos._con
    total = gh.cargar_historial(con, aplicacion.repos.participantes, aplicacion.repos.donativos, hoy=HOY)
    return aplicacion, con, total


def test_historial_de_un_anio_con_sus_patrones(con_historial):
    aplicacion, _, total = con_historial
    donativos = aplicacion.repos.donativos.listar()
    assert total == len(donativos) > 300
    assert all(d.id.startswith(gh.PREFIJO) and d.estado == EstadoDonativo.ENTREGADO for d in donativos)
    fin = HOY - timedelta(days=gh.DIAS_SIN_HISTORIA)
    assert max(d.creado.date() for d in donativos) <= fin
    assert min(d.creado.date() for d in donativos) >= fin - timedelta(days=365)
    lupe = [d for d in donativos if d.donante_id == "don-lupe"]
    assert lupe and {d.creado.weekday() for d in lupe} <= {0, 1, 2, 3}
    assert all(2 <= d.kg_totales <= 4 for d in lupe)
    espiga = [d for d in donativos if d.donante_id == "pan-espiga"]
    assert {d.creado.weekday() for d in espiga} <= {1, 4}
    assert all(25 <= sum(a.cantidad for a in d.alimentos) <= 35 for d in espiga)
    assert {d.creado.weekday() for d in donativos if d.donante_id == "fru-guero"} <= {5}
    assert {d.creado.weekday() for d in donativos if d.donante_id == "tac-corona"} <= {6}
    # historial de estados con fechas del pasado y en orden
    h = aplicacion.repos.donativos.historial(lupe[0].id)
    assert h[0]["evento"] == "publicar" and h[-1]["evento"] == "entregar"
    assert h[-1]["fecha"].date() == lupe[0].creado.date()


def test_el_predictor_encuentra_el_patron_de_don_lupe(con_historial):
    from rescate.herramientas.patrones import detectar_patrones

    aplicacion, _, _ = con_historial
    proximo_lunes = HOY + timedelta(days=(7 - HOY.weekday()) % 7)
    patrones = detectar_patrones(aplicacion.repos.donativos.de_donante("don-lupe"), proximo_lunes)
    assert patrones and patrones[0].tipo == TipoAlimento.PREPARADO


def test_historial_reproducible_y_borrable(con_historial):
    aplicacion, con, total = con_historial
    ids = {d.id for d in aplicacion.repos.donativos.listar()}
    assert gh.cargar_historial(con, aplicacion.repos.participantes, aplicacion.repos.donativos, hoy=HOY) == total
    assert {d.id for d in aplicacion.repos.donativos.listar()} == ids  # misma semilla, sin duplicados
    assert gh.borrar(con) == total
    assert aplicacion.repos.donativos.listar() == []
    assert con.execute("SELECT count(*) FROM historial_estados").fetchone()[0] == 0


def test_caso_vencido_expira_al_revisar(con_historial):
    from rescate.dominio.enums import TipoCaso

    aplicacion, con, _ = con_historial
    gh.cargar_historial(con, aplicacion.repos.participantes, aplicacion.repos.donativos, con_caso_vencido=True, hoy=HOY)
    assert aplicacion.repos.donativos.obtener(gh.ID_VENCIDO).estado == EstadoDonativo.ASIGNADO
    assert [d.id for d in aplicacion.servicios.distribucion.vencer_pendientes()] == [gh.ID_VENCIDO]
    casos = aplicacion.servicios.casos.abiertos(Actor(rol=Rol.COORDINADOR))
    assert [(c.tipo, c.donativo_id) for c in casos] == [(TipoCaso.RECOLECCION_VENCIDA, gh.ID_VENCIDO)]


def test_tablero_de_un_anio_en_menos_de_3_segundos(con_historial):
    aplicacion, _, total = con_historial
    inicio = time.perf_counter()
    t = aplicacion.servicios.reportes.tablero(Actor(rol=Rol.COORDINADOR), HOY - timedelta(days=400), HOY)
    assert time.perf_counter() - inicio < 3
    assert t.resumen.donativos == total and len(t.top_donantes) == 7 and len(t.serie_semanal) >= 52


# ---------------------------------------------------------------- interfaz


def correr(aplicacion, actor, modulo):
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string(
        "import streamlit as st\n"
        f"from ui import {modulo}\n"
        f"{modulo}.mostrar(st.session_state['prueba_servicios'], st.session_state['prueba_actor'])\n",
        default_timeout=60,
    )
    app.session_state["prueba_servicios"] = aplicacion.servicios
    app.session_state["prueba_actor"] = actor
    app.run()
    assert not app.exception
    return app


def metrica(app, etiqueta):
    return next(m.value for m in app.metric if m.label == etiqueta)


def test_pestana_impacto_con_un_anio_de_datos(con_historial):
    aplicacion, _, total = con_historial
    coordinador = Actor(rol=Rol.COORDINADOR)
    app = correr(aplicacion, coordinador, "coordinador")
    anio = aplicacion.servicios.reportes.tablero(coordinador, HOY - timedelta(days=365), HOY)
    assert 300 < anio.resumen.donativos <= total
    assert metrica(app, "Donativos entregados") == f"{anio.resumen.donativos:,}"
    app.selectbox(key="coordinador_impacto_donante").select(
        aplicacion.repos.participantes.obtener("don-lupe")
    ).run()
    lupe = aplicacion.servicios.reportes.tablero(coordinador, HOY - timedelta(days=365), HOY, "don-lupe")
    assert metrica(app, "Donativos entregados") == f"{lupe.resumen.donativos:,}"
    app.date_input(key="coordinador_impacto_desde").set_value(HOY).run()
    assert "No hay entregas en este periodo." in [i.value for i in app.info]
    app.date_input(key="coordinador_impacto_hasta").set_value(HOY - timedelta(days=5)).run()
    assert app.error


def test_mi_impacto_del_receptor_y_del_donante(con_historial):
    aplicacion, _, _ = con_historial
    oblatos = aplicacion.repos.participantes.obtener("com-oblatos")
    app = correr(aplicacion, Actor(rol=Rol.RECEPTOR, participante_id=oblatos.id), "receptor")
    esperado = aplicacion.servicios.reportes.tablero(
        Actor(rol=Rol.RECEPTOR, participante_id=oblatos.id), HOY - timedelta(days=365), HOY
    ).resumen
    assert metrica(app, "Raciones equivalentes") == f"{esperado.raciones:,}"

    app = correr(aplicacion, Actor(rol=Rol.DONANTE, participante_id="don-lupe"), "donante")
    assert "Mi impacto (últimos 12 meses)" in [s.value for s in app.subheader]
    assert float(metrica(app, "Kg rescatados").replace(",", "")) > 0
