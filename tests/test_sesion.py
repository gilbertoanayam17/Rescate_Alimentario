"""Inicio de sesión con PIN, bloqueo por intentos y su configuración."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from rescate.config import cargar_configuracion
from rescate.dominio.enums import Rol
from rescate.dominio.modelos import Actor, Donante, Ubicacion
from rescate.servicios import ErrorAutorizacion, ErrorServicio
from rescate.servicios.participantes import (
    ServicioParticipantes,
    hashear_pin,
    validar_formato_pin,
    verificar_pin,
)

CENTRO = Ubicacion(lat=20.6741, lon=-103.3404)

# ------------------------------------------------------------- configuración


def test_los_pin_salen_de_la_configuracion(monkeypatch):
    monkeypatch.setenv("PIN_DEMO", " 4321 ")
    monkeypatch.setenv("PIN_COORDINADOR", "9999")
    config = cargar_configuracion()
    assert (config.pin_demo, config.pin_coordinador) == ("4321", "9999")


def test_pin_por_defecto(monkeypatch):
    monkeypatch.delenv("PIN_DEMO", raising=False)
    monkeypatch.delenv("PIN_COORDINADOR", raising=False)
    config = cargar_configuracion()
    assert (config.pin_demo, config.pin_coordinador) == ("1234", "0000")


# ---------------------------------------------------------------------- hash


def test_hash_pbkdf2_con_sal():
    primero, segundo = hashear_pin("2468"), hashear_pin("2468")
    assert primero != segundo  # sal aleatoria
    esquema, iteraciones, sal, valor = primero.split("$")
    assert (esquema, iteraciones, len(sal)) == ("pbkdf2", "100000", 32) and "2468" not in (sal, valor)
    assert verificar_pin("2468", primero) and verificar_pin("2468", segundo)
    assert not verificar_pin("2469", primero)
    assert not verificar_pin("2468", "texto-raro") and not verificar_pin("2468", "md5$1$aa$bb")


def test_formato_del_pin():
    assert validar_formato_pin(" 1234 ") == "1234"
    for malo in ("", "123", "123456789", "12a4"):
        with pytest.raises(ErrorServicio):
            validar_formato_pin(malo)


# ------------------------------------------------------------------- sesión


@pytest.fixture
def con_pin(servicios, coordinador):
    d = Donante(id="don-pin", nombre="Fonda con PIN", ubicacion=CENTRO)
    servicios.participantes.registrar(coordinador, d, pin="2468")
    return d


def test_pin_correcto_e_incorrecto(servicios, con_pin):
    actor = servicios.participantes.iniciar_sesion(con_pin.id, "2468")
    assert actor == Actor(rol=Rol.DONANTE, participante_id=con_pin.id)
    with pytest.raises(ErrorAutorizacion, match="PIN incorrecto"):
        servicios.participantes.iniciar_sesion(con_pin.id, "1111")
    with pytest.raises(ErrorAutorizacion, match="No existe"):
        servicios.participantes.iniciar_sesion("nadie", "2468")


def test_pin_del_coordinador(servicios):
    assert servicios.participantes.sesion_coordinador("0000") == Actor(rol=Rol.COORDINADOR)
    with pytest.raises(ErrorAutorizacion):
        servicios.participantes.sesion_coordinador("1234")
    with pytest.raises(ErrorAutorizacion):
        servicios.participantes.sesion_coordinador("")


def test_bloqueo_tras_cinco_fallos(repos):
    momento = {"ahora": datetime(2026, 11, 23, 12, 0)}
    servicio = ServicioParticipantes(
        repos.participantes, repos.donativos, reloj=lambda: momento["ahora"]
    )
    servicio.registrar(
        Actor(rol=Rol.COORDINADOR), Donante(id="don-b", nombre="Fonda", ubicacion=CENTRO), pin="2468"
    )
    for _ in range(5):
        with pytest.raises(ErrorAutorizacion, match="PIN incorrecto"):
            servicio.iniciar_sesion("don-b", "0000")
    with pytest.raises(ErrorAutorizacion, match="Demasiados intentos"):
        servicio.iniciar_sesion("don-b", "2468")  # bloqueado aunque el PIN sea correcto
    momento["ahora"] += timedelta(seconds=61)
    assert servicio.iniciar_sesion("don-b", "2468").participante_id == "don-b"


def test_los_fallos_viejos_no_cuentan(repos):
    momento = {"ahora": datetime(2026, 11, 23, 12, 0)}
    servicio = ServicioParticipantes(
        repos.participantes, repos.donativos, reloj=lambda: momento["ahora"]
    )
    for _ in range(4):
        with pytest.raises(ErrorAutorizacion):
            servicio.sesion_coordinador("9")
    momento["ahora"] += timedelta(minutes=6)
    with pytest.raises(ErrorAutorizacion, match="PIN incorrecto"):
        servicio.sesion_coordinador("9")  # quinto fallo, pero los anteriores ya vencieron
    assert servicio.sesion_coordinador("0000").rol == Rol.COORDINADOR


def test_sin_pin_no_se_entra_ni_con_el_pin_demo(servicios, repos, donante):
    assert donante.pin_hash == ""
    for pin in ("1234", "0000", ""):
        with pytest.raises(ErrorAutorizacion, match="no tiene PIN; pídelo al coordinador"):
            servicios.participantes.iniciar_sesion(donante.id, pin)
    assert repos.participantes.obtener(donante.id).pin_hash == ""  # nadie le asigna uno al vuelo


def test_el_coordinador_le_asigna_pin_a_un_participante_existente(servicios, coordinador, repos, donante):
    servicios.participantes.registrar(coordinador, repos.participantes.obtener(donante.id), pin="8642")
    assert servicios.participantes.iniciar_sesion(donante.id, "8642").participante_id == donante.id


def test_cargar_semilla_asigna_el_pin_demo(tmp_path, monkeypatch):
    import sys

    from rescate.persistencia.db import conectar
    from rescate.persistencia.repositorios import ParticipantesDuckDB
    from scripts import cargar_semilla

    monkeypatch.setenv("RUTA_DB", str(tmp_path / "semilla.duckdb"))
    monkeypatch.setenv("PIN_DEMO", "5678")
    monkeypatch.setattr(sys, "argv", ["cargar_semilla.py"])
    cargar_semilla.main()
    con = conectar(tmp_path / "semilla.duckdb")
    personas = ParticipantesDuckDB(con).listar()
    con.close()
    assert len(personas) == 15 and all(verificar_pin("5678", p.pin_hash) for p in personas)


def test_asignar_pin_faltante(servicios, repos, donante, con_pin):
    hash_previo = repos.participantes.obtener(con_pin.id).pin_hash
    assert servicios.participantes.asignar_pin_faltante("1357") == 1
    assert verificar_pin("1357", repos.participantes.obtener(donante.id).pin_hash)
    assert repos.participantes.obtener(con_pin.id).pin_hash == hash_previo


def test_editar_el_perfil_conserva_el_pin(servicios, repos, actor_de, coordinador, con_pin):
    guardado = repos.participantes.obtener(con_pin.id)
    servicios.participantes.registrar(
        actor_de(con_pin),
        guardado.model_copy(update={"nombre": "Nuevo nombre", "pin_hash": "pbkdf2$1$00$00"}),
    )
    servicios.participantes.registrar(coordinador, guardado.model_copy(update={"pin_hash": ""}))
    assert verificar_pin("2468", repos.participantes.obtener(con_pin.id).pin_hash)
    with pytest.raises(ErrorServicio, match="4 a 8"):
        servicios.participantes.registrar(coordinador, guardado, pin="12")


def test_el_pin_nunca_queda_en_claro(aplicacion, servicios, actor_de, con_pin, receptores):
    servicios.publicacion.publicar(actor_de(con_pin), "20 bolillos")
    datos = aplicacion.repos.participantes._con.execute("SELECT datos FROM participantes").fetchall()
    assert not any('"2468"' in fila[0] for fila in datos)
    for entrada in aplicacion.bitacora.recientes(500):
        assert "pbkdf2$" not in entrada.contenido and "pin_hash" not in str(entrada.datos)


# ---------------------------------------------------------------- interfaz

ENTRADA = (
    "import streamlit as st\n"
    "from ui.sesion import actor_de_sesion, barra_sesion, pantalla_entrada\n"
    "servicios = st.session_state['prueba_servicios']\n"
    "actor = actor_de_sesion()\n"
    "if actor is None:\n"
    "    pantalla_entrada(servicios)\n"
    "else:\n"
    "    st.header(f'Dentro como {actor.rol.value}')\n"
    "    barra_sesion(servicios, actor)\n"
)


def entrada(servicios):
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string(ENTRADA, default_timeout=30)
    app.session_state["prueba_servicios"] = servicios
    return app.run()


def test_entrada_con_pin_incorrecto_y_correcto(servicios, con_pin):
    app = entrada(servicios)
    assert not app.header and app.expander[0].label == "Aviso de privacidad"
    app.selectbox(key="sesion_participante").select(con_pin.id)
    app.text_input(key="sesion_pin").input("1111")
    next(b for b in app.button if b.label == "Entrar").click().run()
    assert not app.exception and app.error[0].value == "PIN incorrecto." and not app.header
    app.text_input(key="sesion_pin").input("2468")
    next(b for b in app.button if b.label == "Entrar").click().run()
    assert app.header[0].value == "Dentro como donante"
    assert any("Fonda con PIN" in m.value for m in app.markdown)
    app.button(key="sesion_salir").click().run()
    assert not app.header and "sesion_actor" not in app.session_state


def test_entrada_del_coordinador(servicios):
    from rescate.dominio.enums import Rol as R

    app = entrada(servicios)
    app.radio(key="sesion_rol").set_value(R.COORDINADOR).run()
    app.text_input(key="sesion_pin").input("0000")
    next(b for b in app.button if b.label == "Entrar").click().run()
    assert app.header[0].value == "Dentro como coordinador"


def test_sin_participantes_del_rol(servicios):
    app = entrada(servicios)  # base vacía
    assert any("No hay participantes" in w.value for w in app.warning)
    assert any("¿No tienes cuenta o olvidaste tu PIN?" in m.value for m in app.markdown)


def test_la_entrada_explica_como_pedir_el_alta(servicios, con_pin):
    from dataclasses import replace

    from rescate.dominio.enums import Rol as R

    servicios = replace(servicios, correo_coordinacion="alta@red.example", telefono_coordinacion="33 1234 5678")
    app = entrada(servicios)
    textos = " ".join(m.value for m in app.markdown)
    assert "donante (comercio)" in textos and "hora de cierre" in textos
    assert "mailto:alta@red.example?subject=Alta%20en%20Rescate%20Alimentario" in textos
    assert "tel:3312345678" in textos
    app.radio(key="sesion_rol").set_value(R.RECOLECTOR).run()
    assert "transporte" in " ".join(m.value for m in app.markdown)
    app.radio(key="sesion_rol").set_value(R.COORDINADOR).run()
    assert not any("¿No tienes cuenta" in m.value for m in app.markdown)


def test_sin_contacto_configurado_se_indica_a_quien_pedirlo(servicios, con_pin):
    from dataclasses import replace

    app = entrada(replace(servicios, correo_coordinacion="", telefono_coordinacion=""))
    assert any("organización que opera la red" in m.value for m in app.markdown)


def test_el_contacto_sale_de_la_configuracion(monkeypatch):
    monkeypatch.setenv("CORREO_COORDINACION", " alta@red.example ")
    monkeypatch.setenv("TELEFONO_COORDINACION", "33 1234 5678")
    config = cargar_configuracion()
    assert (config.correo_coordinacion, config.telefono_coordinacion) == ("alta@red.example", "33 1234 5678")


def test_coordinador_asigna_pin_desde_la_pagina(aplicacion, servicios, donante):
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string(
        "import streamlit as st\n"
        "from ui import coordinador\n"
        "coordinador.mostrar(st.session_state['prueba_servicios'], st.session_state['prueba_actor'])\n",
        default_timeout=30,
    )
    app.session_state["prueba_servicios"] = servicios
    app.session_state["prueba_actor"] = Actor(rol=Rol.COORDINADOR)
    app.run()
    app.text_input(key="coordinador_pin_nuevo").input("12")
    next(b for b in app.button if b.label == "Asignar PIN").click().run()
    assert any("4 a 8" in e.value for e in app.error)
    app.text_input(key="coordinador_pin_nuevo").input("9753")
    next(b for b in app.button if b.label == "Asignar PIN").click().run()
    assert not app.exception
    assert servicios.participantes.iniciar_sesion(donante.id, "9753").participante_id == donante.id
