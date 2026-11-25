"""Aceptación, reasignación y perfil del comedor."""

from datetime import time, timedelta

import streamlit as st

from rescate.dominio.enums import EstadoDonativo as E
from rescate.dominio.enums import TipoAlimento
from rescate.dominio.modelos import Actor, Receptor, ahora
from rescate.servicios import ErrorServicio, Servicios
from ui.componentes_prediccion import tarjeta_pronostico
from ui.comun import boton_constancia, metricas_impacto, tarjeta_donativo

ETIQUETAS = dict(
    zip(
        TipoAlimento,
        [
            "Comida preparada",
            "Panadería",
            "Frutas y verduras",
            "Lácteos",
            "Carne y pescado crudos",
            "Abarrotes",
            "Bebidas",
            "Otro",
        ],
    )
)


def mostrar(servicios: Servicios, actor: Actor | None) -> None:
    """Muestra propuestas, entregas y la edición del perfil seleccionado."""
    st.header("Donativos para mi organización")
    if actor is None or not actor.participante_id:
        st.info("Elige un receptor en la barra lateral.")
        return
    participante = servicios.participantes.obtener(actor.participante_id)
    if not isinstance(participante, Receptor):
        st.warning("El receptor ya no está disponible. Elige otro participante.")
        return
    if "receptor_aviso" in st.session_state:
        st.success(st.session_state.pop("receptor_aviso"))
    donativos = servicios.distribucion.donativos_de_receptor(actor)
    pendientes = [
        d
        for d in donativos
        if d.estado == E.ASIGNADO and d.asignacion and not d.asignacion.aceptada
    ]
    recibidos = [d for d in donativos if d.estado == E.ENTREGADO]
    activos = {E.ASIGNADO, E.EN_RECOLECCION, E.ENTREGADO}
    kg = sum(
        d.kg_totales
        for d in donativos
        if d.estado in activos
        and d.asignacion
        and d.asignacion.fecha.date() == ahora().date()
    )
    columnas = st.columns(3)
    columnas[0].metric(
        "Kg comprometidos hoy / capacidad",
        f"{kg:g} / {participante.capacidad_kg_dia:g}",
    )
    columnas[1].metric("Por confirmar", len(pendientes))
    columnas[2].metric(
        "Kg recibidos esta semana",
        sum(
            d.kg_totales
            for d in recibidos
            if d.actualizado >= ahora() - timedelta(days=7)
        ),
    )
    tabs = st.tabs(
        ["Por confirmar", "En camino", "Recibidos", "Posibles donativos", "Mi perfil"]
    )
    with tabs[0]:
        if not pendientes:
            st.info("No hay donativos por confirmar.")
        for d in pendientes:
            tarjeta_donativo(servicios, actor, d)
            st.caption("El sistema orienta sobre inocuidad; no certifica el alimento.")
            try:
                if st.button("Aceptar", key=f"receptor_aceptar_{d.id}", type="primary", icon=":material/check:"):
                    servicios.distribucion.aceptar(actor, d.id)
                    st.session_state.receptor_aviso = (
                        "Donativo aceptado. Ya aparece para los recolectores."
                    )
                    st.rerun()
                motivo = st.text_input(
                    "Motivo del rechazo", key=f"receptor_motivo_{d.id}"
                )
                if st.button("No podemos recibirlo", key=f"receptor_rechazar_{d.id}", icon=":material/close:"):
                    if not motivo.strip():
                        st.error("Escribe un motivo para la reasignación.")
                    else:
                        actualizado = servicios.distribucion.rechazar(actor, d.id, motivo)
                        nuevo = servicios.participantes.obtener(actualizado.receptor_id)
                        st.session_state.receptor_aviso = (
                            f"Se reasignó a {nuevo.nombre}."
                            if nuevo
                            else "Quedó pendiente para el coordinador."
                        )
                        st.rerun()
            except ErrorServicio as exc:
                st.error(str(exc))
    with tabs[1]:
        for d in donativos:
            if d.estado == E.EN_RECOLECCION or (
                d.estado == E.ASIGNADO and d.asignacion and d.asignacion.aceptada
            ):
                tarjeta_donativo(servicios, actor, d)
                recolector = servicios.participantes.obtener(d.recolector_id)
                st.caption(
                    f"Recolector: {recolector.nombre}"
                    if recolector
                    else "Esperando recolector"
                )
    with tabs[2]:
        st.metric("Total de kg recibidos", sum(d.kg_totales for d in recibidos))
        st.subheader("Mi impacto (últimos 12 meses)")
        hoy = ahora().date()
        metricas_impacto(
            servicios.reportes.tablero(actor, hoy - timedelta(days=365), hoy)
        )
        for d in recibidos:
            tarjeta_donativo(servicios, actor, d)
            boton_constancia(servicios, actor, d, "receptor")
    with tabs[3]:
        posibles_donativos(servicios, actor)
    with tabs[4], st.form("receptor_perfil"):
        tipos = st.multiselect(
            "Tipos aceptados",
            list(TipoAlimento),
            default=participante.tipos_aceptados,
            format_func=lambda x: ETIQUETAS[x],
        )
        capacidad = st.number_input(
            "Capacidad kg/día",
            min_value=0.0,
            value=float(participante.capacidad_kg_dia),
        )
        frio = st.checkbox(
            "Tiene refrigeración", value=participante.tiene_refrigeracion
        )
        apertura = st.time_input(
            "Hora de apertura", time.fromisoformat(participante.hora_apertura)
        )
        cierre = st.time_input(
            "Hora de cierre", time.fromisoformat(participante.hora_cierre)
        )
        personas = st.number_input(
            "Personas atendidas", min_value=0, value=participante.personas_atendidas
        )
        direccion = st.text_input("Dirección", participante.ubicacion.direccion)
        if st.form_submit_button("Guardar perfil", type="primary", icon=":material/save:"):
            try:
                servicios.participantes.registrar(
                    actor,
                    participante.model_copy(
                        update=dict(
                            tipos_aceptados=tipos,
                            capacidad_kg_dia=capacidad,
                            tiene_refrigeracion=frio,
                            hora_apertura=apertura.strftime("%H:%M"),
                            hora_cierre=cierre.strftime("%H:%M"),
                            personas_atendidas=personas,
                            ubicacion=participante.ubicacion.model_copy(
                                update={"direccion": direccion}
                            ),
                        )
                    )
                )
                st.session_state.receptor_aviso = "Perfil actualizado."
                st.rerun()
            except ErrorServicio as exc:
                st.error(str(exc))


def posibles_donativos(servicios: Servicios, actor: Actor) -> None:
    """Pronósticos en los que este comedor quedó pre-reservado (CAR-07), sin acciones."""
    st.caption(
        "Lo que probablemente te donen hoy, según lo que cada comercio ha donado otros días. "
        "El donativo llega cuando el comercio lo publica."
    )
    pronosticos = servicios.prediccion.pronosticos_para_receptor(actor)
    if not pronosticos:
        st.info("Por ahora no hay posibles donativos para tu organización.")
    for p in pronosticos:
        donante = servicios.participantes.obtener(p.donante_id)
        tarjeta_pronostico(p, nombre_donante=donante.nombre if donante else None)
