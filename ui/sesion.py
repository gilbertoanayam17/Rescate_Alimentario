"""Inicio y cierre de sesión con PIN y aviso de privacidad.

El rol no se elige: sale del participante con el que se entra (lo valida el servicio). La
página guarda en `st.session_state["sesion_actor"]` el `Actor` que regresa el servicio.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from rescate.dominio.enums import Rol
from rescate.dominio.modelos import Actor
from rescate.servicios import ErrorServicio, Servicios

CLAVE_ACTOR = "sesion_actor"
RUTA_AVISO = Path(__file__).resolve().parent.parent / "docs" / "aviso_privacidad.md"
ETIQUETA_ROL = {
    Rol.DONANTE: "Donante (comercio)",
    Rol.RECEPTOR: "Receptor (comedor)",
    Rol.RECOLECTOR: "Recolector (voluntario)",
    Rol.COORDINADOR: "Coordinador",
}


def actor_de_sesion() -> Actor | None:
    return st.session_state.get(CLAVE_ACTOR)


def aviso_privacidad() -> None:
    with st.expander("Aviso de privacidad"):
        try:
            st.markdown(RUTA_AVISO.read_text(encoding="utf-8"))
        except OSError:
            st.caption("El aviso de privacidad no está disponible.")


def pantalla_entrada(servicios: Servicios) -> None:
    """Sin sesión: elegir quién eres, escribir el PIN y entrar."""
    st.title("Rescate Alimentario")
    st.caption("Del sobrante de la fonda al comedor comunitario")
    rol = st.radio(
        "Entrar como",
        list(ETIQUETA_ROL),
        format_func=ETIQUETA_ROL.get,
        horizontal=True,
        key="sesion_rol",
    )
    elegido = None
    if rol != Rol.COORDINADOR:
        opciones = servicios.participantes.listar(rol)
        if not opciones:
            st.warning("No hay participantes con este rol. Pide a la coordinación que te dé de alta.")
            aviso_privacidad()
            return
        nombres = {p.id: p.nombre for p in opciones}
        elegido = st.selectbox("¿Quién eres?", list(nombres), format_func=nombres.get, key="sesion_participante")
    with st.form("sesion_entrada"):
        pin = st.text_input("PIN", type="password", max_chars=8, key="sesion_pin")
        entrar = st.form_submit_button("Entrar", type="primary")
    if entrar:
        try:
            actor = (
                servicios.participantes.sesion_coordinador(pin)
                if rol == Rol.COORDINADOR
                else servicios.participantes.iniciar_sesion(elegido, pin)
            )
        except ErrorServicio as exc:
            st.error(str(exc))
        else:
            st.session_state[CLAVE_ACTOR] = actor
            st.rerun()
    aviso_privacidad()


def barra_sesion(servicios: Servicios, actor: Actor) -> None:
    """Con sesión: quién eres y el botón para salir."""
    if actor.rol == Rol.COORDINADOR:
        nombre = "Coordinación"
    else:
        participante = servicios.participantes.obtener(actor.participante_id)
        nombre = participante.nombre if participante else actor.participante_id
    st.markdown(f"**Sesión:** {nombre} ({ETIQUETA_ROL[actor.rol]})")
    if st.button("Cerrar sesión", key="sesion_salir"):
        cerrar_sesion()
        st.rerun()


def cerrar_sesion() -> None:
    """Quita el actor y el estado de las páginas (claves con prefijo de página)."""
    prefijos = ("donante_", "receptor_", "recolector_", "coordinador_", "sesion_")
    for clave in list(st.session_state):
        if clave == CLAVE_ACTOR or str(clave).startswith(prefijos):
            del st.session_state[clave]
