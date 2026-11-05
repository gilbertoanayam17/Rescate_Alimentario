"""CAR-02 Agente de Inocuidad: dictamina si un donativo es apto para donarse.

DUEÑO: Gilberto (flujo 1).

1. Corre la cadena de reglas deterministas (`reglas_inocuidad`, Chain of Responsibility).
2. (Tarea G4) Consulta la NOM-251 con RAG y le pide al LLM que mantenga o endurezca el
   dictamen; nunca puede relajarlo.

No cambies la firma del constructor ni de `ejecutar` (solo se agregan parámetros opcionales).
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable

from rescate.agentes.base import Agente
from rescate.agentes.reglas_inocuidad import combinar, crear_cadena
from rescate.bitacora import Bitacora
from rescate.dominio.enums import TipoEntradaBitacora
from rescate.dominio.modelos import DictamenInocuidad, Donativo, ahora
from rescate.llm.cliente import ClienteLLM
from rescate.rag.base_conocimiento import BaseConocimiento, BaseConocimientoVacia


class AgenteInocuidad(Agente[Donativo, DictamenInocuidad]):
    nombre = "Inocuidad"

    def __init__(
        self,
        llm: ClienteLLM,
        bitacora: Bitacora,
        base_conocimiento: BaseConocimiento | None = None,
        reloj: Callable[[], datetime] = ahora,
    ) -> None:
        super().__init__(llm, bitacora)
        self.base_conocimiento = base_conocimiento or BaseConocimientoVacia()
        self.reloj = reloj

    def ejecutar(self, entrada: Donativo) -> DictamenInocuidad:
        did = entrada.id
        self._anotar(
            TipoEntradaBitacora.PENSAMIENTO, f"Reviso {entrada.resumen()} con las reglas de inocuidad.", did, paso=1
        )
        hallazgos = crear_cadena().evaluar(entrada, self.reloj())
        for hallazgo in hallazgos:
            self._anotar(
                TipoEntradaBitacora.OBSERVACION,
                f"{hallazgo.regla}: {hallazgo.motivo}",
                did,
                paso=2,
                datos=hallazgo.model_dump(mode="json"),
            )
        dictamen = combinar(hallazgos)
        self._anotar(
            TipoEntradaBitacora.RESULTADO,
            f"{dictamen.dictamen.value}: {dictamen.motivo}",
            did,
            paso=3,
            datos=dictamen.model_dump(mode="json"),
        )
        return dictamen
