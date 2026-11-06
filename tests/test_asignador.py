"""Decisiones controladas, filtros y respaldo del asignador."""

import json
from datetime import datetime

import pytest

from rescate.agentes.asignador import AgenteAsignador
from rescate.dominio.enums import Dictamen, TipoEntradaBitacora
from rescate.dominio.modelos import (
    Alimento,
    DictamenInocuidad,
    Donativo,
    SolicitudAsignacion,
)


@pytest.fixture
def caso(servicio, donante, receptores, llm_falso):
    d = Donativo(
        donante_id=donante.id,
        texto_original="pan",
        alimentos=[
            Alimento(nombre="pan", cantidad=10, kg_estimados=2, tipo="panaderia")
        ],
    )
    agente = AgenteAsignador(
        llm_falso,
        servicio.bitacora,
        servicio.repo_participantes,
        servicio.repo_donativos,
        reloj=lambda: datetime(2026, 11, 5, 12),
    )
    return agente, SolicitudAsignacion(
        donativo=d, donante=donante, receptores=receptores
    )


def test_sin_llm_y_bitacora(caso, servicio):
    agente, solicitud = caso
    salida = agente.ejecutar(solicitud)
    assert salida.receptor_id == "rec-cerca"
    tipos = {e.tipo for e in servicio.bitacora_de(solicitud.donativo.id)}
    assert {
        TipoEntradaBitacora.ACCION,
        TipoEntradaBitacora.OBSERVACION,
        TipoEntradaBitacora.ERROR,
    } <= tipos


def test_llm_puede_elegir_segundo(caso, llm_falso):
    llm_falso.programar(
        "DecisionAsignacion",
        dict(
            razonamiento="Equidad",
            receptor_id="rec-lejos",
            justificacion="Mejor distribución",
        ),
    )
    assert caso[0].ejecutar(caso[1]).receptor_id == "rec-lejos"


def test_id_inventado_usa_respaldo(caso, llm_falso):
    llm_falso.programar(
        "DecisionAsignacion",
        dict(razonamiento="Error", receptor_id="inventado", justificacion="Error"),
    )
    assert caso[0].ejecutar(caso[1]).receptor_id == "rec-cerca"


def test_refrigeracion(caso):
    caso[1].donativo.dictamen = DictamenInocuidad(
        dictamen=Dictamen.APTO_CON_CONDICIONES,
        motivo="Frío",
        requiere_refrigeracion=True,
    )
    assert caso[0].ejecutar(caso[1]).receptor_id == "rec-lejos"


def test_descartados_y_sin_compatibles(caso):
    caso[1].donativo.receptores_descartados = ["rec-cerca"]
    assert caso[0].ejecutar(caso[1]).receptor_id == "rec-lejos"
    caso[1].donativo.receptores_descartados.append("rec-lejos")
    assert caso[0].ejecutar(caso[1]).requiere_coordinador


def test_no_apto_nunca_asigna(caso):
    caso[1].donativo.dictamen = DictamenInocuidad(
        dictamen=Dictamen.NO_APTO, motivo="No apto"
    )
    assert caso[0].ejecutar(caso[1]).receptor_id is None


def test_receptor_existente_fuera_del_top_tres_no_se_puede_elegir(caso, llm_falso):
    agente, solicitud = caso
    solicitud.receptores.extend(
        solicitud.receptores[0].model_copy(update={"id": f"rec-extra-{i}"})
        for i in range(3)
    )
    llm_falso.programar(
        "DecisionAsignacion",
        dict(
            razonamiento="Elegir uno lejano",
            receptor_id="rec-lejos",
            justificacion="Selección fuera de los tres permitidos",
        ),
    )
    salida = agente.ejecutar(solicitud)
    candidatos = json.loads(llm_falso.llamadas[-1][1])["candidatos"]
    assert len(candidatos) == 3
    assert "rec-lejos" not in {c["receptor_id"] for c in candidatos}
    assert salida.receptor_id == candidatos[0]["receptor_id"]
    assert salida.puntaje == candidatos[0]["total"]


def test_un_candidato_no_consulta_llm(caso, llm_falso):
    caso[1].receptores = caso[1].receptores[:1]
    assert caso[0].ejecutar(caso[1]).receptor_id == "rec-cerca"
    assert not llm_falso.llamadas


def test_decision_vacia_activa_respaldo(caso, llm_falso):
    llm_falso.programar(
        "DecisionAsignacion",
        dict(razonamiento=" ", receptor_id="rec-lejos", justificacion=" "),
    )
    assert caso[0].ejecutar(caso[1]).receptor_id == "rec-cerca"


