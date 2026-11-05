"""CAR-02 Agente de Inocuidad: dictamina si un donativo es apto para donarse.

DUEÑO: Gilberto (flujo 1).
FASE 0: versión determinista mínima y conservadora, sin LLM ni RAG. La tarea G4 la
reemplaza por la cadena de reglas (Chain of Responsibility) + RAG sobre la NOM-251 + LLM.
No cambies la firma del constructor ni de `ejecutar`.
"""
from __future__ import annotations

from rescate.agentes.base import Agente
from rescate.bitacora import Bitacora
from rescate.dominio.enums import PERECEDEROS, Dictamen, TipoAlimento, TipoEntradaBitacora
from rescate.dominio.modelos import DictamenInocuidad, Donativo
from rescate.llm.cliente import ClienteLLM
from rescate.rag.base_conocimiento import BaseConocimiento, BaseConocimientoVacia

SENALES_DETERIORO = ["echado a perder", "huele mal", "moho", "agrio", "podrid", "rancio", "caducad", "vencid", "baboso"]


class AgenteInocuidad(Agente[Donativo, DictamenInocuidad]):
    nombre = "Inocuidad"

    def __init__(
        self,
        llm: ClienteLLM,
        bitacora: Bitacora,
        base_conocimiento: BaseConocimiento | None = None,
    ) -> None:
        super().__init__(llm, bitacora)
        self.base_conocimiento = base_conocimiento or BaseConocimientoVacia()

    def ejecutar(self, entrada: Donativo) -> DictamenInocuidad:
        self._anotar(
            TipoEntradaBitacora.PENSAMIENTO,
            "Evalúo con reglas mínimas (versión de fase 0, sin LLM ni RAG).",
            entrada.id,
            paso=1,
        )
        dictamen = self._evaluar_con_reglas(entrada)
        self._anotar(
            TipoEntradaBitacora.RESULTADO,
            f"{dictamen.dictamen.value}: {dictamen.motivo}",
            entrada.id,
            paso=2,
            datos=dictamen.model_dump(mode="json"),
        )
        return dictamen

    def _evaluar_con_reglas(self, donativo: Donativo) -> DictamenInocuidad:
        texto = " ".join([donativo.texto_original, *[a.observaciones for a in donativo.alimentos]]).lower()
        if any(senal in texto for senal in SENALES_DETERIORO):
            return DictamenInocuidad(
                dictamen=Dictamen.NO_APTO,
                motivo="El donante describe señales de deterioro; no se dona.",
                reglas_citadas=["Criterio interno del proyecto: alimentos con señales de deterioro no se donan"],
            )
        tipos = {a.tipo for a in donativo.alimentos}
        if tipos & PERECEDEROS:
            return DictamenInocuidad(
                dictamen=Dictamen.APTO_CON_CONDICIONES,
                motivo="Incluye alimentos perecederos; deben mantenerse fríos y consumirse pronto.",
                condiciones=["Mantener a 7 °C o menos hasta su consumo", "Consumir el mismo día"],
                vida_util_horas=12,
                requiere_refrigeracion=bool(tipos & {TipoAlimento.LACTEO, TipoAlimento.CARNE_PESCADO}),
                reglas_citadas=["NOM-251-SSA1-2009, numeral 7.3.3"],
            )
        return DictamenInocuidad(
            dictamen=Dictamen.APTO,
            motivo="Alimentos de bajo riesgo a temperatura ambiente.",
            vida_util_horas=48,
        )
