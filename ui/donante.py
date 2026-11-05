"""Página del donante (flujo 1): publica en lenguaje natural y ve qué decidieron los agentes.

DUEÑO: Gilberto (tarea G5). CAR-01, CAR-05 y CAR-11.

El donante escribe en un chat lo que le sobró. Si el Agente Intérprete necesita un dato,
el asistente pregunta y la respuesta se manda como aclaración del MISMO donativo
(`texto + MARCA_ACLARACION + respuesta`). Al completarse se muestran los alimentos, el
dictamen de inocuidad con su fundamento, la asignación y la bitácora de los agentes.
"""

from __future__ import annotations

import streamlit as st

from rescate.agentes.interprete import MARCA_ACLARACION
from rescate.dominio.enums import EstadoDonativo, TipoAlimento
from rescate.dominio.modelos import Donativo, EntradaBitacora, Participante
from rescate.servicios import ErrorServicio, ServicioDonativos
from ui.comun import historial_estados, insignia_dictamen, tarjeta_donativo, vista_bitacora

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
#: Orden del flujo del orquestador; desempata entradas de la bitácora anotadas en el mismo segundo.
ORDEN_AGENTES = {"Intérprete": 0, "Inocuidad": 1, "Asignador": 2}


def bitacora_en_orden(entradas: list[EntradaBitacora]) -> list[EntradaBitacora]:
    """La bitácora guarda la fecha al segundo; dentro de un mismo segundo se respeta el orden del flujo."""
    return sorted(entradas, key=lambda e: (e.fecha, ORDEN_AGENTES.get(e.agente, len(ORDEN_AGENTES)), e.paso))


def mostrar(servicio: ServicioDonativos, participante: Participante | None) -> None:
    st.header("Publica lo que te sobró")
    st.caption("Escríbelo como se lo dirías a un amigo. Nosotros nos encargamos del resto.")
    if participante is None:
        st.info("Elige un donante en la barra lateral.")
        return

    clave_chat = f"donante_chat_{participante.id}"
    clave_pendiente = f"donante_pendiente_{participante.id}"
    chat: list[dict] = st.session_state.setdefault(clave_chat, [])

    ejemplo = _ejemplos_rapidos()

    with st.chat_message("assistant"):
        st.markdown(
            f"Hola, **{participante.nombre}**. Cuéntame qué te sobró hoy y cuánto; "
            "si me falta algún dato, te pregunto."
        )
    for mensaje in chat:
        with st.chat_message(mensaje["rol"]):
            _contenido(servicio, mensaje)

    escrito = st.chat_input("¿Qué te sobró hoy?", key=f"donante_entrada_{participante.id}")
    if ejemplo:  # un ejemplo siempre empieza un donativo nuevo
        st.session_state.pop(clave_pendiente, None)
    texto = escrito or ejemplo
    if texto:
        _conversar(servicio, participante, texto, chat, clave_pendiente)

    if st.session_state.get(clave_pendiente):
        if st.button(
            "Empezar de nuevo", key=f"donante_reiniciar_{participante.id}", help="Descarta lo pendiente"
        ):
            st.session_state.pop(clave_pendiente, None)
            st.session_state[clave_chat] = []
            st.rerun()

    _mis_donativos(servicio, participante)


# ---------------------------------------------------------------------- chat


def _ejemplos_rapidos() -> str | None:
    st.caption("Ejemplos rápidos")
    columnas = st.columns(len(EJEMPLOS))
    for columna, (etiqueta, texto) in zip(columnas, EJEMPLOS.items()):
        if columna.button(etiqueta, key=f"donante_ejemplo_{etiqueta}", width="stretch", help=texto):
            return texto
    return None


def _conversar(
    servicio: ServicioDonativos,
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
                resultado = servicio.publicar(
                    texto_completo, participante.id, pendiente["donativo_id"] if pendiente else None
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
        _contenido(servicio, mensaje)


def _contenido(servicio: ServicioDonativos, mensaje: dict) -> None:
    if mensaje["tipo"] == "error":
        st.error(mensaje["contenido"])
        return
    if mensaje["tipo"] != "resultado":
        st.markdown(mensaje["contenido"])
        return
    donativo = servicio.donativo(mensaje["donativo_id"])
    if donativo is None:  # p. ej., la base se reinició
        st.markdown(mensaje["contenido"])
        return
    _resultado(servicio, donativo, mensaje["contenido"])


def _resultado(servicio: ServicioDonativos, donativo: Donativo, mensaje: str) -> None:
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
        receptor = servicio.participante(a.receptor_id)
        if receptor:
            st.markdown(f"**Receptor:** {receptor.nombre}")
        elif a.requiere_coordinador:
            st.markdown("**Receptor:** aún no hay un comedor disponible; el coordinador lo revisará.")
        if a.justificacion:
            st.caption(a.justificacion)

    with st.expander("¿Cómo lo decidieron los agentes?"):
        vista_bitacora(bitacora_en_orden(servicio.bitacora_de(donativo.id)))


# --------------------------------------------------------------- mis donativos


def _mis_donativos(servicio: ServicioDonativos, participante: Participante) -> None:
    st.subheader("Mis donativos")
    donativos = servicio.donativos_de_donante(participante.id)
    if not donativos:
        st.caption("Aún no has publicado donativos.")
        return
    for donativo in donativos:
        tarjeta_donativo(servicio, donativo)
        with st.expander("Historial de estados"):
            historial_estados(servicio, donativo.id)
        aceptado = bool(donativo.asignacion and donativo.asignacion.aceptada)
        if donativo.estado in CANCELABLES and not aceptado:
            if st.button("Cancelar", key=f"donante_cancelar_{donativo.id}"):
                try:
                    servicio.cancelar(donativo.id)
                except ErrorServicio as e:
                    st.error(str(e))
                else:
                    st.toast("Donativo cancelado")
                    st.rerun()
