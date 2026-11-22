"""Tarjeta de pronóstico (CAR-07). La usan la página del donante (con acciones) y las del
receptor y el coordinador (sin acciones). Dueño: Gilberto.
"""
from __future__ import annotations

import streamlit as st

from rescate.dominio.modelos import Pronostico
from rescate.herramientas.compatibilidad import NOMBRE_TIPO
from rescate.herramientas.patrones import DIAS_PLURAL


def frase_sugerida(pronostico: Pronostico) -> str:
    """El texto que se manda al chat del donante con "Publicar ahora"."""
    return f"Me sobraron unos {pronostico.kg_esperados:g} kg de {pronostico.descripcion}"


def tarjeta_pronostico(
    pronostico: Pronostico,
    nombre_donante: str | None = None,
    nombre_receptor: str | None = None,
    acciones: bool = False,
    clave: str = "",
) -> str | None:
    """Dibuja el pronóstico. Con acciones=True muestra "Publicar ahora" y "Hoy no" y regresa
    "publicar" o "descartar" si se pulsó; si no, None."""
    tipo = NOMBRE_TIPO.get(pronostico.tipo, pronostico.tipo.value)
    dia = DIAS_PLURAL[pronostico.fecha.weekday()]
    with st.container(border=True):
        titulo = f"🔮 **Pronóstico para hoy**{f' · {nombre_donante}' if nombre_donante else ''}"
        st.markdown(titulo)
        st.write(pronostico.mensaje)
        detalle = (
            f"{tipo.capitalize()} · unos {pronostico.kg_esperados:g} kg · "
            f"confianza {pronostico.confianza:.0%} (los {dia} de las últimas semanas)"
        )
        if nombre_receptor:
            detalle += f" · pre-reservado para {nombre_receptor}"
        st.caption(detalle)
        if not acciones:
            return None
        izquierda, derecha = st.columns(2)
        clave = clave or pronostico.id
        if izquierda.button("Publicar ahora", key=f"pronostico_publicar_{clave}", type="primary"):
            return "publicar"
        if derecha.button("Hoy no", key=f"pronostico_descartar_{clave}"):
            return "descartar"
    return None
