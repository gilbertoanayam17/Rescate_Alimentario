"""Constancia de entrega de un donativo (CAR-12)."""
from __future__ import annotations

from datetime import datetime

from rescate.dominio.modelos import Donativo, Participante
from rescate.herramientas import impacto
from rescate.herramientas.compatibilidad import NOMBRE_TIPO

from .base import GeneradorDocumento

LEYENDA_CONSTANCIA = (
    "Respaldo para reportes ESG y fiscales (LISR art. 27, fr. XX); no es un comprobante fiscal "
    "(CFDI). Rescate Alimentario orienta sobre inocuidad; no certifica el alimento."
)


class ConstanciaEntrega(GeneradorDocumento):
    titulo = "Constancia de entrega de donativo"

    def __init__(
        self,
        donativo: Donativo,
        donante: Participante | None,
        receptor: Participante | None,
        recolector: Participante | None,
        fecha_entrega: datetime,
        generado: datetime | None = None,
        comprimir: bool = True,
    ) -> None:
        super().__init__(generado, comprimir)
        self.donativo = donativo
        self.donante = donante
        self.receptor = receptor
        self.recolector = recolector
        self.fecha_entrega = fecha_entrega

    def cuerpo(self) -> None:
        d = self.donativo
        self.dato("Folio:", d.id)
        self.dato("Fecha de entrega:", f"{self.fecha_entrega:%d/%m/%Y %H:%M}")
        self.dato("Donante:", _nombre(self.donante, d.donante_id))
        self.dato("Receptor:", _nombre(self.receptor, d.receptor_id))
        self.dato("Recolector:", _nombre(self.recolector, d.recolector_id))

        self.subtitulo("Alimentos entregados")
        self.tabla(
            ["Alimento", "Cantidad", "Tipo", "Kg"],
            [
                [a.nombre, f"{a.cantidad:g} {a.unidad}", NOMBRE_TIPO.get(a.tipo, a.tipo.value), f"{a.kg_estimados:g}"]
                for a in d.alimentos
            ],
            [0.4, 0.2, 0.25, 0.15],
        )
        kg = d.kg_totales
        self.pdf.ln(2)
        self.dato("Total:", f"{kg:g} kg")
        self.dato("Raciones equiv.:", f"{impacto.raciones(kg)}")
        self.dato("CO2e evitado:", f"{impacto.co2e_de(d):g} kg")
        self.parrafo(impacto.FUENTES, tamano=8)

        if d.dictamen:
            self.subtitulo("Dictamen de inocuidad")
            self.dato("Dictamen:", d.dictamen.dictamen.value.replace("_", " "))
            self.dato("Motivo:", d.dictamen.motivo)
            for condicion in d.dictamen.condiciones:
                self.dato("Condición:", condicion)
            if d.dictamen.reglas_citadas:
                self.dato("Fundamento:", "; ".join(d.dictamen.reglas_citadas))

    def pie(self) -> None:
        self.pdf.ln(6)
        self.parrafo(LEYENDA_CONSTANCIA, tamano=9)


def _nombre(participante: Participante | None, respaldo: str | None) -> str:
    return participante.nombre if participante else (respaldo or "-")
