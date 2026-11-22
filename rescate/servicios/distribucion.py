"""Asignación, aceptación, recolección y entrega (CAR-03, CAR-05). Una de las tres partes de SRP."""
from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import datetime

from rescate.agentes.logistico import AgenteLogistico
from rescate.dominio.enums import EstadoDonativo, Evento, Rol, TipoCaso
from rescate.dominio.estados import TransicionInvalida, aplicar_evento
from rescate.dominio.modelos import Actor, Asignacion, Donativo, Receptor, Recolector, ahora
from rescate.herramientas.compatibilidad import evaluar_compatibilidad
from rescate.herramientas.horario import limite_recoleccion
from rescate.mediador import MediadorCasos
from rescate.orquestador import Orquestador
from rescate.persistencia.repositorios import RepositorioDonativos, RepositorioParticipantes

from .autorizacion import exigir_rol, participante_del_actor
from .ciclo_vida import CicloDeVida
from .errores import ErrorAutorizacion, ErrorServicio

YA_TOMADO = "Otro voluntario ya tomó este donativo."


class ServicioDistribucion:
    def __init__(
        self,
        orquestador: Orquestador,
        participantes: RepositorioParticipantes,
        donativos: RepositorioDonativos,
        ciclo: CicloDeVida,
        mediador: MediadorCasos,
        logistico: AgenteLogistico | None = None,
        reloj: Callable[[], datetime] = ahora,
    ) -> None:
        self._orquestador = orquestador
        self._participantes = participantes
        self._donativos = donativos
        self._ciclo = ciclo
        self._mediador = mediador
        self._logistico = logistico
        self._reloj = reloj
        self._candado = threading.Lock()  # lectura-modificación-escritura de un donativo

    # ------------------------------------------------------------------ receptor

    def donativos_de_receptor(self, actor: Actor | None) -> list[Donativo]:
        receptor = participante_del_actor(actor, Rol.RECEPTOR, self._participantes)
        return self._donativos.de_receptor(receptor.id)

    def aceptar(self, actor: Actor | None, donativo_id: str) -> Donativo:
        receptor = participante_del_actor(actor, Rol.RECEPTOR, self._participantes)
        with self._candado:
            donativo = self._asignado_a(donativo_id, receptor.id)
            if not donativo.asignacion.aceptada:
                donativo.asignacion.aceptada = True
                self._ciclo.registrar_aceptacion(donativo, actor)
        return donativo

    def rechazar(self, actor: Actor | None, donativo_id: str, motivo: str) -> Donativo:
        """El receptor no lo puede recibir: se libera y se reasigna a otro automáticamente."""
        receptor = participante_del_actor(actor, Rol.RECEPTOR, self._participantes)
        if not motivo or not motivo.strip():
            raise ErrorServicio("Escribe un motivo para la reasignación.")
        with self._candado:
            donativo = self._asignado_a(donativo_id, receptor.id)
            donativo.receptores_descartados.append(receptor.id)
            self._ciclo.transicionar(donativo, Evento.LIBERAR, motivo.strip(), actor)
            return self._reasignar(donativo, actor)

    # --------------------------------------------------------------- coordinador

    def reintentar_asignacion(self, actor: Actor | None, donativo_id: str) -> Donativo:
        exigir_rol(actor, Rol.COORDINADOR)
        with self._candado:
            donativo = self._obtener(donativo_id)
            if donativo.estado != EstadoDonativo.EVALUADO:
                raise ErrorServicio("Solo se pueden reasignar donativos evaluados sin receptor.")
            return self._reasignar(donativo, actor)

    def asignar_manual(self, actor: Actor | None, donativo_id: str, receptor_id: str, motivo: str) -> Donativo:
        exigir_rol(actor, Rol.COORDINADOR)
        with self._candado:
            donativo = self._obtener(donativo_id)
            if donativo.estado != EstadoDonativo.EVALUADO:
                raise ErrorServicio("Solo se pueden asignar donativos evaluados sin receptor.")
            receptor = self._participantes.obtener(receptor_id)
            if not isinstance(receptor, Receptor):
                raise ErrorServicio("Elige un receptor válido.")
            compatibilidad = evaluar_compatibilidad(donativo, receptor)
            if not compatibilidad.compatible:
                raise ErrorServicio("No es compatible: " + "; ".join(compatibilidad.motivos))
            asignacion = Asignacion(
                receptor_id=receptor.id,
                justificacion=f"Asignación manual del coordinador: {motivo.strip() or 'sin motivo'}",
            )
            self._ciclo.aplicar_asignacion(donativo, asignacion, actor)
            return donativo

    def vencer_pendientes(self) -> list[Donativo]:
        """Expira los donativos cuyo plazo de recolección pasó (lo completa la tarea A2)."""
        return []

    # ---------------------------------------------------------------- recolector

    def disponibles_para_recolectar(self, actor: Actor | None) -> list[Donativo]:
        participante_del_actor(actor, Rol.RECOLECTOR, self._participantes)
        return [
            d
            for d in self._donativos.listar(EstadoDonativo.ASIGNADO)
            if d.asignacion and d.asignacion.aceptada and d.recolector_id is None
        ]

    def donativos_de_recolector(self, actor: Actor | None) -> list[Donativo]:
        recolector = participante_del_actor(actor, Rol.RECOLECTOR, self._participantes)
        return self._donativos.de_recolector(recolector.id)

    def iniciar_recoleccion(self, actor: Actor | None, donativo_id: str) -> Donativo:
        """Atómico: si dos voluntarios lo intentan a la vez, solo uno se lo queda."""
        recolector = participante_del_actor(actor, Rol.RECOLECTOR, self._participantes)
        if isinstance(recolector, Recolector) and not recolector.disponible:
            raise ErrorServicio("Tu perfil está marcado como no disponible para nuevas recolecciones.")
        with self._candado:
            donativo = self._obtener(donativo_id)
            if not (donativo.asignacion and donativo.asignacion.aceptada):
                raise ErrorServicio("El receptor aún no acepta este donativo.")
            if donativo.recolector_id is not None or donativo.estado != EstadoDonativo.ASIGNADO:
                raise ErrorServicio(YA_TOMADO)
            momento = self._reloj()
            if limite_recoleccion(donativo, momento) <= momento:
                raise ErrorServicio("La ventana de recolección terminó. Consulta al coordinador.")
            actualizado = donativo.model_copy(deep=True)
            actualizado.recolector_id = recolector.id
            try:
                aplicar_evento(actualizado, Evento.INICIAR_RECOLECCION)
            except TransicionInvalida as e:
                raise ErrorServicio(str(e)) from e
            if not self._donativos.tomar_para_recoleccion(actualizado):
                raise ErrorServicio(YA_TOMADO)
            self._ciclo.registrar_tomado(actualizado, actor)
            return actualizado

    def confirmar_entrega(self, actor: Actor | None, donativo_id: str) -> Donativo:
        recolector = participante_del_actor(actor, Rol.RECOLECTOR, self._participantes)
        with self._candado:
            donativo = self._obtener(donativo_id)
            if donativo.recolector_id != recolector.id:
                raise ErrorAutorizacion("Este donativo lo lleva otro recolector.")
            self._ciclo.transicionar(donativo, Evento.ENTREGAR, "Entregado al receptor", actor)
            return donativo

    def ruta_sugerida(self, actor: Actor | None):
        """Ruta con varias paradas del Agente Logístico (la completa la tarea A5)."""
        participante_del_actor(actor, Rol.RECOLECTOR, self._participantes)

    def tomar_ruta(self, actor: Actor | None, donativo_ids: list[str]) -> list[str]:
        """Toma cada donativo de la ruta; regresa los que ya había tomado otro voluntario."""
        perdidos = []
        for donativo_id in donativo_ids:
            try:
                self.iniciar_recoleccion(actor, donativo_id)
            except ErrorAutorizacion:
                raise
            except ErrorServicio:
                perdidos.append(donativo_id)
        return perdidos

    # ------------------------------------------------------------------ internos

    def _obtener(self, donativo_id: str) -> Donativo:
        donativo = self._donativos.obtener(donativo_id)
        if donativo is None:
            raise ErrorServicio(f"No existe el donativo {donativo_id}.")
        return donativo

    def _asignado_a(self, donativo_id: str, receptor_id: str) -> Donativo:
        donativo = self._obtener(donativo_id)
        if donativo.estado != EstadoDonativo.ASIGNADO or donativo.receptor_id != receptor_id:
            raise ErrorAutorizacion("Este donativo no está asignado a tu organización.")
        return donativo

    def _reasignar(self, donativo: Donativo, actor: Actor | None) -> Donativo:
        donante = self._participantes.obtener(donativo.donante_id)
        asignacion = self._orquestador.asignar(donativo, donante, self._participantes.receptores())
        if not self._ciclo.aplicar_asignacion(donativo, asignacion, actor):
            self._mediador.notificar("Distribución", TipoCaso.SIN_RECEPTOR, donativo.id, asignacion.justificacion)
        return donativo
