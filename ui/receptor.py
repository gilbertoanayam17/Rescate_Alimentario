"""Página del receptor (flujo 2).

DUEÑO: Alejandro. FASE 0: solo lista lo asignado. La tarea A5 agrega perfil, aceptar/rechazar
y recibidos.
"""
from __future__ import annotations

import streamlit as st

from rescate.dominio.modelos import Participante
from rescate.servicios import ServicioDonativos
from ui.comun import tarjeta_donativo


def mostrar(servicio: ServicioDonativos, participante: Participante | None) -> None:
    st.header("Donativos para mi organización")
    if participante is None:
        st.info("Elige un receptor en la barra lateral.")
        return
    st.info("Página en construcción (tarea A5).")
    for donativo in servicio.donativos_de_receptor(participante.id):
        tarjeta_donativo(servicio, donativo)
