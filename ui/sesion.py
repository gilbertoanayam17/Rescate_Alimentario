"""Inicio y cierre de sesión con PIN y aviso de privacidad.

El rol no se elige: sale del participante con el que se entra (lo valida el servicio). La
página guarda en `st.session_state["sesion_actor"]` el `Actor` que regresa el servicio.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

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
#: Lo que la coordinación necesita para dar de alta a alguien (los campos de su registro).
DATOS_ALTA = {
    Rol.DONANTE: "nombre del comercio, tipo (fonda, panadería, puesto…), dirección, teléfono y hora de cierre",
    Rol.RECEPTOR: (
        "nombre de la organización, dirección, teléfono, alimentos que reciben, cuántos kilos pueden "
        "recibir al día, si tienen refrigerador, horario de recepción y cuántas personas atienden"
    ),
    Rol.RECOLECTOR: "nombre, teléfono, zona donde te mueves y transporte (a pie, bicicleta, moto o auto)",
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
    """Sin sesión: la entrada va en una columna central angosta para que se lea de un vistazo."""
    _, centro, _ = st.columns([1, 2, 1])
    with centro:
        _formulario_entrada(servicios)


def _formulario_entrada(servicios: Servicios) -> None:
    """Elegir quién eres, escribir el PIN y entrar."""
    st.title(":material/volunteer_activism: Rescate Alimentario")
    st.caption("Los comercios publican la comida que les sobró y los comedores comunitarios la reciben.")
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
            st.warning("No hay participantes con este rol todavía.")
            como_registrarse(servicios, rol)
            aviso_privacidad()
            return
        nombres = {p.id: p.nombre for p in opciones}
        elegido = st.selectbox("¿Quién eres?", list(nombres), format_func=nombres.get, key="sesion_participante")
    with st.form("sesion_entrada"):
        pin = st.text_input(
            "PIN", type="password", max_chars=8, key="sesion_pin",
            help="Si lo olvidaste, la coordinación te asigna uno nuevo.",
        )
        entrar = st.form_submit_button("Entrar", type="primary", icon=":material/login:")
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
    if rol != Rol.COORDINADOR:
        como_registrarse(servicios, rol)
    aviso_privacidad()


def contacto_coordinacion(servicios: Servicios, asunto: str) -> str:
    """Correo y teléfono de la coordinación como ligas (configurables en .env)."""
    partes = []
    if servicios.correo_coordinacion:
        correo = servicios.correo_coordinacion
        partes.append(f":material/mail: [{correo}](mailto:{correo}?subject={quote(asunto)})")
    if servicios.telefono_coordinacion:
        telefono = servicios.telefono_coordinacion
        digitos = "".join(c for c in telefono if c.isdigit() or c == "+")
        partes.append(f":material/call: [{telefono}](tel:{digitos})")
    return " · ".join(partes)


def como_registrarse(servicios: Servicios, rol: Rol) -> None:
    """Quien no tiene cuenta no puede darse de alta solo: la coordinación lo registra y le da su PIN."""
    with st.container(border=True):
        st.markdown("**¿No tienes cuenta o olvidaste tu PIN?**")
        st.markdown(
            "La coordinación de la red registra a cada participante y le asigna su PIN. "
            f"Para darte de alta como {ETIQUETA_ROL[rol].lower()}, mándale: {DATOS_ALTA[rol]}."
        )
        contacto = contacto_coordinacion(servicios, f"Alta en Rescate Alimentario: {ETIQUETA_ROL[rol]}")
        st.markdown(contacto or "Pide los datos de contacto a la organización que opera la red en tu zona.")


def barra_sesion(servicios: Servicios, actor: Actor) -> None:
    """Con sesión: quién eres y el botón para salir."""
    if actor.rol == Rol.COORDINADOR:
        nombre = "Coordinación"
    else:
        participante = servicios.participantes.obtener(actor.participante_id)
        nombre = participante.nombre if participante else actor.participante_id
    st.markdown(f"**Sesión:** {nombre} ({ETIQUETA_ROL[actor.rol]})")
    if st.button("Cerrar sesión", key="sesion_salir", icon=":material/logout:"):
        cerrar_sesion()
        st.rerun()


def cerrar_sesion() -> None:
    """Quita el actor y el estado de las páginas (claves con prefijo de página)."""
    prefijos = ("donante_", "receptor_", "recolector_", "coordinador_", "sesion_")
    for clave in list(st.session_state):
        if clave == CLAVE_ACTOR or str(clave).startswith(prefijos):
            del st.session_state[clave]
