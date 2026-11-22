"""Reporte de impacto para patrocinadores (ESG, CAR-12): periodo y cifras del tablero."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING

from rescate.dominio.enums import TipoAlimento
from rescate.herramientas.compatibilidad import NOMBRE_TIPO

from .base import GeneradorDocumento

if TYPE_CHECKING:
    from rescate.servicios.reportes import TableroImpacto


class ReporteImpacto(GeneradorDocumento):
    titulo = "Reporte de impacto (ESG)"

    def __init__(self, tablero: TableroImpacto, generado: datetime | None = None, comprimir: bool = True) -> None:
        super().__init__(generado, comprimir)
        self.tablero = tablero

    def cuerpo(self) -> None:
        t, r = self.tablero, self.tablero.resumen
        self.dato("Periodo:", f"{t.desde:%d/%m/%Y} a {t.hasta:%d/%m/%Y}")
        self.subtitulo("Resumen")
        self.tabla(
            ["Indicador", "Valor"],
            [
                ["Kg de alimento rescatado", f"{r.kg:,.1f}"],
                ["Raciones equivalentes", f"{r.raciones:,}"],
                ["CO2e evitado (kg)", f"{r.co2e_kg:,.1f}"],
                ["Donativos entregados", f"{r.donativos:,}"],
                ["Comercios donantes", f"{r.donantes}"],
                ["Organizaciones receptoras", f"{r.receptores}"],
            ],
            [0.6, 0.4],
        )
        por_mes: dict[str, float] = defaultdict(float)
        for p in t.serie_semanal:
            por_mes[f"{p.semana:%Y-%m}"] += p.kg
        self.subtitulo("Kg por mes")
        self.tabla(["Mes", "Kg"], [[mes, f"{kg:,.1f}"] for mes, kg in sorted(por_mes.items())], [0.5, 0.5])
        for titulo, top in (("Principales donantes", t.top_donantes), ("Principales receptores", t.top_receptores)):
            self.subtitulo(titulo)
            self.tabla(
                ["Nombre", "Kg", "Donativos"],
                [[p.nombre, f"{p.kg:,.1f}", p.donativos] for p in top],
                [0.6, 0.2, 0.2],
            )
        self.subtitulo("Kg por tipo de alimento")
        self.tabla(
            ["Tipo", "Kg"],
            [[NOMBRE_TIPO.get(TipoAlimento(tipo), tipo), f"{kg:,.1f}"] for tipo, kg in t.kg_por_tipo.items()],
            [0.6, 0.4],
        )

    def pie(self) -> None:
        self.pdf.ln(4)
        self.parrafo("Fuentes de los factores: " + self.tablero.fuentes, tamano=8)
        self.parrafo(
            "Cifras calculadas por código a partir de los donativos entregados registrados en la plataforma.",
            tamano=8,
        )
