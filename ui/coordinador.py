"""Administración de participantes, bandeja de casos (CAR-10), pronósticos y trazabilidad."""

from collections import Counter
from datetime import time, timedelta

import pandas as pd
import streamlit as st

from rescate.dominio.enums import EstadoDonativo as E
from rescate.dominio.enums import Rol, TipoAlimento, TipoCaso
from rescate.dominio.modelos import (
    Actor,
    Donante,
    Receptor,
    Recolector,
    Ubicacion,
    ahora,
)
from rescate.mediador import TITULO_CASO
from rescate.servicios import ErrorServicio, Servicios
from ui.componentes_prediccion import tarjeta_pronostico
from ui.comun import (
    ETIQUETA_ESTADO,
    historial_estados,
    metricas_impacto,
    tarjeta_donativo,
    vista_bitacora,
)
from ui.receptor import ETIQUETAS


def mostrar(servicios: Servicios, actor: Actor | None) -> None:
    """Administra la demostración y permite consultar su trazabilidad."""
    st.header("Coordinación")
    if "coordinador_aviso" in st.session_state:
        st.success(st.session_state.pop("coordinador_aviso"))
    vencidos = servicios.distribucion.vencer_pendientes()
    if vencidos:
        st.warning(
            f"{len(vencidos)} donativo(s) vencieron sin recogerse; revisa la pestaña Casos."
        )
    todos = servicios.reportes.todos(actor)
    pendientes = [
        d
        for d in todos
        if d.estado == E.EVALUADO
        and (not d.asignacion or not d.receptor_id or d.asignacion.requiere_coordinador)
    ]
    tabs = st.tabs(
        [
            "Resumen",
            "Donativos",
            "Casos",
            "Impacto",
            "Participantes",
            "Pronósticos",
            "Bitácora",
        ]
    )
    with tabs[0]:
        cols = st.columns(5)
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
        cols[4].metric("Casos abiertos", len(servicios.casos.abiertos(actor)))
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
                tarjeta_donativo(servicios, actor, d, mostrar_bitacora=False)
                with st.expander(f"Historial {d.id}"):
                    historial_estados(servicios, actor, d.id)
    with tabs[2]:
        bandeja_casos(servicios, actor)
    with tabs[3]:
        pestana_impacto(servicios, actor)
    with tabs[4]:
        for rol in (Rol.DONANTE, Rol.RECEPTOR, Rol.RECOLECTOR):
            st.subheader(rol.value.capitalize())
            personas = servicios.participantes.listar(rol)
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
            pin = st.text_input(
                "PIN de acceso (4 a 8 dígitos)", type="password", max_chars=8
            )
            if st.form_submit_button("Registrar participante"):
                try:
                    if not pin.strip():
                        raise ErrorServicio("Escribe el PIN con el que entrará.")
                    clase = {
                        Rol.DONANTE: Donante,
                        Rol.RECEPTOR: Receptor,
                        Rol.RECOLECTOR: Recolector,
                    }[rol]
                    servicios.participantes.registrar(
                        actor,
                        clase(
                            nombre=nombre.strip(),
                            ubicacion=Ubicacion(lat=lat, lon=lon, direccion=direccion),
                            **campos,
                        ),
                        pin=pin,
                    )
                    st.session_state.coordinador_aviso = "Participante registrado."
                    st.rerun()
                except ErrorServicio as exc:
                    st.error(str(exc))
        personas = servicios.participantes.listar()
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
                    servicios.participantes.eliminar(actor, elegido.id)
                    st.session_state.coordinador_aviso = "Participante eliminado."
                    st.rerun()
                except ErrorServicio as exc:
                    st.error(str(exc))
    with tabs[5]:
        pronosticos_del_dia(servicios, actor)
    with tabs[6]:
        entradas = servicios.reportes.bitacora_reciente(actor, 200)
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


