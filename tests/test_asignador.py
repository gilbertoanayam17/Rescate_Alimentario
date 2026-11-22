"""Decisiones controladas, filtros y respaldo del asignador."""

import json
from datetime import datetime

import pytest

from rescate.agentes.asignador import AgenteAsignador
from rescate.dominio.enums import Dictamen, Rol, TipoEntradaBitacora
from rescate.dominio.modelos import (
    Actor,
    Alimento,
    DictamenInocuidad,
    Donativo,
    SolicitudAsignacion,
)


@pytest.fixture
def caso(aplicacion, donante, receptores, llm_falso):
    d = Donativo(
        donante_id=donante.id,
        texto_original="pan",
        alimentos=[
            Alimento(nombre="pan", cantidad=10, kg_estimados=2, tipo="panaderia")
        ],
    )
    agente = AgenteAsignador(
        llm_falso,
        aplicacion.bitacora,
        aplicacion.repos.participantes,
        aplicacion.repos.donativos,
        reloj=lambda: datetime(2026, 11, 5, 12),
    )
    return agente, SolicitudAsignacion(
        donativo=d, donante=donante, receptores=receptores
    )


def test_sin_llm_y_bitacora(caso, aplicacion):
    agente, solicitud = caso
    salida = agente.ejecutar(solicitud)
    assert salida.receptor_id == "rec-cerca"
    tipos = {e.tipo for e in aplicacion.bitacora.de_donativo(solicitud.donativo.id)}
    assert {
        TipoEntradaBitacora.ACCION,
        TipoEntradaBitacora.OBSERVACION,
        TipoEntradaBitacora.ERROR,
    } <= tipos


def test_llm_puede_elegir_segundo(caso, llm_falso):
    # rec-cerca sigue primero, pero rec-lejos tiene más capacidad: razón válida
    caso[1].receptores[0] = (
        caso[1].receptores[0].model_copy(update={"capacidad_kg_dia": 1})
    )
    llm_falso.programar(
        "DecisionAsignacion",
        dict(
            razonamiento="Le cabe todo el donativo",
            receptor_id="rec-lejos",
            justificacion="Mejor capacidad",
        ),
    )
    assert caso[0].ejecutar(caso[1]).receptor_id == "rec-lejos"
    assert (
        json.loads(llm_falso.llamadas[-1][1])["candidatos"][0]["receptor_id"]
        == "rec-cerca"
    )


def test_llm_no_puede_elegir_segundo_sin_ventaja(caso, llm_falso, aplicacion):
    # Empatados salvo la distancia: preferir al lejano no tiene sustento
    llm_falso.programar(
        "DecisionAsignacion",
        dict(
            razonamiento="Es el más cercano",
            receptor_id="rec-lejos",
            justificacion="Por ser el más cercano",
        ),
    )
    salida = caso[0].ejecutar(caso[1])
    assert salida.receptor_id == "rec-cerca"
    errores = [
        e.contenido
        for e in aplicacion.bitacora.de_donativo(caso[1].donativo.id)
        if e.tipo == TipoEntradaBitacora.ERROR
    ]
    assert any("no supera" in e for e in errores)


def test_descartados_se_explican_con_nombres_y_en_espanol(caso, aplicacion):
    caso[1].donativo.alimentos.append(
        Alimento(nombre="leche", cantidad=1, kg_estimados=1, tipo="lacteo")
    )
    caso[0].ejecutar(caso[1])
    observacion = next(
        e.contenido
        for e in aplicacion.bitacora.de_donativo(caso[1].donativo.id)
        if e.contenido.startswith("1 compatibles")
    )
    assert "Comedor Cerca (no acepta lácteos)" in observacion
    assert "{" not in observacion


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


def test_bitacora_del_asignador_ordena_y_conserva_calculos(caso, aplicacion):
    caso[0].ejecutar(caso[1])
    entradas = aplicacion.bitacora.de_donativo(caso[1].donativo.id)
    assert [e.paso for e in entradas] == list(range(1, len(entradas) + 1))
    observaciones = [e for e in entradas if "candidatos" in e.datos]
    assert len(observaciones) == 1
    assert set(observaciones[0].datos["candidatos"][0]["desglose"]) == {
        "distancia",
        "capacidad",
        "horario",
        "equidad",
    }


def _como(participante):
    return Actor(rol=participante.rol, participante_id=participante.id)


def _publicar(aplicacion, donante, texto):
    return aplicacion.servicios.publicacion.publicar(_como(donante), texto).donativo


