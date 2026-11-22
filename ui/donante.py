"""Página del donante (flujo 1): publica en lenguaje natural y ve qué decidieron los agentes.

DUEÑO: Gilberto (tarea G4). CAR-01, CAR-05, CAR-07 y CAR-11.

El donante escribe en un chat lo que le sobró. Si el Agente Intérprete necesita un dato,
el asistente pregunta y la respuesta se manda como aclaración del MISMO donativo
(`texto + MARCA_ACLARACION + respuesta`). Al completarse se muestran los alimentos, el
dictamen de inocuidad con su fundamento, la asignación y la bitácora de los agentes.

Arriba del chat se muestran los pronósticos del día (Agente Predictor): "Publicar ahora" manda
al chat una frase armada con el pronóstico y "Hoy no" lo descarta. La página nunca decide
permisos: los servicios validan el actor y las reglas (por ejemplo, cancelar).
"""

from __future__ import annotations

from datetime import timedelta

import streamlit as st

from rescate.agentes.interprete import MARCA_ACLARACION
from rescate.dominio.enums import EstadoDonativo, EstadoPronostico, TipoAlimento
from rescate.dominio.modelos import Actor, Donativo, EntradaBitacora, Participante, ahora
from rescate.servicios import ErrorServicio, Servicios
from ui.componentes_prediccion import frase_sugerida, tarjeta_pronostico
from ui.comun import (
    historial_estados,
    insignia_dictamen,
    metricas_impacto,
    tarjeta_donativo,
    vista_bitacora,
)

AVISO_NO_CERTIFICA = (
    "Rescate Alimentario orienta sobre inocuidad con base en la NOM-251; no certifica el alimento. "
    "La responsabilidad sigue siendo del comercio."
)

EJEMPLOS = {
    "🥖 Bolillos y jitomate": "Me sobraron 15 bolillos y 5 kg de jitomate",
    "🍗 Pollo en mole": "Tengo 2 charolas de pollo en mole",
    "🥛 Leche que quedó afuera": "Me quedaron 3 litros de leche que dejé afuera desde la mañana",
}
NOMBRE_TIPO = {
    TipoAlimento.PREPARADO: "Preparado",
    TipoAlimento.PANADERIA: "Panadería",
    TipoAlimento.FRUTA_VERDURA: "Fruta y verdura",
    TipoAlimento.LACTEO: "Lácteo",
    TipoAlimento.CARNE_PESCADO: "Carne o pescado",
    TipoAlimento.ABARROTE: "Abarrote",
    TipoAlimento.BEBIDA: "Bebida",
    TipoAlimento.OTRO: "Otro",
}
CANCELABLES = {EstadoDonativo.PUBLICADO, EstadoDonativo.EVALUADO, EstadoDonativo.ASIGNADO}
EN_CURSO = {*CANCELABLES, EstadoDonativo.EN_RECOLECCION}
#: Orden del flujo del orquestador; desempata entradas de la bitácora anotadas en el mismo segundo.
ORDEN_AGENTES = {"Intérprete": 0, "Inocuidad": 1, "Asignador": 2}


def bitacora_en_orden(entradas: list[EntradaBitacora]) -> list[EntradaBitacora]:
    """La bitácora guarda la fecha al segundo; dentro de un mismo segundo se respeta el orden del flujo."""
    return sorted(entradas, key=lambda e: (e.fecha, ORDEN_AGENTES.get(e.agente, len(ORDEN_AGENTES)), e.paso))


def mostrar(servicios: Servicios, actor: Actor | None) -> None:
    st.header("Publica lo que te sobró")
    st.caption("Escríbelo como se lo dirías a un amigo. Nosotros nos encargamos del resto.")
    participante = servicios.participantes.obtener(actor.participante_id) if actor else None
    if participante is None:
        st.info("Elige un donante en la barra lateral.")
        return

    clave_chat = f"donante_chat_{participante.id}"
    clave_pendiente = f"donante_pendiente_{participante.id}"
    chat: list[dict] = st.session_state.setdefault(clave_chat, [])

    sugerida = _pronosticos_del_dia(servicios, actor)
    ejemplo = _ejemplos_rapidos() or sugerida

    with st.chat_message("assistant"):
        st.markdown(
            f"Hola, **{participante.nombre}**. Cuéntame qué te sobró hoy y cuánto; "
            "si me falta algún dato, te pregunto."
        )
    for mensaje in chat:
        with st.chat_message(mensaje["rol"]):
            _contenido(servicios, actor, mensaje)

    escrito = st.chat_input("¿Qué te sobró hoy?", key=f"donante_entrada_{participante.id}")
    st.caption(f"ℹ️ {AVISO_NO_CERTIFICA}")
    if ejemplo:  # un ejemplo o un pronóstico siempre empieza un donativo nuevo
        st.session_state.pop(clave_pendiente, None)
    texto = escrito or ejemplo
    if texto:
        _conversar(servicios, actor, participante, texto, chat, clave_pendiente)

    if st.session_state.get(clave_pendiente):
        if st.button(
            "Empezar de nuevo", key=f"donante_reiniciar_{participante.id}", help="Descarta lo pendiente"
        ):
            st.session_state.pop(clave_pendiente, None)
            st.session_state[clave_chat] = []
            st.rerun()

    _mis_donativos(servicios, actor, participante)