def pronosticos_del_dia(servicios: Servicios, actor: Actor) -> None:
    """Genera y muestra los pronósticos de hoy de todos los donantes (CAR-07)."""
    hoy = ahora().date()
    if st.button("Generar pronósticos de hoy", key="coordinador_generar_pronosticos"):
        try:
            st.session_state.coordinador_pronosticos = servicios.prediccion.generar(
                actor, hoy
            )
        except ErrorServicio as exc:
            st.error(str(exc))
    pronosticos = st.session_state.get("coordinador_pronosticos")
    if pronosticos is None:
        st.info("Pulsa el botón para calcular los pronósticos del día.")
        return
    if not pronosticos:
        st.info("Hoy no hay pronósticos: ningún comercio tiene un patrón para este día.")
    for p in pronosticos:
        donante = servicios.participantes.obtener(p.donante_id)
        receptor = servicios.participantes.obtener(p.receptor_sugerido_id)
        tarjeta_pronostico(
            p,
            nombre_donante=donante.nombre if donante else None,
            nombre_receptor=receptor.nombre if receptor else None,
        )


ACTIVOS = {E.PUBLICADO, E.EVALUADO, E.ASIGNADO, E.EN_RECOLECCION}


def bandeja_casos(servicios: Servicios, actor: Actor) -> None:
    """Casos escalados por los agentes, agrupados por tipo, con sus acciones."""
    casos = servicios.casos.abiertos(actor)
    if not casos:
        st.info("No hay casos abiertos.")
        return
    atendidos: set[str] = set()  # un donativo con varios casos muestra sus acciones una vez
    for tipo in TipoCaso:
        del_tipo = [c for c in casos if c.tipo == tipo]
        if not del_tipo:
            continue
        st.subheader(f"{TITULO_CASO[tipo]} ({len(del_tipo)})")
        for caso in del_tipo:
            with st.container(border=True):
                st.markdown(
                    f"**{caso.emisor}** · {caso.creado:%d/%m %H:%M} — {caso.motivo}"
                )
                donativo = (
                    servicios.reportes.donativo(actor, caso.donativo_id)
                    if caso.donativo_id
                    else None
                )
                if donativo and donativo.id not in atendidos:
                    atendidos.add(donativo.id)
                    tarjeta_donativo(servicios, actor, donativo)
                    acciones_donativo(servicios, actor, donativo)
                resolver_caso(servicios, actor, caso.id)


def acciones_donativo(servicios: Servicios, actor: Actor, donativo) -> None:
    """Reintentar, asignar a mano o cancelar el donativo de un caso."""
    try:
        if donativo.estado == E.EVALUADO:
            if st.button("Reintentar asignación", key=f"coordinador_reintentar_{donativo.id}"):
                servicios.distribucion.reintentar_asignacion(actor, donativo.id)
                st.session_state.coordinador_aviso = "Asignación reevaluada."
                st.rerun()
            compatibles = servicios.distribucion.receptores_compatibles(actor, donativo.id)
            if compatibles:
                receptor = st.selectbox(
                    "Asignar manualmente a",
                    compatibles,
                    format_func=lambda r: r.nombre,
                    key=f"coordinador_manual_receptor_{donativo.id}",
                )
                motivo = st.text_input(
                    "Motivo de la asignación manual",
                    key=f"coordinador_manual_motivo_{donativo.id}",
                )
                if st.button("Asignar", key=f"coordinador_manual_{donativo.id}"):
                    servicios.distribucion.asignar_manual(
                        actor, donativo.id, receptor.id, motivo
                    )
                    st.session_state.coordinador_aviso = f"Asignado a {receptor.nombre}."
                    st.rerun()
            else:
                st.caption("Ningún receptor registrado es compatible con este donativo.")
        if donativo.estado in ACTIVOS and st.button(
            "Cancelar donativo", key=f"coordinador_cancelar_{donativo.id}"
        ):
            servicios.publicacion.cancelar(
                actor, donativo.id, "Cancelado por la coordinación"
            )
            st.session_state.coordinador_aviso = "Donativo cancelado."
            st.rerun()
    except ErrorServicio as exc:
        st.error(str(exc))