def _pantalla(aplicacion, pagina, participante=None):
    """Ejecuta una página real con los servicios y DuckDB de la prueba."""
    from streamlit.testing.v1 import AppTest

    app = AppTest.from_string(
        "import streamlit as st\n"
        "from ui import receptor, recolector, coordinador\n"
        "paginas = {'receptor': receptor, 'recolector': recolector,\n"
        "           'coordinador': coordinador}\n"
        "paginas[st.session_state['prueba_pagina']].mostrar(\n"
        "    st.session_state['prueba_servicios'],\n"
        "    st.session_state['prueba_actor'])\n",
        default_timeout=30,
    )
    app.session_state["prueba_servicios"] = aplicacion.servicios
    app.session_state["prueba_pagina"] = pagina
    app.session_state["prueba_actor"] = (
        _como(participante) if participante else Actor(rol=Rol.COORDINADOR)
    )
    app.run()
    assert not app.exception
    return app


def _campo(app, tipo, etiqueta):
    return next(c for c in getattr(app, tipo) if c.label == etiqueta)


def test_pantallas_rechazar_aceptar_recoger_entregar_y_metricas(
    aplicacion, donante, receptores, recolector
):
    from rescate.dominio.enums import EstadoDonativo

    donativo = _publicar(
        aplicacion, donante, "Me sobraron 15 bolillos y 5 kg de jitomate"
    )
    primero = donativo.receptor_id
    receptor = _pantalla(
        aplicacion, "receptor", aplicacion.repos.participantes.obtener(primero)
    )
    receptor.button(key=f"receptor_rechazar_{donativo.id}").click().run()
    assert (
        receptor.error
        and aplicacion.repos.donativos.obtener(donativo.id).receptor_id == primero
    )
    receptor.text_input(key=f"receptor_motivo_{donativo.id}").set_value(
        "Sin espacio"
    ).run()
    receptor.button(key=f"receptor_rechazar_{donativo.id}").click().run()
    assert not receptor.exception
    donativo = aplicacion.repos.donativos.obtener(donativo.id)
    assert donativo.receptor_id != primero
    assert primero in donativo.receptores_descartados
    assert any("Se reasignó" in s.value for s in receptor.success)
    receptor = _pantalla(
        aplicacion,
        "receptor",
        aplicacion.repos.participantes.obtener(donativo.receptor_id),
    )
    receptor.button(key=f"receptor_aceptar_{donativo.id}").click().run()
    assert not receptor.exception
    assert aplicacion.repos.donativos.obtener(donativo.id).asignacion.aceptada
    voluntario = _pantalla(aplicacion, "recolector", recolector)
    voluntario.button(key=f"recolector_recoger_{donativo.id}").click().run()
    assert not voluntario.exception
    assert (
        aplicacion.repos.donativos.obtener(donativo.id).estado
        == EstadoDonativo.EN_RECOLECCION
    )
    voluntario.button(key=f"recolector_entregar_{donativo.id}").click().run()
    assert not voluntario.exception
    assert (
        aplicacion.repos.donativos.obtener(donativo.id).estado
        == EstadoDonativo.ENTREGADO
    )
    rechazado = _publicar(aplicacion, donante, "Me sobraron 2 kg de arroz con moho")
    assert rechazado.estado == EstadoDonativo.RECHAZADO and not rechazado.receptor_id
    assert not any(
        e.agente == "Asignador" for e in aplicacion.bitacora.de_donativo(rechazado.id)
    )
    coordinador = _pantalla(aplicacion, "coordinador")
    assert (
        float(_campo(coordinador, "metric", "Kg entregados").value)
        == donativo.kg_totales
    )
    assert _campo(coordinador, "metric", "No aptos").value == "1"
    assert _campo(coordinador, "metric", "Donativos activos").value == "0"
    eventos = [h["evento"] for h in aplicacion.repos.donativos.historial(donativo.id)]
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
def test_coordinador_alta_y_eliminacion_confirmada(aplicacion, rol):
    from rescate.dominio.enums import Rol

    app = _pantalla(aplicacion, "coordinador")
    app.selectbox(key="coordinador_rol").select(Rol(rol)).run()
    _campo(app, "text_input", "Nombre").set_value(f"Prueba {rol}")
    _campo(app, "text_input", "Dirección").set_value("Centro de Guadalajara")
    _campo(app, "text_input", "PIN de acceso (4 a 8 dígitos)").set_value("4321")
    _campo(app, "button", "Registrar participante").click().run()
    assert not app.exception
    assert len(aplicacion.servicios.participantes.listar()) == 1
    persona = aplicacion.servicios.participantes.listar()[0]
    assert persona.rol == Rol(rol) and persona.nombre == f"Prueba {rol}"
    assert persona.pin_hash.startswith("pbkdf2$") and "4321" not in persona.pin_hash
    assert app.button(key="coordinador_eliminar").disabled
    app.checkbox(key="coordinador_confirmar").check().run()
    app.button(key="coordinador_eliminar").click().run()
    assert not app.exception and not aplicacion.servicios.participantes.listar()