# ---------------------------------------------------------------- pronósticos


def _pronosticos_del_dia(servicios: Servicios, actor: Actor) -> str | None:
    """Tarjetas de los pronósticos vigentes de hoy. Regresa la frase para el chat si se pulsó
    "Publicar ahora"; "Hoy no" descarta el pronóstico."""
    try:
        with st.spinner("Revisando tus pronósticos de hoy..."):
            pronosticos = servicios.prediccion.pronosticos_para_donante(actor)
    except ErrorServicio as e:
        st.warning(f"No pude calcular tus pronósticos: {e}")
        return None
    if not pronosticos:
        return None
    zona = st.empty()
    frase, pulsado = None, False
    with zona.container():
        for pronostico in pronosticos:
            receptor = (
                servicios.participantes.obtener(pronostico.receptor_sugerido_id)
                if pronostico.receptor_sugerido_id
                else None
            )
            accion = tarjeta_pronostico(
                pronostico,
                nombre_receptor=receptor.nombre if receptor else None,
                acciones=True,
                clave=pronostico.id,
            )
            if accion is None or pulsado:
                continue
            pulsado = True
            estado = EstadoPronostico.PUBLICADO if accion == "publicar" else EstadoPronostico.DESCARTADO
            try:
                servicios.prediccion.marcar(actor, pronostico.id, estado)
            except ErrorServicio as e:
                st.error(str(e))
                return None
            if accion == "publicar":
                frase = frase_sugerida(pronostico)
    if pulsado:
        zona.empty()  # la tarjeta pulsada ya no está vigente
        if frase is None:
            st.toast("Listo, hoy no te lo recordamos más.")
            st.rerun()
    return frase


# ---------------------------------------------------------------------- chat


def _ejemplos_rapidos() -> str | None:
    st.caption("Ejemplos rápidos")
    columnas = st.columns(len(EJEMPLOS))
    for columna, (etiqueta, texto) in zip(columnas, EJEMPLOS.items()):
        if columna.button(etiqueta, key=f"donante_ejemplo_{etiqueta}", width="stretch", help=texto):
            return texto
    return None


def _conversar(
    servicios: Servicios,
    actor: Actor,
    participante: Participante,
    texto: str,
    chat: list[dict],
    clave_pendiente: str,
) -> None:
    """Manda el mensaje al servicio: nuevo donativo o aclaración del pendiente."""
    pendiente = st.session_state.get(clave_pendiente)
    chat.append({"rol": "user", "tipo": "texto", "contenido": texto})
    with st.chat_message("user"):
        st.markdown(texto)

    texto_completo = f"{pendiente['texto']}{MARCA_ACLARACION}{texto}" if pendiente else texto
    with st.chat_message("assistant"):
        try:
            with st.spinner("Los agentes están revisando tu donativo..."):
                resultado = servicios.publicacion.publicar(
                    actor, texto_completo, pendiente["donativo_id"] if pendiente else None
                )
        except ErrorServicio as e:
            mensaje = {"rol": "assistant", "tipo": "error", "contenido": str(e)}
        else:
            if resultado.completo:
                st.session_state.pop(clave_pendiente, None)
                mensaje = {
                    "rol": "assistant",
                    "tipo": "resultado",
                    "contenido": resultado.mensaje,
                    "donativo_id": resultado.donativo.id,
                }
            else:
                st.session_state[clave_pendiente] = {
                    "donativo_id": resultado.donativo_id,
                    "texto": texto_completo,
                }
                mensaje = {"rol": "assistant", "tipo": "pregunta", "contenido": " ".join(resultado.preguntas)}
        chat.append(mensaje)
        _contenido(servicios, actor, mensaje)


