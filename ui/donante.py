"""Página del donante (flujo 1).

DUEÑO: Gilberto. FASE 0: formulario mínimo para que la app funcione de punta a punta.
La tarea G5 la convierte en un chat con aclaraciones, dictamen y bitácora.
"""
from __future__ import annotations

import streamlit as st

from rescate.dominio.modelos import Participante
from rescate.servicios import ErrorServicio, ServicioDonativos
from ui.comun import tarjeta_donativo


def mostrar(servicio: ServicioDonativos, participante: Participante | None) -> None:
    st.header("Publicar excedente")
    if participante is None:
        st.info("Elige un donante en la barra lateral.")
        return

    texto = st.text_area("¿Qué te sobró hoy?", placeholder="Me sobraron 15 bolillos y 3 kg de arroz")
    if st.button("Publicar", type="primary"):
        try:
            with st.spinner("Los agentes están trabajando..."):
                resultado = servicio.publicar(texto, participante.id)
        except ErrorServicio as e:
            st.error(str(e))
        else:
            if not resultado.completo:
                st.warning(" ".join(resultado.preguntas))
            else:
                st.success(resultado.mensaje)

    st.subheader("Mis donativos")
    donativos = servicio.donativos_de_donante(participante.id)
    if not donativos:
        st.caption("Aún no has publicado donativos.")
    for donativo in donativos:
        tarjeta_donativo(servicio, donativo)
