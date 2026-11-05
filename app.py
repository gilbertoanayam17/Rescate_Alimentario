"""Punto de entrada de la interfaz: `streamlit run app.py`.

En el MVP no hay login: en la barra lateral se elige el rol y el participante
(los cuatro roles se simulan desde la misma app).

Archivo COMPARTIDO (fase 0). Cada página vive en ui/<rol>.py y expone
`mostrar(servicio, participante)`.
"""
import streamlit as st

from rescate.contenedor import construir_servicio
from rescate.dominio.enums import Rol
from ui import coordinador, donante, receptor, recolector

st.set_page_config(page_title="Rescate Alimentario", page_icon="🥖", layout="wide")


@st.cache_resource
def obtener_servicio():
    return construir_servicio()


servicio = obtener_servicio()

PAGINAS = {
    Rol.DONANTE: donante,
    Rol.RECEPTOR: receptor,
    Rol.RECOLECTOR: recolector,
    Rol.COORDINADOR: coordinador,
}
ETIQUETAS = {
    Rol.DONANTE: "Donante (comercio)",
    Rol.RECEPTOR: "Receptor (comedor)",
    Rol.RECOLECTOR: "Recolector (voluntario)",
    Rol.COORDINADOR: "Coordinador",
}

with st.sidebar:
    st.title("Rescate Alimentario")
    st.caption("Del sobrante de la fonda al comedor comunitario")
    rol = st.radio("Entrar como", list(PAGINAS), format_func=ETIQUETAS.get, key="rol")
    participante = None
    if rol != Rol.COORDINADOR:
        opciones = servicio.participantes(rol)
        if not opciones:
            st.warning("No hay participantes con este rol. Da de alta uno como coordinador.")
        else:
            nombres = {p.id: p.nombre for p in opciones}
            elegido = st.selectbox(
                "¿Quién eres?", list(nombres), format_func=nombres.get, key=f"participante_{rol.value}"
            )
            participante = servicio.participante(elegido)
    st.divider()
    st.caption(servicio.estado_llm())

PAGINAS[rol].mostrar(servicio, participante)
