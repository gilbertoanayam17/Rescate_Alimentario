"""CAR-03 Agente Asignador: elige el receptor más adecuado para un donativo.

DUEÑO: Alejandro (flujo 2).
FASE 0: versión determinista mínima (receptor compatible más cercano), sin LLM. La tarea
A4 la reemplaza por herramientas + puntuación (Strategy) + decisión del LLM (+ ReAct).
No cambies la firma del constructor ni de `ejecutar`.
"""
from __future__ import annotations

from rescate.agentes.base import Agente
from rescate.bitacora import Bitacora
from rescate.dominio.enums import TipoEntradaBitacora
from rescate.dominio.modelos import Asignacion, Receptor, SolicitudAsignacion
from rescate.herramientas.geo import haversine_km
from rescate.llm.cliente import ClienteLLM
from rescate.persistencia.repositorios import RepositorioDonativos, RepositorioParticipantes


class AgenteAsignador(Agente[SolicitudAsignacion, Asignacion]):
    nombre = "Asignador"

    def __init__(
        self,
        llm: ClienteLLM,
        bitacora: Bitacora,
        participantes: RepositorioParticipantes,
        donativos: RepositorioDonativos,
    ) -> None:
        super().__init__(llm, bitacora)
        self.participantes = participantes
        self.donativos = donativos

    def ejecutar(self, entrada: SolicitudAsignacion) -> Asignacion:
        donativo = entrada.donativo
        self._anotar(
            TipoEntradaBitacora.PENSAMIENTO,
            "Busco el receptor compatible más cercano (versión de fase 0, sin LLM).",
            donativo.id,
            paso=1,
        )
        candidatos = [r for r in entrada.receptores if self._es_compatible(entrada, r)]
        if not candidatos:
            asignacion = Asignacion(
                requiere_coordinador=True,
                justificacion="Ningún receptor acepta este tipo de alimento con las condiciones requeridas.",
            )
        else:
            origen = entrada.donante.ubicacion
            candidatos.sort(key=lambda r: haversine_km(origen, r.ubicacion))
            elegido = candidatos[0]
            distancia = haversine_km(origen, elegido.ubicacion)
            asignacion = Asignacion(
                receptor_id=elegido.id,
                puntaje=round(1 / (1 + distancia), 3),
                justificacion=f"{elegido.nombre} es el receptor compatible más cercano ({distancia:.1f} km).",
                alternativas=[r.id for r in candidatos[1:3]],
            )
        self._anotar(
            TipoEntradaBitacora.RESULTADO,
            asignacion.justificacion,
            donativo.id,
            paso=2,
            datos=asignacion.model_dump(mode="json"),
        )
        return asignacion

    @staticmethod
    def _es_compatible(entrada: SolicitudAsignacion, receptor: Receptor) -> bool:
        donativo = entrada.donativo
        if receptor.id in donativo.receptores_descartados:
            return False
        if not all(a.tipo in receptor.tipos_aceptados for a in donativo.alimentos):
            return False
        if donativo.dictamen and donativo.dictamen.requiere_refrigeracion and not receptor.tiene_refrigeracion:
            return False
        return True