def test_coordinador_nombre_obligatorio(aplicacion):
    app = _pantalla(aplicacion, "coordinador")
    _campo(app, "text_input", "Nombre").set_value("   ")
    _campo(app, "button", "Registrar participante").click().run()
    assert not app.exception and app.error
    assert not aplicacion.servicios.participantes.listar()


def test_receptor_guarda_perfil(aplicacion, receptores):
    app = _pantalla(aplicacion, "receptor", receptores[0])
    _campo(app, "number_input", "Capacidad kg/día").set_value(75.0)
    _campo(app, "checkbox", "Tiene refrigeración").check()
    _campo(app, "text_input", "Dirección").set_value("Nueva dirección ficticia")
    _campo(app, "button", "Guardar perfil").click().run()
    assert not app.exception
    guardado = aplicacion.repos.participantes.obtener(receptores[0].id)
    assert guardado.capacidad_kg_dia == 75 and guardado.tiene_refrigeracion
    assert guardado.ubicacion.direccion == "Nueva dirección ficticia"


def test_coordinador_reintenta_despues_del_alta(aplicacion, donante):
    from rescate.dominio.modelos import Receptor

    donativo = _publicar(aplicacion, donante, "Me sobraron 10 bolillos")
    app = _pantalla(aplicacion, "coordinador")
    assert _campo(app, "metric", "Sin receptor").value == "1"
    aplicacion.servicios.participantes.registrar(
        Actor(rol=Rol.COORDINADOR),
        Receptor(nombre="Nuevo comedor", ubicacion=donante.ubicacion),
    )
    app.button(key=f"coordinador_reintentar_{donativo.id}").click().run()
    assert (
        not app.exception
        and aplicacion.repos.donativos.obtener(donativo.id).receptor_id
    )
    assert _campo(app, "metric", "Sin receptor").value == "0"


def test_recolector_no_toma_donativo_vencido(
    aplicacion, donante, receptores, recolector
):
    from datetime import timedelta

    from rescate.dominio.modelos import ahora

    d = _publicar(aplicacion, donante, "Me sobraron 10 bolillos")
    aplicacion.servicios.distribucion.aceptar(
        Actor(rol=Rol.RECEPTOR, participante_id=d.receptor_id), d.id
    )
    d = aplicacion.repos.donativos.obtener(d.id)
    d.recoger_antes_de = ahora() - timedelta(seconds=1)
    aplicacion.repos.donativos.guardar(d)
    app = _pantalla(aplicacion, "recolector", recolector)
    # Al abrir la página se vence: ya no se ofrece y pasa a la bandeja del coordinador.
    assert not [b for b in app.button if b.key == f"recolector_recoger_{d.id}"]
    assert aplicacion.repos.donativos.obtener(d.id).estado.value == "expirado"


def test_recolector_no_disponible_no_toma_donativo(
    aplicacion, donante, receptores, recolector
):
    d = _publicar(aplicacion, donante, "Me sobraron 10 bolillos")
    aplicacion.servicios.distribucion.aceptar(
        Actor(rol=Rol.RECEPTOR, participante_id=d.receptor_id), d.id
    )
    recolector.disponible = False
    aplicacion.servicios.participantes.registrar(Actor(rol=Rol.COORDINADOR), recolector)
    app = _pantalla(aplicacion, "recolector", recolector)
    assert app.button(key=f"recolector_recoger_{d.id}").disabled


def test_coordinador_conserva_participantes_del_historial(
    aplicacion, donante, receptores, recolector
):
    d = _publicar(aplicacion, donante, "Me sobraron 10 bolillos")
    primero = d.receptor_id
    aplicacion.servicios.distribucion.rechazar(
        Actor(rol=Rol.RECEPTOR, participante_id=primero), d.id, "Sin espacio"
    )
    app = _pantalla(aplicacion, "coordinador")
    app.selectbox(key="coordinador_eliminar_id").select(
        aplicacion.repos.participantes.obtener(primero)
    ).run()
    app.checkbox(key="coordinador_confirmar").check().run()
    assert app.button(key="coordinador_eliminar").disabled


