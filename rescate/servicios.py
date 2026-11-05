"""Fachada (patrón Facade) que usa la interfaz para todo.

La interfaz de Streamlit nunca habla con agentes, repositorios ni estados directamente:
solo con ServicioDonativos. Aquí se aplican las transiciones del ciclo de vida (CAR-05)
y se guarda el historial.

Archivo COMPARTIDO (fase 0). Si necesitas un método nuevo, agrégalo (no cambies los existentes)
en un PR aparte con prefijo "contrato:".
"""
from __future__ import annotations

from pydantic import BaseModel

from rescate.bitacora import Bitacora
from rescate.dominio.enums import Dictamen, EstadoDonativo, Evento, Rol
from rescate.dominio.estados import TransicionInvalida, aplicar_evento
from rescate.dominio.modelos import (
    Asignacion,
    Donante,
    Donativo,
    EntradaBitacora,
    Participante,
    SolicitudInterpretacion,
    nuevo_id,
)
from rescate.llm.cliente import ClienteLLM
from rescate.orquestador import Orquestador
from rescate.persistencia.repositorios import RepositorioDonativos, RepositorioParticipantes


class ErrorServicio(Exception):
    """Error de uso que la interfaz debe mostrar al usuario."""


class ResultadoPublicacion(BaseModel):
    donativo_id: str
    completo: bool
    preguntas: list[str] = []
    donativo: Donativo | None = None
    mensaje: str = ""