def resolver_caso(servicios: Servicios, actor: Actor, caso_id: str) -> None:
    nota = st.text_input("Nota de resolución", key=f"coordinador_nota_{caso_id}")
    if st.button("Marcar como resuelto", key=f"coordinador_resolver_{caso_id}"):
        try:
            servicios.casos.resolver(actor, caso_id, nota)
            st.session_state.coordinador_aviso = "Caso resuelto."
            st.rerun()
        except ErrorServicio as exc:
            st.error(str(exc))


def pestana_impacto(servicios: Servicios, actor: Actor) -> None:
    """Tablero de impacto (CAR-08): periodo, filtros, cifras clave y gráficas."""
    hoy = ahora().date()
    filtros = st.columns(4)
    desde = filtros[0].date_input(
        "Desde", hoy - timedelta(days=365), key="coordinador_impacto_desde"
    )
    hasta = filtros[1].date_input("Hasta", hoy, key="coordinador_impacto_hasta")
    donante = filtros[2].selectbox(
        "Donante",
        [None, *servicios.participantes.listar(Rol.DONANTE)],
        format_func=lambda p: "Todos" if p is None else p.nombre,
        key="coordinador_impacto_donante",
    )
    receptor = filtros[3].selectbox(
        "Receptor",
        [None, *servicios.participantes.listar(Rol.RECEPTOR)],
        format_func=lambda p: "Todos" if p is None else p.nombre,
        key="coordinador_impacto_receptor",
    )
    if desde > hasta:
        st.error("La fecha inicial debe ser anterior a la final.")
        return
    tablero = servicios.reportes.tablero(
        actor,
        desde,
        hasta,
        donante_id=donante.id if donante else None,
        receptor_id=receptor.id if receptor else None,
    )
    metricas_impacto(tablero)
    st.download_button(
        "Descargar reporte ESG (PDF)",
        data=lambda: servicios.reportes.reporte_impacto_pdf(actor, desde, hasta),
        file_name=f"reporte_impacto_{desde:%Y%m%d}_{hasta:%Y%m%d}.pdf",
        mime="application/pdf",
        key="coordinador_reporte_esg",
        help="Cifras de toda la organización en el periodo elegido.",
    )
    if not tablero.resumen.donativos:
        st.info("No hay entregas en este periodo.")
        return
    serie = pd.DataFrame(
        [
            {"Semana": p.semana, "kg": p.kg, "raciones": p.raciones, "CO2e (kg)": p.co2e_kg}
            for p in tablero.serie_semanal
        ]
    ).set_index("Semana")
    st.markdown("**Kg rescatados por semana**")
    st.line_chart(serie[["kg"]], y_label="kg")
    izquierda, derecha = st.columns(2)
    for columna, titulo, top in (
        (izquierda, "Top 10 donantes (kg)", tablero.top_donantes),
        (derecha, "Top 10 receptores (kg)", tablero.top_receptores),
    ):
        columna.markdown(f"**{titulo}**")
        columna.bar_chart(
            pd.DataFrame([{"nombre": p.nombre, "kg": p.kg} for p in top]).set_index("nombre"),
            horizontal=True,
            sort="-kg",
            x_label="kg",
            y_label="",
        )
    st.markdown("**Kg por tipo de alimento**")
    st.bar_chart(
        pd.DataFrame(
            [{"tipo": ETIQUETAS[TipoAlimento(t)], "kg": kg} for t, kg in tablero.kg_por_tipo.items()]
        ).set_index("tipo"),
        horizontal=True,
        sort="-kg",
        x_label="kg",
        y_label="",
    )
    with st.expander("Ver los datos en tabla"):
        st.dataframe(serie)