def test_coordinador_filtra_bitacora(aplicacion, donante, receptores):
    d = _publicar(aplicacion, donante, "Me sobraron 10 bolillos")
    app = _pantalla(aplicacion, "coordinador")
    app.selectbox(key="coordinador_agente").select("Asignador").run()
    app.text_input(key="coordinador_donativo").set_value(d.id).run()
    bitacora = next(t for t in app.tabs if t.label == "Bitácora")
    entradas = bitacora.markdown
    assert entradas and all("**Asignador**" in e.value for e in entradas)
    app.text_input(key="coordinador_donativo").set_value("no-existe").run()
    assert not next(t for t in app.tabs if t.label == "Bitácora").markdown


def test_app_con_los_cuatro_roles(tmp_path, monkeypatch):
    """La app real: sin PIN no hay página; con PIN se abre la del rol del participante."""
    from pathlib import Path

    import streamlit as st
    from streamlit.testing.v1 import AppTest

    from rescate.dominio.enums import Rol

    monkeypatch.setenv("USAR_LLM_FALSO", "1")
    monkeypatch.setenv("RUTA_DB", str(tmp_path / "app.duckdb"))
    monkeypatch.setenv("PIN_DEMO", "1234")
    monkeypatch.setenv("PIN_COORDINADOR", "0000")
    st.cache_resource.clear()
    app = AppTest.from_file(
        str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=30
    ).run()
    assert not app.exception
    assert not app.header  # sin sesión no hay página
    assert len(app.selectbox(key="sesion_participante").options) == 7
    for rol, pin, encabezado in [
        (Rol.DONANTE, "1234", "Publica lo que te sobró"),
        (Rol.RECEPTOR, "1234", "Donativos para mi organización"),
        (Rol.RECOLECTOR, "1234", "Recolecciones"),
        (Rol.COORDINADOR, "0000", "Coordinación"),
    ]:
        app.radio(key="sesion_rol").set_value(rol).run()
        app.text_input(key="sesion_pin").input(pin)
        next(b for b in app.button if b.label == "Entrar").click().run()
        assert not app.exception
        assert app.header[0].value == encabezado
        assert not app.sidebar.radio  # ya no existe el selector de rol
        app.sidebar.button(key="sesion_salir").click().run()
        assert not app.header
    st.cache_resource.clear()


# ------------------------------------------------------------ ciclo ReAct (A6)


def paso(accion, receptor_id=None, pensamiento="Reviso", justificacion=None):
    return {
        "pensamiento": pensamiento,
        "accion": accion,
        "receptor_id": receptor_id,
        "justificacion": justificacion,
    }


def entradas_de(aplicacion, solicitud, tipo=None):
    return [
        e.contenido
        for e in aplicacion.bitacora.de_donativo(solicitud.donativo.id)
        if tipo is None or e.tipo == tipo
    ]


def esquemas_llamados(llm_falso):
    return [nombre for nombre, _ in llm_falso.llamadas]


def test_react_ciclo_valido(caso, llm_falso, aplicacion):
    agente, solicitud = caso
    llm_falso.programar(
        "PasoReAct",
        paso("listar_compatibles"),
        paso("distancia", "rec-cerca"),
        paso("capacidad", "rec-cerca"),
        paso("horario", "rec-cerca"),
        paso("equidad", "rec-cerca"),
        paso("finalizar", "rec-cerca", justificacion="Es el más cercano y le cabe."),
    )
    salida = agente.ejecutar(solicitud)
    assert salida.receptor_id == "rec-cerca"
    assert salida.justificacion.startswith(
        "Es el más cercano y le cabe. Datos calculados:"
    )
    assert esquemas_llamados(llm_falso) == ["PasoReAct"] * 6  # no hace falta el nivel 1
    observaciones = " ".join(
        entradas_de(aplicacion, solicitud, TipoEntradaBitacora.OBSERVACION)
    )
    assert (
        "Compatibles: Comedor Cerca (rec-cerca); Albergue Lejos (rec-lejos)"
        in observaciones
    )
    assert "km en línea recta" in observaciones and "puede recibir" in observaciones
    assert (
        "últimos 7 días" in observaciones and "pasa las validaciones" in observaciones
    )
    acciones = entradas_de(aplicacion, solicitud, TipoEntradaBitacora.ACCION)
    assert "ReAct 2: distancia(rec-cerca)" in acciones
    # el historial de pasos viaja delimitado en el prompt del siguiente paso
    ultimo = llm_falso.llamadas[-1][1]
    assert (
        "<datos_asignacion>" in ultimo
        and "pasos_anteriores" in ultimo
        and "km en línea recta" in ultimo
    )


