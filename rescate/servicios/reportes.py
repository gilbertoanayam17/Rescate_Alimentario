"""Consultas de solo lectura: donativos, historial, bitácora, tablero de impacto y documentos."""
from __future__ import annotations

from datetime import date

from rescate.bitacora import Bitacora
from rescate.dominio.enums import EstadoDonativo, Rol
from rescate.dominio.modelos import Actor, Donativo, EntradaBitacora
from rescate.persistencia.repositorios import RepositorioDonativos, RepositorioParticipantes

from .autorizacion import es_coordinador, exigir_rol, participante_del_actor
from .errores import ErrorAutorizacion


class ServicioReportes:
    def __init__(
        self, participantes: RepositorioParticipantes, donativos: RepositorioDonativos, bitacora: Bitacora
    ) -> None:
        self._participantes = participantes
        self._donativos = donativos
        self._bitacora = bitacora

    def todos(self, actor: Actor | None, estado: EstadoDonativo | None = None) -> list[Donativo]:
        exigir_rol(actor, Rol.COORDINADOR)
        return self._donativos.listar(estado)

    def donativo(self, actor: Actor | None, donativo_id: str) -> Donativo | None:
        """Visible para el coordinador y para los participantes involucrados."""
        donativo = self._donativos.obtener(donativo_id)
        if donativo is not None:
            self._exigir_visible(actor, donativo)
        return donativo

    def historial(self, actor: Actor | None, donativo_id: str) -> list[dict]:
        donativo = self._donativos.obtener(donativo_id)
        if donativo is None:
            return []
        self._exigir_visible(actor, donativo)
        return self._donativos.historial(donativo_id)

    def bitacora_de(self, actor: Actor | None, donativo_id: str) -> list[EntradaBitacora]:
        donativo = self._donativos.obtener(donativo_id)
        if donativo is None:
            exigir_rol(actor, Rol.COORDINADOR)  # trazas de algo que no se publicó: solo coordinación
        else:
            self._exigir_visible(actor, donativo)
        return self._bitacora.de_donativo(donativo_id)

    def bitacora_reciente(self, actor: Actor | None, limite: int = 200) -> list[EntradaBitacora]:
        exigir_rol(actor, Rol.COORDINADOR)
        return self._bitacora.recientes(limite)

    def tablero(self, actor: Actor | None, desde: date, hasta: date, donante_id=None, receptor_id=None):
        """Tablero de impacto (CAR-08). Lo implementa la tarea A3."""
        raise NotImplementedError("El tablero de impacto llega con la tarea A3.")

    def constancia_pdf(self, actor: Actor | None, donativo_id: str) -> bytes:
        """Constancia de entrega (CAR-12). La implementa la tarea A4."""
        raise NotImplementedError("La constancia de entrega llega con la tarea A4.")

    def reporte_impacto_pdf(self, actor: Actor | None, desde: date, hasta: date) -> bytes:
        """Reporte ESG (CAR-12). Lo implementa la tarea A4."""
        raise NotImplementedError("El reporte de impacto llega con la tarea A4.")

    def _exigir_visible(self, actor: Actor | None, donativo: Donativo) -> None:
        if es_coordinador(actor):
            return
        exigir_rol(actor, Rol.DONANTE, Rol.RECEPTOR, Rol.RECOLECTOR)
        participante = participante_del_actor(actor, actor.rol, self._participantes)
        if participante.id not in (donativo.donante_id, donativo.receptor_id, donativo.recolector_id):
            raise ErrorAutorizacion("No participas en este donativo.")