def test_bitacora_del_asignador_ordena_y_conserva_calculos(caso, servicio):
    caso[0].ejecutar(caso[1])
    entradas = servicio.bitacora_de(caso[1].donativo.id)
    assert [e.paso for e in entradas] == list(range(1, len(entradas) + 1))
    observaciones = [e for e in entradas if "candidatos" in e.datos]
    assert len(observaciones) == 1
    assert set(observaciones[0].datos["candidatos"][0]["desglose"]) == {
        "distancia",
        "capacidad",
        "horario",
        "equidad",
    }


def _pantalla(servicio, pagina, participante=None):
    """Ejecuta una página real con la fachada y DuckDB de la prueba."""
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string(
        "import streamlit as st\n"
        "from ui import receptor, recolector, coordinador\n"
        "paginas = {'receptor': receptor, 'recolector': recolector,\n"
        "           'coordinador': coordinador}\n"
        "paginas[st.session_state['prueba_pagina']].mostrar(\n"
        "    st.session_state['prueba_servicio'],\n"
        "    st.session_state['prueba_participante'])\n",
        default_timeout=30,
    )
    app.session_state["prueba_servicio"] = servicio
    app.session_state["prueba_pagina"] = pagina
    app.session_state["prueba_participante"] = participante
    app.run()
    assert not app.exception
    return app


def _campo(app, tipo, etiqueta):
    return next(c for c in getattr(app, tipo) if c.label == etiqueta)


def test_pantallas_rechazar_aceptar_recoger_entregar_y_metricas(
    servicio, donante, receptores, recolector
):
    from rescate.dominio.enums import EstadoDonativo

    donativo = servicio.publicar(
        "Me sobraron 15 bolillos y 5 kg de jitomate", donante.id
    ).donativo
    primero = donativo.receptor_id
    receptor = _pantalla(servicio, "receptor", servicio.participante(primero))
    receptor.button(key=f"receptor_rechazar_{donativo.id}").click().run()
    assert receptor.error and servicio.donativo(donativo.id).receptor_id == primero
    receptor.text_input(key=f"receptor_motivo_{donativo.id}").set_value(
        "Sin espacio"
    ).run()
    receptor.button(key=f"receptor_rechazar_{donativo.id}").click().run()
    assert not receptor.exception
    donativo = servicio.donativo(donativo.id)
    assert donativo.receptor_id != primero
    assert primero in donativo.receptores_descartados
    assert any("Se reasignó" in s.value for s in receptor.success)
    receptor = _pantalla(
        servicio, "receptor", servicio.participante(donativo.receptor_id)
    )
    receptor.button(key=f"receptor_aceptar_{donativo.id}").click().run()
    assert not receptor.exception
    assert servicio.donativo(donativo.id).asignacion.aceptada
    voluntario = _pantalla(servicio, "recolector", recolector)
    voluntario.button(key=f"recolector_recoger_{donativo.id}").click().run()
    assert not voluntario.exception
    assert servicio.donativo(donativo.id).estado == EstadoDonativo.EN_RECOLECCION
    voluntario.button(key=f"recolector_entregar_{donativo.id}").click().run()
    assert not voluntario.exception
    assert servicio.donativo(donativo.id).estado == EstadoDonativo.ENTREGADO
    rechazado = servicio.publicar(
        "Me sobraron 2 kg de arroz con moho", donante.id
    ).donativo
    assert rechazado.estado == EstadoDonativo.RECHAZADO and not rechazado.receptor_id
    assert not any(e.agente == "Asignador" for e in servicio.bitacora_de(rechazado.id))
    coordinador = _pantalla(servicio, "coordinador")
    assert (
        float(_campo(coordinador, "metric", "Kg entregados").value)
        == donativo.kg_totales
    )
    assert _campo(coordinador, "metric", "No aptos").value == "1"
    assert _campo(coordinador, "metric", "Donativos activos").value == "0"
    eventos = [h["evento"] for h in servicio.historial(donativo.id)]
    assert eventos == [
        "publicar",
        "evaluar_apto",
        "asignar",
        "liberar",
        "asignar",
        "aceptar",
        "iniciar_recoleccion",
        "entregar",
    ]
    assert any("entregar" in c.value for c in coordinador.caption)


@pytest.mark.parametrize("rol", ["donante", "receptor", "recolector"])
def test_coordinador_alta_y_eliminacion_confirmada(servicio, rol):
    from rescate.dominio.enums import Rol

    app = _pantalla(servicio, "coordinador")
    app.selectbox(key="coordinador_rol").select(Rol(rol)).run()
    _campo(app, "text_input", "Nombre").set_value(f"Prueba {rol}")
    _campo(app, "text_input", "Dirección").set_value("Centro de Guadalajara")
    _campo(app, "button", "Registrar participante").click().run()
    assert not app.exception
    assert len(servicio.participantes()) == 1
    persona = servicio.participantes()[0]
    assert persona.rol == Rol(rol) and persona.nombre == f"Prueba {rol}"
    assert app.button(key="coordinador_eliminar").disabled
    app.checkbox(key="coordinador_confirmar").check().run()
    app.button(key="coordinador_eliminar").click().run()
    assert not app.exception and not servicio.participantes()