def test_react_puede_elegir_otro_con_ventaja(caso, llm_falso):
    agente, solicitud = caso
    solicitud.receptores[0] = solicitud.receptores[0].model_copy(
        update={"capacidad_kg_dia": 1}
    )
    llm_falso.programar(
        "PasoReAct",
        paso("puntuar"),
        paso("finalizar", "rec-lejos", justificacion="Le cabe todo."),
    )
    assert agente.ejecutar(solicitud).receptor_id == "rec-lejos"


def test_react_accion_invalida_usa_el_nivel_1(caso, llm_falso, aplicacion):
    agente, solicitud = caso
    llm_falso.programar("PasoReAct", paso("distancia", "inventado"))
    assert agente.ejecutar(solicitud).receptor_id == "rec-cerca"
    errores = entradas_de(aplicacion, solicitud, TipoEntradaBitacora.ERROR)
    assert any("no es compatible" in e for e in errores)
    assert esquemas_llamados(llm_falso) == ["PasoReAct", "DecisionAsignacion"]


def test_react_respuesta_fuera_del_esquema_usa_el_nivel_1(caso, llm_falso):
    agente, solicitud = caso
    llm_falso.programar("PasoReAct", paso("borrar_base"))
    assert agente.ejecutar(solicitud).receptor_id == "rec-cerca"


def test_react_agota_los_pasos(caso, llm_falso, aplicacion):
    agente, solicitud = caso
    llm_falso.programar("PasoReAct", *[paso("puntuar")] * 6)
    llm_falso.programar(
        "DecisionAsignacion",
        {
            "razonamiento": "El primero",
            "receptor_id": "rec-cerca",
            "justificacion": "Mayor puntaje",
        },
    )
    assert agente.ejecutar(solicitud).receptor_id == "rec-cerca"
    assert esquemas_llamados(llm_falso) == ["PasoReAct"] * 6 + ["DecisionAsignacion"]
    assert any(
        "Se agotaron los 6 pasos" in e
        for e in entradas_de(aplicacion, solicitud, TipoEntradaBitacora.ERROR)
    )


def test_react_finalizar_con_incompatible(caso, llm_falso, aplicacion):
    agente, solicitud = caso
    solicitud.donativo.alimentos.append(
        Alimento(nombre="leche", cantidad=1, kg_estimados=1, tipo="lacteo")
    )
    llm_falso.programar(
        "PasoReAct", paso("finalizar", "rec-cerca", justificacion="El más cercano")
    )
    # rec-cerca no acepta lácteos: con un solo compatible no hay ReAct ni LLM
    assert agente.ejecutar(solicitud).receptor_id == "rec-lejos"
    solicitud.receptores.append(
        solicitud.receptores[1].model_copy(update={"id": "rec-lejos-2"})
    )
    salida = agente.ejecutar(solicitud)
    assert salida.receptor_id in {"rec-lejos", "rec-lejos-2"}
    assert any(
        "no es compatible" in e
        for e in entradas_de(aplicacion, solicitud, TipoEntradaBitacora.ERROR)
    )


def test_react_finalizar_sin_ventaja(caso, llm_falso, aplicacion):
    agente, solicitud = caso
    llm_falso.programar(
        "PasoReAct", paso("finalizar", "rec-lejos", justificacion="Me gusta más")
    )
    assert agente.ejecutar(solicitud).receptor_id == "rec-cerca"
    assert any(
        "no supera" in e
        for e in entradas_de(aplicacion, solicitud, TipoEntradaBitacora.ERROR)
    )


def test_react_finalizar_fuera_del_top_tres(caso, llm_falso, aplicacion):
    agente, solicitud = caso
    solicitud.receptores.extend(
        solicitud.receptores[0].model_copy(update={"id": f"rec-extra-{i}"})
        for i in range(3)
    )
    llm_falso.programar(
        "PasoReAct", paso("finalizar", "rec-lejos", justificacion="Lejano")
    )
    salida = agente.ejecutar(solicitud)
    assert salida.receptor_id != "rec-lejos"
    assert any(
        "no está entre los 3 mejores" in e
        for e in entradas_de(aplicacion, solicitud, TipoEntradaBitacora.ERROR)
    )


def test_react_justificacion_vacia_usa_una_plantilla(caso, llm_falso):
    agente, solicitud = caso
    llm_falso.programar("PasoReAct", paso("finalizar", "rec-cerca", justificacion=" "))
    assert agente.ejecutar(solicitud).justificacion.startswith(
        "Elegí Comedor Cerca tras revisar"
    )
