"""Orquestador del flujo agéntico de un donativo, con LangGraph.

    START -> interpretar --(faltan datos)--> END (se devuelven preguntas al donante)
                 |
              (completo)
                 v
        construir_donativo -> evaluar --(no apto)--> END
                                 |
                              (apto)
                                 v
                              asignar -> END

El orquestador solo coordina: no guarda nada ni cambia estados. Eso lo hace
ServicioDonativos con el resultado. Depende de los agentes por su interfaz
`ejecutar`, así que cada integrante cambia su agente sin tocar este archivo.

Archivo COMPARTIDO (fase 0).
"""
from __future__ import annotations

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from rescate.agentes.base import Agente
from rescate.dominio.enums import Dictamen
from rescate.dominio.modelos import (
    Asignacion,
    DictamenInocuidad,
    Donante,
    Donativo,
    Receptor,
    ResultadoInterpretacion,
    SolicitudAsignacion,
    SolicitudInterpretacion,
)


class EstadoFlujo(TypedDict, total=False):
    solicitud: SolicitudInterpretacion
    receptores: list[Receptor]
    interpretacion: ResultadoInterpretacion
    donativo: Donativo
    dictamen: DictamenInocuidad
    asignacion: Asignacion


class Orquestador:
    def __init__(
        self,
        interprete: Agente[SolicitudInterpretacion, ResultadoInterpretacion],
        inocuidad: Agente[Donativo, DictamenInocuidad],
        asignador: Agente[SolicitudAsignacion, Asignacion],
    ) -> None:
        self.interprete = interprete
        self.inocuidad = inocuidad
        self.asignador = asignador
        self._grafo = self._construir_grafo()

    # ------------------------------------------------------------------ API

    def procesar(self, solicitud: SolicitudInterpretacion, receptores: list[Receptor]) -> EstadoFlujo:
        """Corre el flujo completo para una publicación del donante."""
        return self._grafo.invoke({"solicitud": solicitud, "receptores": receptores})

    def asignar(self, donativo: Donativo, donante: Donante, receptores: list[Receptor]) -> Asignacion:
        """Solo el paso de asignación (reasignar cuando un receptor rechaza)."""
        return self.asignador.ejecutar(
            SolicitudAsignacion(donativo=donativo, donante=donante, receptores=receptores)
        )

    # ---------------------------------------------------------------- grafo

    def _construir_grafo(self):
        grafo = StateGraph(EstadoFlujo)
        grafo.add_node("interpretar", self._interpretar)
        grafo.add_node("construir_donativo", self._construir_donativo)
        grafo.add_node("evaluar", self._evaluar)
        grafo.add_node("asignar", self._asignar)
        grafo.add_edge(START, "interpretar")
        grafo.add_conditional_edges(
            "interpretar",
            self._tras_interpretar,
            {"completo": "construir_donativo", "faltan_datos": END},
        )
        grafo.add_edge("construir_donativo", "evaluar")
        grafo.add_conditional_edges("evaluar", self._tras_evaluar, {"apto": "asignar", "no_apto": END})
        grafo.add_edge("asignar", END)
        return grafo.compile()

    def _interpretar(self, estado: EstadoFlujo) -> EstadoFlujo:
        return {"interpretacion": self.interprete.ejecutar(estado["solicitud"])}

    @staticmethod
    def _tras_interpretar(estado: EstadoFlujo) -> str:
        return "completo" if estado["interpretacion"].completo else "faltan_datos"

    @staticmethod
    def _construir_donativo(estado: EstadoFlujo) -> EstadoFlujo:
        solicitud, interpretacion = estado["solicitud"], estado["interpretacion"]
        donativo = Donativo(
            id=solicitud.donativo_id,
            donante_id=solicitud.donante.id,
            texto_original=solicitud.texto,
            alimentos=interpretacion.alimentos,
            hora_preparacion=interpretacion.hora_preparacion,
            recoger_antes_de=interpretacion.recoger_antes_de,
        )
        return {"donativo": donativo}

    def _evaluar(self, estado: EstadoFlujo) -> EstadoFlujo:
        donativo = estado["donativo"]
        dictamen = self.inocuidad.ejecutar(donativo)
        donativo.dictamen = dictamen
        return {"dictamen": dictamen, "donativo": donativo}

    @staticmethod
    def _tras_evaluar(estado: EstadoFlujo) -> str:
        return "no_apto" if estado["dictamen"].dictamen == Dictamen.NO_APTO else "apto"

    def _asignar(self, estado: EstadoFlujo) -> EstadoFlujo:
        solicitud = SolicitudAsignacion(
            donativo=estado["donativo"],
            donante=estado["solicitud"].donante,
            receptores=estado["receptores"],
        )
        return {"asignacion": self.asignador.ejecutar(solicitud)}
