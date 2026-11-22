"""Traslado y confirmación de entrega de donativos aceptados."""

import pandas as pd
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
    propios = servicios.distribucion.donativos_de_recolector(actor)
    tabs = st.tabs(["Listos para recoger", "En curso", "Historial"])
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
    with tabs[2]:
        entregados = [d for d in propios if d.estado == E.ENTREGADO]
        st.metric("Kg entregados", sum(d.kg_totales for d in entregados))
        for d in entregados:
            tarjeta_donativo(servicios, actor, d, mostrar_bitacora=False)
