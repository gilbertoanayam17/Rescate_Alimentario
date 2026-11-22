"""Consultas de solo lectura: donativos, historial, bitácora, tablero de impacto y documentos."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from pydantic import BaseModel

from rescate.bitacora import Bitacora
from rescate.dominio.enums import EstadoDonativo, Rol
from rescate.dominio.modelos import Actor, Donativo, EntradaBitacora
from rescate.herramientas import impacto
from rescate.herramientas.impacto import ResumenImpacto
from rescate.persistencia.repositorios import RepositorioDonativos, RepositorioParticipantes

from .autorizacion import es_coordinador, exigir_rol, participante_del_actor
from .errores import ErrorAutorizacion


class PuntoSemanal(BaseModel):
    semana: date  # lunes de la semana
    kg: float
    raciones: int
    co2e_kg: float


class Posicion(BaseModel):
    """Un renglón de un top 10."""

    participante_id: str
    nombre: str
    kg: float
    donativos: int


class TableroImpacto(BaseModel):
    """Lo que muestra la pestaña Impacto (CAR-08). Todas las cifras las calcula código."""

    desde: date
    hasta: date
    donante_id: str | None = None
    receptor_id: str | None = None
    resumen: ResumenImpacto
    serie_semanal: list[PuntoSemanal]
    top_donantes: list[Posicion]
    top_receptores: list[Posicion]
    kg_por_tipo: dict[str, float]
    fuentes: str = impacto.FUENTES


def fecha_entrega(donativo: Donativo) -> date:
    """Un donativo ENTREGADO ya no cambia: su última actualización es la entrega."""
    return donativo.actualizado.date()


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

    def tablero(
        self,
        actor: Actor | None,
        desde: date,
        hasta: date,
        donante_id: str | None = None,
        receptor_id: str | None = None,
    ) -> TableroImpacto:
        """Impacto de los donativos ENTREGADOS entre `desde` y `hasta` (por fecha de entrega).

        El coordinador ve todo y puede filtrar; el donante y el receptor solo ven lo suyo: el
        filtro se fuerza con su id, sin importar lo que pida la interfaz."""
        if not es_coordinador(actor):
            exigir_rol(actor, Rol.DONANTE, Rol.RECEPTOR)
            participante = participante_del_actor(actor, actor.rol, self._participantes)
            if participante.rol == Rol.DONANTE:
                donante_id, receptor_id = participante.id, None
            else:
                donante_id, receptor_id = None, participante.id
        entregados = [
            d
            for d in self._donativos.listar(EstadoDonativo.ENTREGADO)
            if desde <= fecha_entrega(d) <= hasta
            and (donante_id is None or d.donante_id == donante_id)
            and (receptor_id is None or d.receptor_id == receptor_id)
        ]
        return TableroImpacto(
            desde=desde,
            hasta=hasta,
            donante_id=donante_id,
            receptor_id=receptor_id,
            resumen=impacto.resumen(entregados),
            serie_semanal=self._serie_semanal(entregados, desde, hasta),
            top_donantes=self._top(entregados, lambda d: d.donante_id),
            top_receptores=self._top(entregados, lambda d: d.receptor_id),
            kg_por_tipo=self._kg_por_tipo(entregados),
        )

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

    # ------------------------------------------------------------ ayudantes del tablero

    @staticmethod
    def _serie_semanal(donativos: list[Donativo], desde: date, hasta: date) -> list[PuntoSemanal]:
        por_semana: dict[date, list[Donativo]] = defaultdict(list)
        for d in donativos:
            dia = fecha_entrega(d)
            por_semana[dia - timedelta(days=dia.weekday())].append(d)
        serie = []
        semana = desde - timedelta(days=desde.weekday())
        while semana <= hasta:
            r = impacto.resumen(por_semana.get(semana, []))
            serie.append(PuntoSemanal(semana=semana, kg=r.kg, raciones=r.raciones, co2e_kg=r.co2e_kg))
            semana += timedelta(days=7)
        return serie

    def _top(self, donativos: list[Donativo], clave, limite: int = 10) -> list[Posicion]:
        kg: dict[str, float] = defaultdict(float)
        cuenta: dict[str, int] = defaultdict(int)
        for d in donativos:
            pid = clave(d)
            if pid:
                kg[pid] += d.kg_totales
                cuenta[pid] += 1
        orden = sorted(kg, key=lambda pid: (-kg[pid], pid))[:limite]
        posiciones = []
        for pid in orden:
            participante = self._participantes.obtener(pid)
            posiciones.append(
                Posicion(
                    participante_id=pid,
                    nombre=participante.nombre if participante else pid,
                    kg=round(kg[pid], 2),
                    donativos=cuenta[pid],
                )
            )
        return posiciones

    @staticmethod
    def _kg_por_tipo(donativos: list[Donativo]) -> dict[str, float]:
        kg: dict[str, float] = defaultdict(float)
        for d in donativos:
            for a in d.alimentos:
                kg[a.tipo.value] += a.kg_estimados
        return {tipo: round(v, 2) for tipo, v in sorted(kg.items(), key=lambda x: -x[1])}
