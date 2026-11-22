"""Publicar, aclarar y cancelar donativos (CAR-01, CAR-02). Una de las tres partes de SRP."""
from __future__ import annotations

import threading

from pydantic import BaseModel

from rescate.dominio.enums import Dictamen, EstadoDonativo, Evento, Rol, TipoCaso
from rescate.dominio.modelos import (
    Actor,
    Donativo,
    ResultadoInterpretacion,
    SolicitudInterpretacion,
    nuevo_id,
)
from rescate.mediador import MediadorCasos
from rescate.orquestador import Orquestador
from rescate.persistencia.repositorios import RepositorioDonativos, RepositorioParticipantes

from .autorizacion import es_coordinador, participante_del_actor
from .ciclo_vida import CicloDeVida
from .errores import ErrorAutorizacion, ErrorServicio


class ResultadoPublicacion(BaseModel):
    donativo_id: str
    completo: bool
    preguntas: list[str] = []
    donativo: Donativo | None = None
    mensaje: str = ""


class ServicioPublicacion:
    def __init__(
        self,
        orquestador: Orquestador,
        participantes: RepositorioParticipantes,
        donativos: RepositorioDonativos,
        ciclo: CicloDeVida,
        mediador: MediadorCasos,
    ) -> None:
        self._orquestador = orquestador
        self._participantes = participantes
        self._donativos = donativos
        self._ciclo = ciclo
        self._mediador = mediador
        # Pico de cierre (visión 9.3): las publicaciones se atienden una por una, en orden de llegada.
        self._candado = threading.Lock()

    def publicar(self, actor: Actor | None, texto: str, donativo_id: str | None = None) -> ResultadoPublicacion:
        """Corre interpretar → evaluar → asignar. Si faltan datos regresa `completo=False` con
        `preguntas`; la interfaz vuelve a llamar con el texto + la aclaración y el MISMO id."""
        donante = participante_del_actor(actor, Rol.DONANTE, self._participantes)
        if not texto.strip():
            raise ErrorServicio("Describe lo que te sobró.")

        with self._candado:
            solicitud = SolicitudInterpretacion(
                texto=texto, donante=donante, donativo_id=donativo_id or nuevo_id()
            )
            estado = self._orquestador.procesar(solicitud, self._participantes.receptores())
            interpretacion: ResultadoInterpretacion = estado["interpretacion"]
            self._escalar_alertas(interpretacion, solicitud.donativo_id)
            if not interpretacion.completo:
                return ResultadoPublicacion(
                    donativo_id=solicitud.donativo_id,
                    completo=False,
                    preguntas=interpretacion.preguntas,
                    mensaje="Necesito un dato más para publicar tu donativo.",
                )

            donativo: Donativo = estado["donativo"]
            self._ciclo.registrar_publicacion(donativo, actor)
            dictamen = estado["dictamen"]
            evento = Evento.EVALUAR_NO_APTO if dictamen.dictamen == Dictamen.NO_APTO else Evento.EVALUAR_APTO
            self._ciclo.transicionar(donativo, evento, dictamen.motivo, actor)
            if dictamen.requiere_revision:
                self._mediador.notificar("Inocuidad", TipoCaso.INOCUIDAD_DUDOSA, donativo.id, dictamen.motivo)

            if "asignacion" in estado:
                asignacion = estado["asignacion"]
                if not self._ciclo.aplicar_asignacion(donativo, asignacion, actor):
                    self._mediador.notificar("Asignador", TipoCaso.SIN_RECEPTOR, donativo.id, asignacion.justificacion)

        return ResultadoPublicacion(
            donativo_id=donativo.id, completo=True, donativo=donativo, mensaje=self._mensaje(donativo)
        )

    def cancelar(self, actor: Actor | None, donativo_id: str, motivo: str = "") -> Donativo:
        """El donante dueño (si ningún receptor lo ha aceptado) o el coordinador."""
        donativo = self._obtener(donativo_id)
        if not es_coordinador(actor):
            donante = participante_del_actor(actor, Rol.DONANTE, self._participantes)
            if donativo.donante_id != donante.id:
                raise ErrorAutorizacion("Este donativo no es tuyo.")
            if donativo.asignacion and donativo.asignacion.aceptada:
                raise ErrorServicio("Un receptor ya lo aceptó; ya no se puede cancelar.")
        self._ciclo.transicionar(donativo, Evento.CANCELAR, motivo or "Cancelado por el donante", actor)
        return donativo

    def donativos_de_donante(self, actor: Actor | None) -> list[Donativo]:
        donante = participante_del_actor(actor, Rol.DONANTE, self._participantes)
        return self._donativos.de_donante(donante.id)

    # ---------------------------------------------------------------- internos

    def _obtener(self, donativo_id: str) -> Donativo:
        donativo = self._donativos.obtener(donativo_id)
        if donativo is None:
            raise ErrorServicio(f"No existe el donativo {donativo_id}.")
        return donativo

    def _escalar_alertas(self, interpretacion: ResultadoInterpretacion, donativo_id: str) -> None:
        """Las alertas de seguridad del Intérprete se vuelven casos para el coordinador."""
        alertas = list(dict.fromkeys(interpretacion.alertas))
        if "posible_inyeccion" in alertas:
            self._mediador.notificar(
                "Intérprete", TipoCaso.POSIBLE_INYECCION, donativo_id, "El texto del donante parece intentar manipular al agente."
            )
        otras = [a for a in alertas if a != "posible_inyeccion"]
        if otras:
            self._mediador.notificar(
                "Intérprete",
                TipoCaso.INTERPRETACION_CORREGIDA,
                donativo_id,
                "El sistema corrigió la interpretación del LLM: " + ", ".join(otras),
            )

    def _mensaje(self, donativo: Donativo) -> str:
        if donativo.estado == EstadoDonativo.RECHAZADO:
            return "Gracias por avisar. Por seguridad, este alimento no se puede donar."
        if donativo.estado == EstadoDonativo.ASIGNADO:
            receptor = self._participantes.obtener(donativo.receptor_id)
            nombre = receptor.nombre if receptor else "un receptor"
            return f"¡Listo! Tu donativo se asignó a {nombre}."
        return "Tu donativo está publicado; un coordinador buscará quién lo reciba."
