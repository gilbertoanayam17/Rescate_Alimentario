"""Componentes de interfaz que comparten todas las páginas.

Archivo COMPARTIDO (fase 0). Agregar componentes nuevos está bien; si cambias uno
existente, avisa al otro integrante.
"""
from __future__ import annotations

import streamlit as st

from rescate.dominio.enums import Dictamen, EstadoDonativo, TipoEntradaBitacora
from rescate.dominio.modelos import Donativo, EntradaBitacora
from rescate.servicios import ServicioDonativos

ETIQUETA_ESTADO = {
    EstadoDonativo.PUBLICADO: ("Publicado", "gray"),
    EstadoDonativo.EVALUADO: ("Evaluado", "blue"),
    EstadoDonativo.ASIGNADO: ("Asignado", "violet"),
    EstadoDonativo.EN_RECOLECCION: ("En recolección", "orange"),
    EstadoDonativo.ENTREGADO: ("Entregado", "green"),
    EstadoDonativo.RECHAZADO: ("No apto", "red"),
    EstadoDonativo.EXPIRADO: ("Expirado", "gray"),
    EstadoDonativo.CANCELADO: ("Cancelado", "gray"),
}

ETIQUETA_DICTAMEN = {
    Dictamen.APTO: ("Apto", "green"),
    Dictamen.APTO_CON_CONDICIONES: ("Apto con condiciones", "orange"),
    Dictamen.NO_APTO: ("No apto", "red"),
}

ICONO_BITACORA = {
    TipoEntradaBitacora.PENSAMIENTO: "💭",
    TipoEntradaBitacora.ACCION: "🛠️",
    TipoEntradaBitacora.OBSERVACION: "👀",
    TipoEntradaBitacora.RESULTADO: "✅",
    TipoEntradaBitacora.ERROR: "⚠️",
}


def insignia_estado(estado: EstadoDonativo) -> str:
    texto, color = ETIQUETA_ESTADO[estado]
    return f":{color}[**● {texto}**]"


def insignia_dictamen(dictamen: Dictamen) -> str:
    texto, color = ETIQUETA_DICTAMEN[dictamen]
    return f":{color}[**{texto}**]"


def tarjeta_donativo(servicio: ServicioDonativos, donativo: Donativo, mostrar_bitacora: bool = True) -> None:
    """Resumen de un donativo: alimentos, estado, dictamen, asignación y bitácora."""
    with st.container(border=True):
        st.markdown(f"**{donativo.resumen()}**  {insignia_estado(donativo.estado)}")
        donante = servicio.participante(donativo.donante_id)
        st.caption(
            f"{donante.nombre if donante else donativo.donante_id} · {donativo.kg_totales} kg · "
            f"publicado {donativo.creado:%d/%m %H:%M} · id {donativo.id}"
        )
        if donativo.dictamen:
            d = donativo.dictamen
            st.markdown(f"Inocuidad: {insignia_dictamen(d.dictamen)} — {d.motivo}")
            for condicion in d.condiciones:
                st.markdown(f"- {condicion}")
            if d.reglas_citadas:
                st.caption("Fundamento: " + "; ".join(d.reglas_citadas))
        if donativo.asignacion:
            a = donativo.asignacion
            receptor = servicio.participante(a.receptor_id)
            if receptor:
                aceptada = " (aceptado)" if a.aceptada else " (por confirmar)"
                st.markdown(f"Receptor: **{receptor.nombre}**{aceptada}")
            st.caption(a.justificacion)
        if mostrar_bitacora:
            with st.expander("¿Cómo lo decidieron los agentes?"):
                vista_bitacora(servicio.bitacora_de(donativo.id))


def vista_bitacora(entradas: list[EntradaBitacora]) -> None:
    if not entradas:
        st.caption("Sin entradas en la bitácora.")
        return
    for e in entradas:
        icono = ICONO_BITACORA.get(e.tipo, "•")
        st.markdown(f"{icono} **{e.agente}** · _{e.tipo.value}_ — {e.contenido}")


def historial_estados(servicio: ServicioDonativos, donativo_id: str) -> None:
    for h in servicio.historial(donativo_id):
        anterior = h["anterior"] or "—"
        st.caption(f"{h['fecha']:%d/%m %H:%M} · {anterior} → {h['nuevo']} ({h['evento']}) {h['motivo'] or ''}")
