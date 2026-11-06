"""Administración de participantes, casos pendientes y trazabilidad."""

from collections import Counter
from datetime import time

import streamlit as st

from rescate.dominio.enums import EstadoDonativo as E
from rescate.dominio.enums import Rol, TipoAlimento
from rescate.dominio.modelos import (
    Donante,
    Participante,
    Receptor,
    Recolector,
    Ubicacion,
)
from rescate.servicios import ErrorServicio, ServicioDonativos
from ui.comun import (
    ETIQUETA_ESTADO,
    historial_estados,
    tarjeta_donativo,
    vista_bitacora,
)
from ui.receptor import ETIQUETAS


def mostrar(servicio: ServicioDonativos, participante: Participante | None) -> None:
    """Administra la demostración y permite consultar su trazabilidad."""
    st.header("Coordinación")
    if "coordinador_aviso" in st.session_state:
        st.success(st.session_state.pop("coordinador_aviso"))
    todos = servicio.todos()
    pendientes = [
        d
        for d in todos
        if d.estado == E.EVALUADO
        and (not d.asignacion or not d.receptor_id or d.asignacion.requiere_coordinador)
    ]
    tabs = st.tabs(
        ["Resumen", "Donativos", "Sin receptor", "Participantes", "Bitácora"]
    )
    with tabs[0]:
        cols = st.columns(4)
        cols[0].metric(
            "Kg entregados", sum(d.kg_totales for d in todos if d.estado == E.ENTREGADO)
        )
        cols[1].metric(
            "Donativos activos",
            sum(
                d.estado in {E.PUBLICADO, E.EVALUADO, E.ASIGNADO, E.EN_RECOLECCION}
                for d in todos
            ),
        )
        cols[2].metric("No aptos", sum(d.estado == E.RECHAZADO for d in todos))
        cols[3].metric("Sin receptor", len(pendientes))
        conteo = Counter(ETIQUETA_ESTADO[d.estado][0] for d in todos)
        if conteo:
            st.bar_chart(dict(conteo))
        else:
            st.info("Publica un donativo para comenzar.")
    with tabs[1]:
        estados = st.multiselect(
            "Estados",
            list(E),
            default=list(E),
            format_func=lambda e: ETIQUETA_ESTADO[e][0],
            key="coordinador_estados",
        )
        for d in todos:
            if d.estado in estados:
                tarjeta_donativo(servicio, d, mostrar_bitacora=False)
                with st.expander(f"Historial {d.id}"):
                    historial_estados(servicio, d.id)
    with tabs[2]:
        if not pendientes:
            st.info("No hay casos pendientes de asignación.")
        for d in pendientes:
            tarjeta_donativo(servicio, d)
            if st.button("Reintentar asignación", key=f"coordinador_reintentar_{d.id}"):
                try:
                    servicio.reintentar_asignacion(d.id)
                    st.session_state.coordinador_aviso = "Asignación reevaluada."
                    st.rerun()
                except ErrorServicio as exc:
                    st.error(str(exc))
    with tabs[3]:
        for rol in (Rol.DONANTE, Rol.RECEPTOR, Rol.RECOLECTOR):
            st.subheader(rol.value.capitalize())
            personas = servicio.participantes(rol)
            st.dataframe(
                [
                    {"id": p.id, "nombre": p.nombre, "dirección": p.ubicacion.direccion}
                    for p in personas
                ]
            )
        rol = st.selectbox(
            "Tipo de participante nuevo",
            [Rol.DONANTE, Rol.RECEPTOR, Rol.RECOLECTOR],
            format_func=lambda r: r.value,
            key="coordinador_rol",
        )
        with st.form("coordinador_alta"):
            nombre = st.text_input("Nombre")
            direccion = st.text_input("Dirección")
            lat = st.number_input(
                "Latitud", min_value=20.55, max_value=20.80, value=20.67, format="%.5f"
            )
            lon = st.number_input(
                "Longitud",
                min_value=-103.50,
                max_value=-103.20,
                value=-103.34,
                format="%.5f",
            )
            campos = {}
            if rol in (Rol.DONANTE, Rol.RECEPTOR):
                campos["hora_cierre"] = st.time_input(
                    "Hora de cierre", time(20)
                ).strftime("%H:%M")
            if rol == Rol.DONANTE:
                campos["tipo_comercio"] = st.text_input("Tipo de comercio", "fonda")
            elif rol == Rol.RECEPTOR:
                campos["tipos_aceptados"] = st.multiselect(
                    "Tipos aceptados",
                    list(TipoAlimento),
                    default=list(TipoAlimento),
                    format_func=lambda t: ETIQUETAS[t],
                )
                campos["capacidad_kg_dia"] = st.number_input(
                    "Capacidad kg/día", min_value=0.0, value=50.0
                )
                campos["tiene_refrigeracion"] = st.checkbox("Tiene refrigeración")
                campos["hora_apertura"] = st.time_input(
                    "Hora de apertura", time(8)
                ).strftime("%H:%M")
                campos["personas_atendidas"] = st.number_input(
                    "Personas atendidas", min_value=0, value=50
                )
            else:
                campos["zona"] = st.text_input("Zona")
                campos["transporte"] = st.selectbox(
                    "Transporte", ["auto", "moto", "bicicleta", "a pie"]
                )
                campos["disponible"] = st.checkbox("Disponible", value=True)
            if st.form_submit_button("Registrar participante"):
                try:
                    clase = {
                        Rol.DONANTE: Donante,
                        Rol.RECEPTOR: Receptor,
                        Rol.RECOLECTOR: Recolector,
                    }[rol]
                    servicio.registrar_participante(
                        clase(
                            nombre=nombre.strip(),
                            ubicacion=Ubicacion(lat=lat, lon=lon, direccion=direccion),
                            **campos,
                        )
                    )
                    st.session_state.coordinador_aviso = "Participante registrado."
                    st.rerun()
                except ErrorServicio as exc:
                    st.error(str(exc))
        personas = servicio.participantes()
        if personas:
            elegido = st.selectbox(
                "Participante para eliminar",
                personas,
                format_func=lambda p: f"{p.nombre} ({p.id})",
                key="coordinador_eliminar_id",
            )
            confirmar = st.checkbox(
                "Confirmo la eliminación", key="coordinador_confirmar"
            )
            vinculado = any(
                elegido.id in (d.donante_id, d.receptor_id, d.recolector_id)
                or elegido.id in d.receptores_descartados
                or (d.asignacion and elegido.id in d.asignacion.alternativas)
                for d in todos
            )
            if vinculado:
                st.caption(
                    "Conservamos participantes vinculados a donativos "
                    "para mantener el historial."
                )
            if st.button(
                "Eliminar participante",
                disabled=not confirmar or vinculado,
                key="coordinador_eliminar",
            ):
                try:
                    servicio.eliminar_participante(elegido.id)
                    st.session_state.coordinador_aviso = "Participante eliminado."
                    st.rerun()
                except ErrorServicio as exc:
                    st.error(str(exc))
    with tabs[4]:
        entradas = servicio.bitacora_reciente(200)
        agente = st.selectbox(
            "Agente",
            ["Todos"] + sorted({e.agente for e in entradas}),
            key="coordinador_agente",
        )
        donativo = st.text_input(
            "Filtrar por id de donativo", key="coordinador_donativo"
        )
        vista_bitacora(
            [
                e
                for e in entradas
                if (agente == "Todos" or e.agente == agente)
                and (not donativo or e.donativo_id == donativo.strip())
            ]
        )
