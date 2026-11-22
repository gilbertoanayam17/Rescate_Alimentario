"""Ruta sugerida (CAR-04), traslado y confirmación de entrega de donativos aceptados."""

import pandas as pd
import pydeck as pdk
import streamlit as st

from rescate.dominio.enums import EstadoDonativo as E
from rescate.dominio.modelos import Actor, Recolector, ahora
from rescate.herramientas.geo import haversine_km
from rescate.herramientas.horario import limite_recoleccion
from rescate.servicios import ErrorServicio, Servicios
from ui.comun import tarjeta_donativo


def mostrar(servicios: Servicios, actor: Actor | None) -> None:
    """Coordina el traslado y consulta las entregas del voluntario."""
    st.header("Recolecciones")
    if actor is None or not actor.participante_id:
        st.info("Elige un recolector en la barra lateral.")
        return
    participante = servicios.participantes.obtener(actor.participante_id)
    if not isinstance(participante, Recolector):
        st.warning("El recolector ya no está disponible. Elige otro participante.")
        return
    if "recolector_aviso" in st.session_state:
        st.success(st.session_state.pop("recolector_aviso"))
    servicios.distribucion.vencer_pendientes()
    propios = servicios.distribucion.donativos_de_recolector(actor)
    tabs = st.tabs(["Listos para recoger", "Mi ruta", "En curso", "Historial"])
    with tabs[0]:
        disponibles = servicios.distribucion.disponibles_para_recolectar(actor)
        if not disponibles:
            st.info("No hay donativos aceptados esperando recolección.")
        for d in disponibles:
            tarjeta_donativo(servicios, actor, d, mostrar_bitacora=False)
            origen, destino = (
                servicios.participantes.obtener(d.donante_id),
                servicios.participantes.obtener(d.receptor_id),
            )
            if not origen or not destino:
                st.warning("Falta un participante. Consulta al coordinador.")
                continue
            st.write(
                f"{origen.nombre}: {origen.ubicacion.direccion} → "
                f"{destino.nombre}: {destino.ubicacion.direccion}"
            )
            st.caption(
                f"{haversine_km(origen.ubicacion, destino.ubicacion):.1f} "
                "km en línea recta; no es una ruta vial."
            )
            limite = limite_recoleccion(d, ahora())
            st.write(f"Recoger antes de {limite:%d/%m %H:%M}")
            for condicion in d.dictamen.condiciones if d.dictamen else []:
                st.warning(condicion)
            st.map(
                pd.DataFrame(
                    [
                        {"lat": p.ubicacion.lat, "lon": p.ubicacion.lon}
                        for p in [origen, destino]
                    ]
                )
            )
            vencido = limite <= ahora()
            if vencido:
                st.warning("La ventana terminó. Consulta al coordinador.")
            if not participante.disponible:
                st.info(
                    "Tu perfil está marcado como no disponible "
                    "para nuevas recolecciones."
                )
            if st.button(
                "Voy por él",
                key=f"recolector_recoger_{d.id}",
                disabled=vencido or not participante.disponible,
            ):
                try:
                    servicios.distribucion.iniciar_recoleccion(actor, d.id)
                    st.session_state.recolector_aviso = "Recolección iniciada."
                    st.rerun()
                except ErrorServicio as exc:
                    st.error(str(exc))
    with tabs[1]:
        mi_ruta(servicios, actor, participante)
    with tabs[2]:
        for d in propios:
            if d.estado != E.EN_RECOLECCION:
                continue
            tarjeta_donativo(servicios, actor, d, mostrar_bitacora=False)
            for condicion in d.dictamen.condiciones if d.dictamen else []:
                st.warning(condicion)
            if st.button("Entregado", key=f"recolector_entregar_{d.id}"):
                try:
                    servicios.distribucion.confirmar_entrega(actor, d.id)
                    st.session_state.recolector_aviso = "Entrega registrada."
                    st.rerun()
                except ErrorServicio as exc:
                    st.error(str(exc))
    with tabs[3]:
        entregados = [d for d in propios if d.estado == E.ENTREGADO]
        st.metric("Kg entregados", sum(d.kg_totales for d in entregados))
        for d in entregados:
            tarjeta_donativo(servicios, actor, d, mostrar_bitacora=False)


