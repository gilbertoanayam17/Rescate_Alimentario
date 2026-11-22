"""Documentos exportables en PDF (CAR-12) con el patrón Template Method."""
from .base import GeneradorDocumento
from .constancia import LEYENDA_CONSTANCIA, ConstanciaEntrega
from .reporte_esg import ReporteImpacto

__all__ = ["LEYENDA_CONSTANCIA", "ConstanciaEntrega", "GeneradorDocumento", "ReporteImpacto"]
