"""Página del recolector (flujo 2).

DUEÑO: Alejandro. FASE 0: solo lista lo disponible. La tarea A6 agrega recoger y entregar.
"""
from __future__ import annotations

import streamlit as st

from rescate.dominio.modelos import Participante
from rescate.servicios import ServicioDonativos
from ui.comun import tarjeta_donativo


def mostrar(servicio: ServicioDonativos, participante: Participante | None) -> None:
    st.header("Recolecciones")
    if participante is None:
        st.info("Elige un recolector en la barra lateral.")
        return
    st.info("Página en construcción (tarea A6).")
    for donativo in servicio.disponibles_para_recolectar():
        tarjeta_donativo(servicio, donativo, mostrar_bitacora=False)
