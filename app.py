"""Punto de entrada de la interfaz: `streamlit run app.py`.

Sin sesión, la pantalla de entrada pide el participante y su PIN (o el PIN del coordinador). El
rol no se elige: sale del participante con el que se entra y los servicios lo validan contra
la base. Cada página vive en ui/<rol>.py y expone `mostrar(servicios, actor)`.
"""
import streamlit as st

from rescate.contenedor import construir_servicios
from rescate.dominio.enums import Rol
from ui import coordinador, donante, receptor, recolector
from ui.comun import panel_avisos
from ui.sesion import actor_de_sesion, barra_sesion, pantalla_entrada

st.set_page_config(page_title="Rescate Alimentario", page_icon="🥖", layout="wide")


@st.cache_resource
def obtener_servicios():
    return construir_servicios()


servicios = obtener_servicios()

PAGINAS = {
    Rol.DONANTE: donante,
    Rol.RECEPTOR: receptor,
    Rol.RECOLECTOR: recolector,
    Rol.COORDINADOR: coordinador,
}

actor = actor_de_sesion()
if actor is None:
    pantalla_entrada(servicios)
    st.caption(servicios.estado_llm())
    st.stop()

with st.sidebar:
    st.title("Rescate Alimentario")
    st.caption("Del sobrante de la fonda al comedor comunitario")
    barra_sesion(servicios, actor)
    st.divider()
    panel_avisos(servicios, actor)
    st.caption(servicios.estado_llm())

PAGINAS[actor.rol].mostrar(servicios, actor)