ACCION = {"recoger": "Recoger", "entregar": "Entregar"}


def mi_ruta(servicios: Servicios, actor: Actor, recolector: Recolector) -> None:
    """La ruta del Agente Logístico: paradas en orden, mapa, explicación y botón para tomarla."""
    st.caption(
        "El Agente Logístico junta lo que ya llevas con los donativos cercanos que te caben "
        "y propone el orden de las paradas."
    )
    if st.button("Calcular ruta sugerida", key="recolector_calcular_ruta"):
        st.session_state.recolector_ruta = servicios.distribucion.ruta_sugerida(actor) or "vacia"
    ruta = st.session_state.get("recolector_ruta")
    if ruta is None:
        return
    if ruta == "vacia":
        st.info("No hay donativos cercanos para armar una ruta.")
        return
    columnas = st.columns(3)
    columnas[0].metric("Paradas", len(ruta.paradas))
    columnas[1].metric("Km en línea recta", f"{ruta.km_total:.1f}")
    columnas[2].metric("Minutos aprox.", f"{ruta.minutos:.0f}")
    st.write(ruta.explicacion)
    for retraso in ruta.retrasos:
        st.warning(retraso)
    if ruta.sin_capacidad:
        st.caption(f"{len(ruta.sin_capacidad)} donativo(s) cercanos no caben en tu transporte.")
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Orden": p.orden,
                    "Acción": ACCION[p.tipo],
                    "Lugar": p.nombre,
                    "Llegada": f"{p.llegada:%H:%M}",
                    "Límite": f"{p.limite:%H:%M}" if p.limite else "",
                    "Donativo": p.donativo_id,
                }
                for p in ruta.paradas
            ]
        ),
        hide_index=True,
    )
    mapa_ruta(recolector, ruta)
    st.caption("Distancias en línea recta; no es una ruta vial.")
    if ruta.por_tomar and st.button(
        "Tomar estos donativos", key="recolector_tomar_ruta", type="primary"
    ):
        try:
            perdidos = servicios.distribucion.tomar_ruta(actor, ruta.por_tomar)
        except ErrorServicio as exc:
            st.error(str(exc))
            return
        tomados = len(ruta.por_tomar) - len(perdidos)
        aviso = f"Tomaste {tomados} donativo(s)."
        if perdidos:
            aviso += f" Otro voluntario ya había tomado {', '.join(perdidos)}."
        st.session_state.recolector_aviso = aviso
        st.session_state.pop("recolector_ruta", None)
        st.rerun()


def mapa_ruta(recolector: Recolector, ruta) -> None:
    """Recorrido (PathLayer) y paradas numeradas sobre el mapa."""
    puntos = [
        {"lon": p.lon, "lat": p.lat, "etiqueta": str(p.orden), "nombre": p.nombre}
        for p in ruta.paradas
    ]
    camino = [[recolector.ubicacion.lon, recolector.ubicacion.lat]] + [
        [p["lon"], p["lat"]] for p in puntos
    ]
    st.pydeck_chart(
        pdk.Deck(
            initial_view_state=pdk.ViewState(
                latitude=recolector.ubicacion.lat,
                longitude=recolector.ubicacion.lon,
                zoom=12,
            ),
            layers=[
                pdk.Layer(
                    "PathLayer",
                    data=[{"path": camino}],
                    get_path="path",
                    get_color=[30, 100, 200],
                    width_min_pixels=3,
                ),
                pdk.Layer(
                    "ScatterplotLayer",
                    data=puntos,
                    get_position="[lon, lat]",
                    get_fill_color=[220, 80, 40],
                    get_radius=60,
                    radius_min_pixels=8,
                    pickable=True,
                ),
                pdk.Layer(
                    "TextLayer",
                    data=puntos,
                    get_position="[lon, lat]",
                    get_text="etiqueta",
                    get_size=16,
                    get_color=[255, 255, 255],
                ),
            ],
            tooltip={"text": "{etiqueta}. {nombre}"},
        )
    )