def _contenido(servicios: Servicios, actor: Actor, mensaje: dict) -> None:
    if mensaje["tipo"] == "error":
        st.error(mensaje["contenido"])
        return
    if mensaje["tipo"] != "resultado":
        st.markdown(mensaje["contenido"])
        return
    donativo = servicios.reportes.donativo(actor, mensaje["donativo_id"])
    if donativo is None:  # p. ej., la base se reinició
        st.markdown(mensaje["contenido"])
        return
    _resultado(servicios, actor, donativo, mensaje["contenido"])


def _resultado(servicios: Servicios, actor: Actor, donativo: Donativo, mensaje: str) -> None:
    if donativo.estado == EstadoDonativo.RECHAZADO:
        st.info("Gracias por avisar; por seguridad este alimento no se puede donar.")
    else:
        st.success(mensaje)

    st.dataframe(
        [
            {
                "Alimento": a.nombre,
                "Cantidad": a.cantidad,
                "Unidad": a.unidad,
                "Tipo": NOMBRE_TIPO.get(a.tipo, a.tipo.value),
                "Kg estimados": a.kg_estimados,
            }
            for a in donativo.alimentos
        ],
        hide_index=True,
        width="stretch",
    )
    st.caption(f"Total estimado: **{donativo.kg_totales:g} kg** (lo calcula el sistema, no el modelo)")

    if donativo.dictamen:
        d = donativo.dictamen
        st.markdown(f"**Inocuidad:** {insignia_dictamen(d.dictamen)} — {d.motivo}")
        for condicion in d.condiciones:
            st.markdown(f"- {condicion}")
        if d.reglas_citadas:
            st.caption("Fundamento: " + "; ".join(d.reglas_citadas))

    if donativo.estado != EstadoDonativo.RECHAZADO and donativo.asignacion:
        a = donativo.asignacion
        receptor = servicios.participantes.obtener(a.receptor_id)
        if receptor:
            st.markdown(f"**Receptor:** {receptor.nombre}")
        elif a.requiere_coordinador:
            st.markdown("**Receptor:** aún no hay un comedor disponible; el coordinador lo revisará.")
        if a.justificacion:
            st.caption(a.justificacion)

    with st.expander("¿Cómo lo decidieron los agentes?"):
        vista_bitacora(bitacora_en_orden(servicios.reportes.bitacora_de(actor, donativo.id)))


# --------------------------------------------------------------- mis donativos


def _mis_donativos(servicios: Servicios, actor: Actor, participante: Participante) -> None:
    _mi_impacto(servicios, actor)
    st.subheader("Mis donativos")
    donativos = servicios.publicacion.donativos_de_donante(actor)
    if not donativos:
        st.caption("Aún no has publicado donativos.")
        return
    en_curso = [d for d in donativos if d.estado in EN_CURSO]
    terminados = [d for d in donativos if d.estado not in EN_CURSO]
    st.markdown(f"**En curso ({len(en_curso)})**")
    if not en_curso:
        st.caption("No tienes donativos en curso.")
    for donativo in en_curso:
        _donativo(servicios, actor, donativo)
    if terminados:
        with st.expander(f"Terminados ({len(terminados)})"):
            for donativo in terminados:
                _donativo(servicios, actor, donativo)


def _mi_impacto(servicios: Servicios, actor: Actor) -> None:
    """Kg entregados, raciones y CO2e del donante en los últimos 12 meses (tarea A3)."""
    hoy = ahora().date()
    st.subheader("Mi impacto (últimos 12 meses)")
    metricas_impacto(servicios.reportes.tablero(actor, hoy - timedelta(days=365), hoy))


def _donativo(servicios: Servicios, actor: Actor, donativo: Donativo) -> None:
    """Una tarjeta de "Mis donativos" con sus acciones. La constancia en PDF (tarea A4) va aquí,
    junto a los botones de cada donativo entregado."""
    tarjeta_donativo(servicios, actor, donativo)
    with st.expander("Historial de estados"):
        historial_estados(servicios, actor, donativo.id)
    aceptado = bool(donativo.asignacion and donativo.asignacion.aceptada)
    puede_cancelar = donativo.estado in CANCELABLES and not aceptado  # la regla la valida el servicio
    if puede_cancelar and st.button("Cancelar", key=f"donante_cancelar_{donativo.id}"):
        try:
            servicios.publicacion.cancelar(actor, donativo.id)
        except ErrorServicio as e:
            st.error(str(e))
        else:
            st.toast("Donativo cancelado")
            st.rerun()
