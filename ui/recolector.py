"""Traslado y confirmación de entrega de donativos aceptados."""

import pandas as pd
import streamlit as st

from rescate.dominio.enums import EstadoDonativo as E
from rescate.dominio.modelos import Participante, Recolector, ahora
from rescate.herramientas.geo import haversine_km
from rescate.herramientas.horario import limite_recoleccion
from rescate.servicios import ErrorServicio, ServicioDonativos
from ui.comun import tarjeta_donativo


def mostrar(servicio: ServicioDonativos, participante: Participante | None) -> None:
    """Coordina el traslado y consulta las entregas del voluntario."""
    st.header("Recolecciones")
    if participante is None:
        st.info("Elige un recolector en la barra lateral.")
        return
    participante = servicio.participante(participante.id)
    if not isinstance(participante, Recolector):
        st.warning("El recolector ya no está disponible. Elige otro participante.")
        return
    if "recolector_aviso" in st.session_state:
        st.success(st.session_state.pop("recolector_aviso"))
    propios = servicio.donativos_de_recolector(participante.id)
    tabs = st.tabs(["Listos para recoger", "En curso", "Historial"])
    with tabs[0]:
        disponibles = servicio.disponibles_para_recolectar()
        if not disponibles:
            st.info("No hay donativos aceptados esperando recolección.")
        for d in disponibles:
            tarjeta_donativo(servicio, d, mostrar_bitacora=False)
            origen, destino = (
                servicio.participante(d.donante_id),
                servicio.participante(d.receptor_id),
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
                    servicio.iniciar_recoleccion(d.id, participante.id)
                    st.session_state.recolector_aviso = "Recolección iniciada."
                    st.rerun()
                except ErrorServicio as exc:
                    st.error(str(exc))
    with tabs[1]:
        for d in propios:
            if d.estado != E.EN_RECOLECCION:
                continue
            tarjeta_donativo(servicio, d, mostrar_bitacora=False)
            for condicion in d.dictamen.condiciones if d.dictamen else []:
                st.warning(condicion)
            if st.button("Entregado", key=f"recolector_entregar_{d.id}"):
                try:
                    servicio.confirmar_entrega(d.id, participante.id)
                    st.session_state.recolector_aviso = "Entrega registrada."
                    st.rerun()
                except ErrorServicio as exc:
                    st.error(str(exc))
    with tabs[2]:
        entregados = [d for d in propios if d.estado == E.ENTREGADO]
        st.metric("Kg entregados", sum(d.kg_totales for d in entregados))
        for d in entregados:
            tarjeta_donativo(servicio, d, mostrar_bitacora=False)
