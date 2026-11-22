"""Componentes de interfaz que comparten todas las páginas.

Archivo COMPARTIDO (fase 0). Agregar componentes nuevos está bien; si cambias uno
existente, avisa al otro integrante.
"""
from __future__ import annotations

import streamlit as st

from rescate.dominio.enums import Dictamen, EstadoDonativo, TipoEntradaBitacora
from rescate.dominio.modelos import Actor, Donativo, EntradaBitacora
from rescate.servicios import ErrorServicio, Servicios
from rescate.servicios.reportes import TableroImpacto

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


def tarjeta_donativo(
    servicios: Servicios, actor: Actor, donativo: Donativo, mostrar_bitacora: bool = True
) -> None:
    """Resumen de un donativo: alimentos, estado, dictamen, asignación y bitácora."""
    with st.container(border=True):
        st.markdown(f"**{donativo.resumen()}**  {insignia_estado(donativo.estado)}")
        donante = servicios.participantes.obtener(donativo.donante_id)
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
            receptor = servicios.participantes.obtener(a.receptor_id)
            if receptor:
                aceptada = " (aceptado)" if a.aceptada else " (por confirmar)"
                st.markdown(f"Receptor: **{receptor.nombre}**{aceptada}")
            st.caption(a.justificacion)
        if mostrar_bitacora:
            with st.expander("¿Cómo lo decidieron los agentes?"):
                vista_bitacora(servicios.reportes.bitacora_de(actor, donativo.id))


def vista_bitacora(entradas: list[EntradaBitacora]) -> None:
    if not entradas:
        st.caption("Sin entradas en la bitácora.")
        return
    for e in entradas:
        icono = ICONO_BITACORA.get(e.tipo, "•")
        st.markdown(f"{icono} **{e.agente}** · _{e.tipo.value}_ — {e.contenido}")


def historial_estados(servicios: Servicios, actor: Actor, donativo_id: str) -> None:
    for h in servicios.reportes.historial(actor, donativo_id):
        anterior = h["anterior"] or "—"
        st.caption(f"{h['fecha']:%d/%m %H:%M} · {anterior} → {h['nuevo']} ({h['evento']}) {h['motivo'] or ''}")


def panel_avisos(servicios: Servicios, actor: Actor | None) -> None:
    """Avisos del participante en la barra lateral (CAR-06): no leídos arriba."""
    if actor is None:
        return
    try:
        avisos = servicios.notificaciones.avisos(actor)
    except ErrorServicio:
        return
    avisos.sort(key=lambda a: (a.leido, -a.fecha.timestamp()))
    pendientes = sum(not a.leido for a in avisos)
    with st.expander(f"🔔 Avisos ({pendientes})", expanded=pendientes > 0):
        if not avisos:
            st.caption("Sin avisos por ahora.")
        for aviso in avisos:
            marca = "" if aviso.leido else "🔵 "
            st.markdown(f"{marca}**{aviso.titulo}** · {aviso.fecha:%d/%m %H:%M}")
            st.caption(aviso.mensaje)
            if not aviso.leido and st.button(
                "Marcar como leído", key=f"sesion_leido_{aviso.id}"
            ):
                try:
                    servicios.notificaciones.marcar_leido(actor, aviso.id)
                except ErrorServicio as exc:
                    st.error(str(exc))
                st.rerun()


def metricas_impacto(tablero: TableroImpacto) -> None:
    """Las cifras clave del impacto (CAR-08), calculadas por código, con sus fuentes."""
    r = tablero.resumen
    cols = st.columns(4)
    cols[0].metric("Kg rescatados", f"{r.kg:,.1f}")
    cols[1].metric("Raciones equivalentes", f"{r.raciones:,}")
    cols[2].metric("CO2e evitado (kg)", f"{r.co2e_kg:,.1f}")
    cols[3].metric("Donativos entregados", f"{r.donativos:,}")
    st.caption(tablero.fuentes)


def boton_constancia(servicios: Servicios, actor: Actor, donativo: Donativo, prefijo: str) -> None:
    """Descarga de la constancia de entrega (CAR-12). El PDF se genera al hacer clic."""
    st.download_button(
        "Descargar constancia (PDF)",
        data=lambda: servicios.reportes.constancia_pdf(actor, donativo.id),
        file_name=f"constancia_{donativo.id}.pdf",
        mime="application/pdf",
        key=f"{prefijo}_constancia_{donativo.id}",
    )