def test_coordinador_nombre_obligatorio(servicio):
    app = _pantalla(servicio, "coordinador")
    _campo(app, "text_input", "Nombre").set_value("   ")
    _campo(app, "button", "Registrar participante").click().run()
    assert not app.exception and app.error
    assert not servicio.participantes()


def test_receptor_guarda_perfil(servicio, receptores):
    app = _pantalla(servicio, "receptor", receptores[0])
    _campo(app, "number_input", "Capacidad kg/día").set_value(75.0)
    _campo(app, "checkbox", "Tiene refrigeración").check()
    _campo(app, "text_input", "Dirección").set_value("Nueva dirección ficticia")
    _campo(app, "button", "Guardar perfil").click().run()
    assert not app.exception
    guardado = servicio.participante(receptores[0].id)
    assert guardado.capacidad_kg_dia == 75 and guardado.tiene_refrigeracion
    assert guardado.ubicacion.direccion == "Nueva dirección ficticia"


def test_coordinador_reintenta_despues_del_alta(servicio, donante):
    from rescate.dominio.modelos import Receptor

    donativo = servicio.publicar("Me sobraron 10 bolillos", donante.id).donativo
    app = _pantalla(servicio, "coordinador")
    assert _campo(app, "metric", "Sin receptor").value == "1"
    servicio.registrar_participante(
        Receptor(nombre="Nuevo comedor", ubicacion=donante.ubicacion)
    )
    app.button(key=f"coordinador_reintentar_{donativo.id}").click().run()
    assert not app.exception and servicio.donativo(donativo.id).receptor_id
    assert _campo(app, "metric", "Sin receptor").value == "0"


def test_recolector_no_toma_donativo_vencido(servicio, donante, receptores, recolector):
    from datetime import timedelta

    from rescate.dominio.modelos import ahora

    d = servicio.publicar("Me sobraron 10 bolillos", donante.id).donativo
    servicio.aceptar_asignacion(d.id, d.receptor_id)
    d = servicio.donativo(d.id)
    d.recoger_antes_de = ahora() - timedelta(seconds=1)
    servicio.repo_donativos.guardar(d)
    app = _pantalla(servicio, "recolector", recolector)
    assert app.button(key=f"recolector_recoger_{d.id}").disabled


def test_recolector_no_disponible_no_toma_donativo(
    servicio, donante, receptores, recolector
):
    d = servicio.publicar("Me sobraron 10 bolillos", donante.id).donativo
    servicio.aceptar_asignacion(d.id, d.receptor_id)
    recolector.disponible = False
    servicio.registrar_participante(recolector)
    app = _pantalla(servicio, "recolector", recolector)
    assert app.button(key=f"recolector_recoger_{d.id}").disabled


def test_coordinador_conserva_participantes_del_historial(
    servicio, donante, receptores, recolector
):
    d = servicio.publicar("Me sobraron 10 bolillos", donante.id).donativo
    primero = d.receptor_id
    servicio.rechazar_asignacion(d.id, primero, "Sin espacio")
    app = _pantalla(servicio, "coordinador")
    app.selectbox(key="coordinador_eliminar_id").select(
        servicio.participante(primero)
    ).run()
    app.checkbox(key="coordinador_confirmar").check().run()
    assert app.button(key="coordinador_eliminar").disabled


def test_coordinador_filtra_bitacora(servicio, donante, receptores):
    d = servicio.publicar("Me sobraron 10 bolillos", donante.id).donativo
    app = _pantalla(servicio, "coordinador")
    app.selectbox(key="coordinador_agente").select("Asignador").run()
    app.text_input(key="coordinador_donativo").set_value(d.id).run()
    entradas = app.tabs[4].markdown
    assert entradas and all("**Asignador**" in e.value for e in entradas)
    app.text_input(key="coordinador_donativo").set_value("no-existe").run()
    assert not app.tabs[4].markdown


def test_app_con_los_cuatro_roles(tmp_path, monkeypatch):
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from rescate.dominio.enums import Rol

    monkeypatch.setenv("USAR_LLM_FALSO", "1")
    monkeypatch.setenv("RUTA_DB", str(tmp_path / "app.duckdb"))
    app = AppTest.from_file(
        str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30
    ).run()
    assert not app.exception
    assert len(app.sidebar.selectbox[0].options) == 7
    for rol, encabezado in [
        (Rol.RECEPTOR, "Donativos para mi organización"),
        (Rol.RECOLECTOR, "Recolecciones"),
        (Rol.COORDINADOR, "Coordinación"),
    ]:
        app.sidebar.radio[0].set_value(rol).run()
        assert not app.exception
        assert app.header[0].value == encabezado
