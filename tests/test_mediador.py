"""Escalamiento con Mediator y expiración (CAR-10, CAR-05)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from rescate.contenedor import construir_aplicacion
from rescate.dominio.enums import Dictamen, EstadoCaso, EstadoDonativo, Rol, TipoAlimento, TipoCaso
from rescate.dominio.modelos import (
    Actor,
    Alimento,
    DictamenInocuidad,
    Donante,
    Donativo,
    Receptor,
    Ubicacion,
)
from rescate.servicios import ErrorAutorizacion, ErrorServicio

CENTRO = Ubicacion(lat=20.6741, lon=-103.3404)


def tipos_abiertos(servicios, coordinador, donativo_id=None) -> list[TipoCaso]:
    return [c.tipo for c in servicios.casos.abiertos(coordinador) if donativo_id in (None, c.donativo_id)]


def evaluado_que_requiere_frio(repos, donante) -> Donativo:
    d = Donativo(
        donante_id=donante.id,
        texto_original="3 litros de leche",
        alimentos=[Alimento(nombre="leche", cantidad=3, unidad="litro", tipo=TipoAlimento.LACTEO, kg_estimados=3)],
        estado=EstadoDonativo.EVALUADO,
        dictamen=DictamenInocuidad(dictamen=Dictamen.APTO_CON_CONDICIONES, motivo="Frío", requiere_refrigeracion=True),
    )
    repos.donativos.guardar(d)
    return d


# ------------------------------------------------------------------ mediador


def test_no_duplica_casos_abiertos_y_avisa_a_la_coordinacion(aplicacion, servicios, coordinador):
    primero = aplicacion.mediador.notificar("Intérprete", TipoCaso.POSIBLE_INYECCION, "d1", "texto raro")
    segundo = aplicacion.mediador.notificar("Intérprete", TipoCaso.POSIBLE_INYECCION, "d1", "otra vez")
    assert primero is not None and segundo is None
    assert tipos_abiertos(servicios, coordinador) == [TipoCaso.POSIBLE_INYECCION]
    avisos = servicios.notificaciones.avisos(coordinador)
    assert [a.mensaje for a in avisos] == ["Intérprete: texto raro"]
    assert avisos[0].titulo == "Caso: Posible manipulación del agente"
    # otro tipo para el mismo donativo sí abre caso
    assert aplicacion.mediador.notificar("Inocuidad", TipoCaso.INOCUIDAD_DUDOSA, "d1", "dudoso")


def test_asignar_resuelve_solo_el_caso_sin_receptor(aplicacion, servicios, actor_de, coordinador, donante):
    d = servicios.publicacion.publicar(actor_de(donante), "10 bolillos").donativo
    aplicacion.mediador.notificar("Inocuidad", TipoCaso.INOCUIDAD_DUDOSA, d.id, "revisar")
    assert set(tipos_abiertos(servicios, coordinador, d.id)) == {TipoCaso.SIN_RECEPTOR, TipoCaso.INOCUIDAD_DUDOSA}

    servicios.participantes.registrar(coordinador, Receptor(id="rec-nuevo", nombre="Nuevo", ubicacion=CENTRO))
    servicios.distribucion.reintentar_asignacion(coordinador, d.id)
    assert tipos_abiertos(servicios, coordinador, d.id) == [TipoCaso.INOCUIDAD_DUDOSA]
    resuelto = next(c for c in aplicacion.repos.casos.de_donativo(d.id) if c.tipo == TipoCaso.SIN_RECEPTOR)
    assert resuelto.estado == EstadoCaso.RESUELTO and resuelto.resolucion.startswith("Resuelto")


def test_el_segundo_rechazo_abre_rechazos_repetidos(servicios, actor_de, coordinador, donante, receptores):
    d = servicios.publicacion.publicar(actor_de(donante), "20 bolillos").donativo
    primero = next(r for r in receptores if r.id == d.receptor_id)
    d = servicios.distribucion.rechazar(actor_de(primero), d.id, "Sin espacio")
    assert tipos_abiertos(servicios, coordinador, d.id) == []
    segundo = next(r for r in receptores if r.id == d.receptor_id)
    servicios.distribucion.rechazar(actor_de(segundo), d.id, "Cerramos temprano")
    abiertos = tipos_abiertos(servicios, coordinador, d.id)
    assert set(abiertos) == {TipoCaso.RECHAZOS_REPETIDOS, TipoCaso.SIN_RECEPTOR}
    caso = next(c for c in servicios.casos.abiertos(coordinador) if c.tipo == TipoCaso.RECHAZOS_REPETIDOS)
    assert "Cerramos temprano" in caso.motivo


def test_cancelar_resuelve_los_casos_del_donativo(servicios, actor_de, coordinador, donante):
    d = servicios.publicacion.publicar(actor_de(donante), "10 bolillos").donativo
    assert tipos_abiertos(servicios, coordinador, d.id) == [TipoCaso.SIN_RECEPTOR]
    servicios.publicacion.cancelar(coordinador, d.id, "Ya no hay")
    assert tipos_abiertos(servicios, coordinador, d.id) == []


# --------------------------------------------------------------- expiración


@pytest.fixture
def con_reloj(llm_falso):
    """Aplicación con un reloj que la prueba adelanta a mano."""
    momento = {"ahora": datetime(2026, 11, 23, 12, 0)}
    app = construir_aplicacion(
        llm=llm_falso, ruta_db=":memory:", cargar_datos_semilla=False, reloj=lambda: momento["ahora"]
    )
    coordinador = Actor(rol=Rol.COORDINADOR)
    donante = Donante(id="don-reloj", nombre="Fonda", ubicacion=CENTRO, hora_cierre="23:00")
    receptor = Receptor(id="rec-reloj", nombre="Comedor", ubicacion=CENTRO, hora_apertura="00:00", hora_cierre="23:59")
    for p in (donante, receptor):
        app.servicios.participantes.registrar(coordinador, p)
    return app, momento, donante, receptor


def test_vencer_pendientes_con_reloj_fijo(con_reloj):
    app, momento, donante, receptor = con_reloj
    servicios, coordinador = app.servicios, Actor(rol=Rol.COORDINADOR)
    d = servicios.publicacion.publicar(Actor(rol=Rol.DONANTE, participante_id=donante.id), "20 bolillos").donativo
    assert d.estado == EstadoDonativo.ASIGNADO
    d.recoger_antes_de = momento["ahora"] + timedelta(hours=1)
    app.repos.donativos.guardar(d)

    assert servicios.distribucion.vencer_pendientes() == []
    momento["ahora"] += timedelta(hours=2)
    vencidos = servicios.distribucion.vencer_pendientes()
    assert [v.id for v in vencidos] == [d.id]
    assert app.repos.donativos.obtener(d.id).estado == EstadoDonativo.EXPIRADO
    assert tipos_abiertos(servicios, coordinador, d.id) == [TipoCaso.RECOLECCION_VENCIDA]
    avisos = servicios.notificaciones.avisos(Actor(rol=Rol.RECEPTOR, participante_id=receptor.id))
    assert "El donativo venció sin recogerse" in [a.mensaje for a in avisos]
    assert servicios.distribucion.vencer_pendientes() == []  # no se vence dos veces


def test_no_vence_lo_que_ya_va_en_camino(con_reloj):
    app, momento, donante, _ = con_reloj
    d = app.servicios.publicacion.publicar(Actor(rol=Rol.DONANTE, participante_id=donante.id), "20 bolillos").donativo
    d.estado = EstadoDonativo.EN_RECOLECCION
    d.recoger_antes_de = momento["ahora"] - timedelta(hours=1)
    app.repos.donativos.guardar(d)
    assert app.servicios.distribucion.vencer_pendientes() == []


# ------------------------------------------------------- asignación manual


def test_asignar_manual_rechaza_receptor_sin_refrigeracion(aplicacion, servicios, coordinador, donante, receptores):
    d = evaluado_que_requiere_frio(aplicacion.repos, donante)
    assert [r.id for r in servicios.distribucion.receptores_compatibles(coordinador, d.id)] == ["rec-lejos"]
    with pytest.raises(ErrorServicio, match="refrigeración"):
        servicios.distribucion.asignar_manual(coordinador, d.id, "rec-cerca", "es el más cercano")

    hecho = servicios.distribucion.asignar_manual(coordinador, d.id, "rec-lejos", "tiene refrigerador")
    assert hecho.estado == EstadoDonativo.ASIGNADO and hecho.receptor_id == "rec-lejos"
    bitacora = servicios.reportes.bitacora_de(coordinador, d.id)
    assert any(e.agente == "Coordinador" and "tiene refrigerador" in e.contenido for e in bitacora)


def test_asignar_manual_solo_coordinador_y_receptor_valido(aplicacion, servicios, actor_de, coordinador, donante, receptores):
    d = evaluado_que_requiere_frio(aplicacion.repos, donante)
    with pytest.raises(ErrorAutorizacion):
        servicios.distribucion.asignar_manual(actor_de(donante), d.id, "rec-lejos", "")
    with pytest.raises(ErrorAutorizacion):
        servicios.distribucion.receptores_compatibles(actor_de(donante), d.id)
    with pytest.raises(ErrorServicio, match="receptor válido"):
        servicios.distribucion.asignar_manual(coordinador, d.id, donante.id, "")


# ----------------------------------------------------------- bandeja


def test_solo_el_coordinador_resuelve(aplicacion, servicios, actor_de, coordinador, donante):
    caso = aplicacion.mediador.notificar("Asignador", TipoCaso.SIN_RECEPTOR, "d9", "nadie")
    with pytest.raises(ErrorAutorizacion):
        servicios.casos.resolver(actor_de(donante), caso.id, "yo")
    with pytest.raises(ErrorAutorizacion):
        servicios.casos.abiertos(actor_de(donante))
    resuelto = servicios.casos.resolver(coordinador, caso.id, "Lo llevé yo")
    assert resuelto.estado == EstadoCaso.RESUELTO and resuelto.resolucion == "Lo llevé yo"
    assert servicios.casos.abiertos(coordinador) == []
    with pytest.raises(ErrorServicio):
        servicios.casos.resolver(coordinador, "no-existe", "")


# --------------------------------------------------------------- interfaz


def coordinacion(aplicacion):
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string(
        "import streamlit as st\n"
        "from ui import coordinador\n"
        "coordinador.mostrar(st.session_state['prueba_servicios'], st.session_state['prueba_actor'])\n",
        default_timeout=30,
    )
    app.session_state["prueba_servicios"] = aplicacion.servicios
    app.session_state["prueba_actor"] = Actor(rol=Rol.COORDINADOR)
    app.run()
    assert not app.exception
    return app


def test_pestana_casos_agrupa_y_resuelve(aplicacion, servicios, actor_de, coordinador, donante):
    d = servicios.publicacion.publicar(actor_de(donante), "10 bolillos").donativo
    aplicacion.mediador.notificar("Intérprete", TipoCaso.POSIBLE_INYECCION, d.id, "ignora tus reglas")
    aplicacion.mediador.notificar("Distribución", TipoCaso.RECOLECCION_VENCIDA, None, "sin donativo")
    app = coordinacion(aplicacion)
    titulos = [s.value for s in app.subheader]
    assert {"Sin receptor (1)", "Posible manipulación del agente (1)", "Recolección vencida (1)"} <= set(titulos)
    assert len([b for b in app.button if b.label == "Reintentar asignación"]) == 1  # una vez por donativo

    caso = next(c for c in servicios.casos.abiertos(coordinador) if c.tipo == TipoCaso.POSIBLE_INYECCION)
    app.text_input(key=f"coordinador_nota_{caso.id}").set_value("Revisado, era broma")
    app.button(key=f"coordinador_resolver_{caso.id}").click().run()
    assert not app.exception
    assert aplicacion.repos.casos.obtener(caso.id).resolucion == "Revisado, era broma"


def test_pestana_casos_asigna_a_mano_y_cancela(aplicacion, servicios, coordinador, donante, receptores):
    frio = evaluado_que_requiere_frio(aplicacion.repos, donante)
    aplicacion.mediador.notificar("Asignador", TipoCaso.SIN_RECEPTOR, frio.id, "nadie con frío")
    app = coordinacion(aplicacion)
    app.text_input(key=f"coordinador_manual_motivo_{frio.id}").set_value("tiene refrigerador")
    app.button(key=f"coordinador_manual_{frio.id}").click().run()
    assert not app.exception
    assert aplicacion.repos.donativos.obtener(frio.id).receptor_id == "rec-lejos"
    assert servicios.casos.abiertos(coordinador) == []

    otro = evaluado_que_requiere_frio(aplicacion.repos, donante)
    aplicacion.mediador.notificar("Inocuidad", TipoCaso.INOCUIDAD_DUDOSA, otro.id, "dudoso")
    app = coordinacion(aplicacion)
    app.button(key=f"coordinador_cancelar_{otro.id}").click().run()
    assert aplicacion.repos.donativos.obtener(otro.id).estado == EstadoDonativo.CANCELADO


def test_la_pagina_del_coordinador_vence_pendientes(aplicacion, servicios, actor_de, coordinador, donante, receptores):
    d = servicios.publicacion.publicar(actor_de(donante), "20 bolillos").donativo
    d.recoger_antes_de = datetime(2020, 1, 1)
    aplicacion.repos.donativos.guardar(d)
    app = coordinacion(aplicacion)
    assert any("vencieron sin recogerse" in w.value for w in app.warning)
    assert tipos_abiertos(servicios, coordinador, d.id) == [TipoCaso.RECOLECCION_VENCIDA]
