"""Ajustes de accesibilidad y legibilidad que el tema de Streamlit no cubre.

Los colores y las fuentes viven en `.streamlit/config.toml`; aquí solo van reglas de
interacción: foco visible con teclado, botones de al menos 44 px, cifras tabulares y
respeto a "reducir movimiento" del sistema operativo.
"""
from __future__ import annotations

import streamlit as st

CSS = """
<style>
/* Foco visible al navegar con teclado (botones, pestañas, campos, enlaces). */
button:focus-visible, [role="tab"]:focus-visible, a:focus-visible,
[data-baseweb="select"]:focus-within, input:focus-visible, textarea:focus-visible {
    outline: 3px solid var(--primary-color, #C2410C) !important;
    outline-offset: 2px !important;
}
/* Área táctil mínima de 44 px y cursor de mano en lo que se puede pulsar. */
.stButton button, .stDownloadButton button, .stFormSubmitButton button {
    min-height: 2.75rem;
    cursor: pointer;
    transition: background-color 180ms ease, border-color 180ms ease, box-shadow 180ms ease;
}
[role="tab"] { min-height: 2.75rem; cursor: pointer; }
/* Cifras que no bailan al cambiar: métricas y tablas. */
[data-testid="stMetricValue"], [data-testid="stDataFrame"] { font-variant-numeric: tabular-nums; }
[data-testid="stMetricValue"] { font-weight: 600; }
/* Quien pidió menos movimiento en su sistema no ve animaciones. */
@media (prefers-reduced-motion: reduce) {
    *, *::before, *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
        scroll-behavior: auto !important;
    }
}
</style>
"""


def aplicar_estilo() -> None:
    """Inyecta las reglas de accesibilidad; se llama una vez por ejecución desde app.py."""
    st.html(CSS)
