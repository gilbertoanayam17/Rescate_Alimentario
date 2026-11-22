"""Errores de uso que la interfaz muestra al usuario."""


class ErrorServicio(Exception):
    """Error de uso que la interfaz debe mostrar (st.error)."""


class ErrorAutorizacion(ErrorServicio):
    """El actor no tiene el rol o la propiedad que la operación exige."""
