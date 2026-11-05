"""Página del coordinador (flujo 2).

DUEÑO: Alejandro. FASE 0: lista de donativos y bitácora reciente. La tarea A7 agrega
participantes (CAR-09), casos sin receptor y métricas.
"""
from __future__ import annotations

import streamlit as st

from rescate.dominio.modelos import Participante
from rescate.servicios import ServicioDonativos
from ui.comun import tarjeta_donativo, vista_bitacora


def mostrar(servicio: ServicioDonativos, participante: Participante | None) -> None:
    st.header("Coordinación")
    st.info("Página en construcción (tarea A7).")
    pestana_donativos, pestana_bitacora = st.tabs(["Donativos", "Bitácora"])
    with pestana_donativos:
        for donativo in servicio.todos():
            tarjeta_donativo(servicio, donativo, mostrar_bitacora=False)
    with pestana_bitacora:
        vista_bitacora(servicio.bitacora_reciente(100))
