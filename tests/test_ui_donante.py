"""Página del donante con AppTest: aviso de no certificación, pronósticos y cancelar."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from rescate.dominio.enums import EstadoDonativo, EstadoPronostico, TipoAlimento
from rescate.dominio.modelos import Actor, Alimento, Donativo, ahora
from ui.donante import AVISO_NO_CERTIFICA


def pantalla(aplicacion, participante):
    """Ejecuta la página real del donante con los servicios y la DuckDB de la prueba."""
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string(
        "import streamlit as st\n"
        "from ui import donante\n"
        "donante.mostrar(st.session_state['prueba_servicios'], st.session_state['prueba_actor'])\n",
        default_timeout=30,
    )
    app.session_state["prueba_servicios"] = aplicacion.servicios
    app.session_state["prueba_actor"] = Actor(rol=participante.rol, participante_id=participante.id)
    app.run()
    assert not app.exception
    return app


@pytest.fixture
def con_historial(aplicacion, donante):
    """Bolillos el mismo día de la semana que hoy en las 4 semanas anteriores: hay pronóstico."""
    hoy = ahora()
    for semanas in (1, 2, 3, 4):
        aplicacion.repos.donativos.guardar(
            Donativo(
                donante_id=donante.id,
                texto_original="20 bolillos",
                alimentos=[
                    Alimento(nombre="bolillo", cantidad=20, unidad="pieza", tipo=TipoAlimento.PANADERIA, kg_estimados=1.4)
                ],
                estado=EstadoDonativo.ENTREGADO,
                creado=datetime.combine(hoy.date() - timedelta(days=7 * semanas), hoy.time()),
            )
        )
    return donante


def textos(app):
    return [c.value for c in app.caption] + [m.value for m in app.markdown]


def test_el_aviso_de_no_certificacion_se_ve(aplicacion, donante):
    app = pantalla(aplicacion, donante)
    assert any(AVISO_NO_CERTIFICA in t for t in textos(app))
    assert "NOM-251" in AVISO_NO_CERTIFICA and "no certifica" in AVISO_NO_CERTIFICA


def test_sin_historial_no_hay_pronosticos(aplicacion, donante):
    app = pantalla(aplicacion, donante)
    assert not any(b.label == "Publicar ahora" for b in app.button)


def test_publicar_ahora_crea_el_donativo_y_marca_el_pronostico(aplicacion, con_historial, receptores):
    app = pantalla(aplicacion, con_historial)
    assert any("Pronóstico para hoy" in t for t in textos(app))
    [pronostico] = aplicacion.repos.pronosticos.de_donante(con_historial.id, ahora().date())
    app.button(key=f"pronostico_publicar_{pronostico.id}").click().run()
    assert not app.exception
    donativos = aplicacion.repos.donativos.de_donante(con_historial.id)
    nuevo = next(d for d in donativos if d.estado != EstadoDonativo.ENTREGADO)
    assert nuevo.texto_original == "Me sobraron unos 1.4 kg de bolillo"
    assert nuevo.estado == EstadoDonativo.ASIGNADO
    assert aplicacion.repos.pronosticos.obtener(pronostico.id).estado == EstadoPronostico.PUBLICADO
    assert not any(b.label == "Publicar ahora" for b in app.button)  # ya no está vigente


def test_hoy_no_descarta_el_pronostico(aplicacion, con_historial, receptores):
    app = pantalla(aplicacion, con_historial)
    [pronostico] = aplicacion.repos.pronosticos.de_donante(con_historial.id, ahora().date())
    app.button(key=f"pronostico_descartar_{pronostico.id}").click().run()
    assert not app.exception
    assert aplicacion.repos.pronosticos.obtener(pronostico.id).estado == EstadoPronostico.DESCARTADO
    assert not any(b.label == "Publicar ahora" for b in app.button)
    assert all(d.estado == EstadoDonativo.ENTREGADO for d in aplicacion.repos.donativos.de_donante(con_historial.id))


def test_cancelar_desde_mis_donativos(aplicacion, donante, receptores):
    from rescate.dominio.modelos import Actor as A

    d = aplicacion.servicios.publicacion.publicar(A(rol=donante.rol, participante_id=donante.id), "20 bolillos").donativo
    app = pantalla(aplicacion, donante)
    assert any("En curso (1)" in t for t in textos(app))
    app.button(key=f"donante_cancelar_{d.id}").click().run()
    assert not app.exception
    assert aplicacion.repos.donativos.obtener(d.id).estado == EstadoDonativo.CANCELADO


def test_un_donativo_aceptado_no_ofrece_cancelar(aplicacion, donante, receptores):
    actor = Actor(rol=donante.rol, participante_id=donante.id)
    d = aplicacion.servicios.publicacion.publicar(actor, "20 bolillos").donativo
    receptor = next(r for r in receptores if r.id == d.receptor_id)
    aplicacion.servicios.distribucion.aceptar(Actor(rol=receptor.rol, participante_id=receptor.id), d.id)
    app = pantalla(aplicacion, donante)
    assert not any(b.key == f"donante_cancelar_{d.id}" for b in app.button)