class ServicioDonativos:
    def __init__(
        self,
        orquestador: Orquestador,
        participantes: RepositorioParticipantes,
        donativos: RepositorioDonativos,
        bitacora: Bitacora,
        llm: ClienteLLM,
    ) -> None:
        self.orquestador = orquestador
        self.repo_participantes = participantes
        self.repo_donativos = donativos
        self.bitacora = bitacora
        self.llm = llm

    # ============================================== participantes (CAR-09)

    def participantes(self, rol: Rol | None = None) -> list[Participante]:
        return self.repo_participantes.listar(rol)

    def participante(self, participante_id: str | None) -> Participante | None:
        return self.repo_participantes.obtener(participante_id) if participante_id else None

    def registrar_participante(self, participante: Participante) -> Participante:
        """Alta o edición (mismo id = edición)."""
        if not participante.nombre.strip():
            raise ErrorServicio("El nombre es obligatorio.")
        self.repo_participantes.guardar(participante)
        return participante

    def eliminar_participante(self, participante_id: str) -> None:
        self.repo_participantes.eliminar(participante_id)

    # ====================================== flujo 1: publicar y evaluar

    def publicar(self, texto: str, donante_id: str, donativo_id: str | None = None) -> ResultadoPublicacion:
        """Corre interpretar -> evaluar -> asignar.

        Si el Intérprete necesita datos, regresa `completo=False` con `preguntas`; la interfaz
        vuelve a llamar con el texto original + la respuesta y el MISMO `donativo_id`.
        """
        donante = self.repo_participantes.obtener(donante_id)
        if not isinstance(donante, Donante):
            raise ErrorServicio("Selecciona un donante válido.")
        if not texto.strip():
            raise ErrorServicio("Describe lo que te sobró.")

        solicitud = SolicitudInterpretacion(texto=texto, donante=donante, donativo_id=donativo_id or nuevo_id())
        estado = self.orquestador.procesar(solicitud, self.repo_participantes.receptores())
        interpretacion = estado["interpretacion"]
        if not interpretacion.completo:
            return ResultadoPublicacion(
                donativo_id=solicitud.donativo_id,
                completo=False,
                preguntas=interpretacion.preguntas,
                mensaje="Necesito un dato más para publicar tu donativo.",
            )

        donativo: Donativo = estado["donativo"]
        self.repo_donativos.guardar(donativo)
        self.repo_donativos.registrar_transicion(
            donativo.id, None, EstadoDonativo.PUBLICADO, "publicar", "Publicado por el donante"
        )

        dictamen = estado["dictamen"]
        evento = Evento.EVALUAR_NO_APTO if dictamen.dictamen == Dictamen.NO_APTO else Evento.EVALUAR_APTO
        self._transicionar(donativo, evento, dictamen.motivo)

        if "asignacion" in estado:
            self._aplicar_asignacion(donativo, estado["asignacion"])

        return ResultadoPublicacion(
            donativo_id=donativo.id, completo=True, donativo=donativo, mensaje=self._mensaje(donativo)
        )

    def donativos_de_donante(self, donante_id: str) -> list[Donativo]:
        return self.repo_donativos.de_donante(donante_id)

    def cancelar(self, donativo_id: str, motivo: str = "Cancelado por el donante") -> Donativo:
        donativo = self._obtener(donativo_id)
        self._transicionar(donativo, Evento.CANCELAR, motivo)
        return donativo

    # ===================================== flujo 2: asignar y entregar

    def donativos_de_receptor(self, receptor_id: str) -> list[Donativo]:
        return self.repo_donativos.de_receptor(receptor_id)

    def aceptar_asignacion(self, donativo_id: str, receptor_id: str) -> Donativo:
        donativo = self._obtener(donativo_id)
        if donativo.estado != EstadoDonativo.ASIGNADO or donativo.receptor_id != receptor_id:
            raise ErrorServicio("Este donativo no está asignado a tu organización.")
        donativo.asignacion.aceptada = True
        self.repo_donativos.guardar(donativo)
        self.repo_donativos.registrar_transicion(
            donativo.id, donativo.estado, donativo.estado, "aceptar", "El receptor aceptó"
        )
        return donativo

    def rechazar_asignacion(self, donativo_id: str, receptor_id: str, motivo: str = "") -> Donativo:
        """El receptor no lo puede recibir: se libera y se reasigna a otro automáticamente."""
        donativo = self._obtener(donativo_id)
        if donativo.estado != EstadoDonativo.ASIGNADO or donativo.receptor_id != receptor_id:
            raise ErrorServicio("Este donativo no está asignado a tu organización.")
        donativo.receptores_descartados.append(receptor_id)
        self._transicionar(donativo, Evento.LIBERAR, motivo or "El receptor rechazó la asignación")
        return self.reintentar_asignacion(donativo.id)

    def reintentar_asignacion(self, donativo_id: str) -> Donativo:
        """Vuelve a correr el Asignador (lo usa el coordinador para casos sin receptor)."""
        donativo = self._obtener(donativo_id)
        if donativo.estado != EstadoDonativo.EVALUADO:
            raise ErrorServicio("Solo se pueden reasignar donativos evaluados sin receptor.")
        donante = self.repo_participantes.obtener(donativo.donante_id)
        asignacion = self.orquestador.asignar(donativo, donante, self.repo_participantes.receptores())
        self._aplicar_asignacion(donativo, asignacion)
        return donativo

    def disponibles_para_recolectar(self) -> list[Donativo]:
        return [
            d
            for d in self.repo_donativos.listar(EstadoDonativo.ASIGNADO)
            if d.asignacion and d.asignacion.aceptada and d.recolector_id is None
        ]

    def donativos_de_recolector(self, recolector_id: str) -> list[Donativo]:
        return self.repo_donativos.de_recolector(recolector_id)

    def iniciar_recoleccion(self, donativo_id: str, recolector_id: str) -> Donativo:
        donativo = self._obtener(donativo_id)
        if not (donativo.asignacion and donativo.asignacion.aceptada):
            raise ErrorServicio("El receptor aún no acepta este donativo.")
        donativo.recolector_id = recolector_id
        self._transicionar(donativo, Evento.INICIAR_RECOLECCION, "Recolector en camino")
        return donativo

    def confirmar_entrega(self, donativo_id: str, recolector_id: str) -> Donativo:
        donativo = self._obtener(donativo_id)
        if donativo.recolector_id != recolector_id:
            raise ErrorServicio("Este donativo lo lleva otro recolector.")
        self._transicionar(donativo, Evento.ENTREGAR, "Entregado al receptor")
        return donativo

    # ============================================== consultas generales

    def donativo(self, donativo_id: str) -> Donativo | None:
        return self.repo_donativos.obtener(donativo_id)

    def todos(self, estado: EstadoDonativo | None = None) -> list[Donativo]:
        return self.repo_donativos.listar(estado)

    def historial(self, donativo_id: str) -> list[dict]:
        return self.repo_donativos.historial(donativo_id)

    def bitacora_de(self, donativo_id: str) -> list[EntradaBitacora]:
        return self.bitacora.de_donativo(donativo_id)

    def bitacora_reciente(self, limite: int = 200) -> list[EntradaBitacora]:
        return self.bitacora.recientes(limite)

    def estado_llm(self) -> str:
        if self.llm.disponible():
            return f"LLM local: {self.llm.nombre_modelo}"
        return "Sin LLM: los agentes usan sus reglas de respaldo"

    # ========================================================== internos

    def _obtener(self, donativo_id: str) -> Donativo:
        donativo = self.repo_donativos.obtener(donativo_id)
        if donativo is None:
            raise ErrorServicio(f"No existe el donativo {donativo_id}.")
        return donativo

    def _transicionar(self, donativo: Donativo, evento: Evento, motivo: str = "") -> None:
        try:
            anterior, nuevo = aplicar_evento(donativo, evento)
        except TransicionInvalida as e:
            raise ErrorServicio(str(e)) from e
        self.repo_donativos.guardar(donativo)
        self.repo_donativos.registrar_transicion(donativo.id, anterior, nuevo, evento, motivo)

    def _aplicar_asignacion(self, donativo: Donativo, asignacion: Asignacion) -> None:
        donativo.asignacion = asignacion
        if asignacion.receptor_id:
            self._transicionar(donativo, Evento.ASIGNAR, asignacion.justificacion)
        else:  # queda EVALUADO; el coordinador lo ve en "Sin receptor"
            self.repo_donativos.guardar(donativo)

    def _mensaje(self, donativo: Donativo) -> str:
        if donativo.estado == EstadoDonativo.RECHAZADO:
            return "Gracias por avisar. Por seguridad, este alimento no se puede donar."
        if donativo.estado == EstadoDonativo.ASIGNADO:
            receptor = self.repo_participantes.obtener(donativo.receptor_id)
            nombre = receptor.nombre if receptor else "un receptor"
            return f"¡Listo! Tu donativo se asignó a {nombre}."
        return "Tu donativo está publicado; un coordinador buscará quién lo reciba."
