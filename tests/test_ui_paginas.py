"""Páginas de receptor, recolector y coordinador, y el panel de avisos, con AppTest."""
from __future__ import annotations

from rescate.dominio.enums import TipoAlimento
from rescate.dominio.modelos import Actor, Pronostico, ahora

PAGINA = (
    "import streamlit as st\n"
    "from ui import {modulo}\n"
    "{modulo}.mostrar(st.session_state['prueba_servicios'], st.session_state['prueba_actor'])\n"
)
PANEL = (
    "import streamlit as st\n"
    "from ui.comun import panel_avisos\n"
    "panel_avisos(st.session_state['prueba_servicios'], st.session_state['prueba_actor'])\n"
)


def correr(servicios, actor: Actor | None, codigo: str):
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string(codigo, default_timeout=30)
    app.session_state["prueba_servicios"] = servicios
    app.session_state["prueba_actor"] = actor
    app.run()
    assert not app.exception
    return app


def pagina(servicios, actor, modulo: str):
    return correr(servicios, actor, PAGINA.format(modulo=modulo))


def textos(app) -> list[str]:
    return [c.value for c in app.caption] + [m.value for m in app.markdown] + [i.value for i in app.info]


def pronostico_para(donante, receptor) -> Pronostico:
    return Pronostico(
        donante_id=donante.id,
        fecha=ahora().date(),
        tipo=TipoAlimento.PANADERIA,
        descripcion="pan dulce y bolillo",
        kg_esperados=2.5,
        confianza=0.8,
        mensaje="Los martes te suele sobrar pan.",
        receptor_sugerido_id=receptor.id,
    )


def test_panel_de_avisos_muestra_y_marca_como_leido(servicios, actor_de, donante, receptores):
    servicios.publicacion.publicar(actor_de(donante), "20 bolillos")
    app = correr(servicios, actor_de(donante), PANEL)
    assert app.expander[0].label == "🔔 Avisos (1)"
    app.button[0].click().run()
    assert app.expander[0].label == "🔔 Avisos (0)"
    assert servicios.notificaciones.no_leidos(actor_de(donante)) == 0


def test_panel_de_avisos_sin_sesion_o_vacio(servicios, actor_de, donante):
    assert not correr(servicios, None, PANEL).expander
    app = correr(servicios, actor_de(donante), PANEL)
    assert "Sin avisos por ahora." in textos(app)


def test_receptor_ve_sus_posibles_donativos(aplicacion, servicios, actor_de, donante, receptores):
    aplicacion.repos.pronosticos.guardar(pronostico_para(donante, receptores[0]))
    app = pagina(servicios, actor_de(receptores[0]), "receptor")
    assert "Los martes te suele sobrar pan." in [m.value for m in app.markdown]
    otro = pagina(servicios, actor_de(receptores[1]), "receptor")
    assert "Por ahora no hay posibles donativos para tu organización." in textos(otro)


def test_coordinador_genera_los_pronosticos_del_dia(aplicacion, servicios, coordinador, donante, receptores):
    app = pagina(servicios, coordinador, "coordinador")
    assert "Pulsa el botón para calcular los pronósticos del día." in textos(app)
    boton = next(b for b in app.button if b.label == "Generar pronósticos de hoy")
    boton.click().run()
    assert "Hoy no hay pronósticos: ningún comercio tiene un patrón para este día." in textos(app)

    aplicacion.repos.pronosticos.guardar(pronostico_para(donante, receptores[0]))
    next(b for b in app.button if b.label == "Generar pronósticos de hoy").click().run()
    assert any(f"pre-reservado para {receptores[0].nombre}" in t for t in textos(app))
