"""Template Method: todos los documentos se arman con los mismos pasos.

`generar()` es el método plantilla y fija el orden: `_iniciar()` → `encabezado()` →
`cuerpo()` → `pie()` → `_cerrar()`. Cada documento solo implementa `cuerpo()` (abstracto) y,
si quiere, `pie()` (gancho). Un documento nuevo es una subclase más: no toca la base de datos
ni a los demás documentos.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from fpdf import FPDF

from rescate.dominio.modelos import ahora

#: Caracteres que Helvetica (latin-1) no tiene, con su reemplazo legible.
REEMPLAZOS = {
    "→": "->",
    "←": "<-",
    "≤": "<=",
    "≥": ">=",
    "—": "-",
    "–": "-",
    "“": '"',
    "”": '"',
    "‘": "'",
    "’": "'",
    "…": "...",
    "•": "-",
    "₂": "2",
    "≈": "~",
}


def a_latin1(texto: object) -> str:
    """Texto seguro para Helvetica: reemplaza lo conocido y descarta lo demás (emojis)."""
    cadena = str(texto)
    for original, reemplazo in REEMPLAZOS.items():
        cadena = cadena.replace(original, reemplazo)
    return cadena.encode("latin-1", "ignore").decode("latin-1")


class GeneradorDocumento(ABC):
    titulo = "Documento"
    MARGEN = 15

    def __init__(self, generado: datetime | None = None, comprimir: bool = True) -> None:
        self.generado = generado or ahora()
        self.comprimir = comprimir
        self.pdf: FPDF | None = None

    # --------------------------------------------------------- método plantilla

    def generar(self) -> bytes:
        """Arma el documento siempre en el mismo orden y regresa los bytes del PDF."""
        self._iniciar()
        self.encabezado()
        self.cuerpo()
        self.pie()
        return self._cerrar()

    # ------------------------------------------------------------------- pasos

    def _iniciar(self) -> None:
        self.pdf = FPDF(format="Letter")
        self.pdf.set_compression(self.comprimir)
        self.pdf.set_margins(self.MARGEN, self.MARGEN, self.MARGEN)
        self.pdf.set_auto_page_break(True, margin=self.MARGEN)
        self.pdf.set_title(a_latin1(self.titulo))
        self.pdf.set_author("Rescate Alimentario")
        self.pdf.add_page()

    def encabezado(self) -> None:
        self.pdf.set_font("Helvetica", "B", 16)
        self.linea("Rescate Alimentario", alto=8)
        self.pdf.set_font("Helvetica", "", 12)
        self.linea(self.titulo, alto=7)
        self.pdf.set_font("Helvetica", "", 9)
        self.linea(f"Generado el {self.generado:%d/%m/%Y %H:%M}", alto=5)
        self.pdf.ln(4)

    @abstractmethod
    def cuerpo(self) -> None:
        """El contenido propio de cada documento."""

    def pie(self) -> None:
        """Gancho: por omisión no agrega nada."""

    def _cerrar(self) -> bytes:
        return bytes(self.pdf.output())

    # --------------------------------------------------------------- ayudantes

    @property
    def ancho_util(self) -> float:
        return self.pdf.w - 2 * self.MARGEN

    def linea(self, texto: object, alto: float = 6) -> None:
        self.pdf.cell(self.ancho_util, alto, a_latin1(texto), new_x="LMARGIN", new_y="NEXT")

    def parrafo(self, texto: object, alto: float = 5, tamano: int = 10) -> None:
        self.pdf.set_font("Helvetica", "", tamano)
        self.pdf.multi_cell(self.ancho_util, alto, a_latin1(texto), new_x="LMARGIN", new_y="NEXT")

    def subtitulo(self, texto: object) -> None:
        self.pdf.ln(2)
        self.pdf.set_font("Helvetica", "B", 12)
        self.linea(texto, alto=7)
        self.pdf.set_font("Helvetica", "", 10)

    def dato(self, etiqueta: str, valor: object) -> None:
        self.pdf.set_font("Helvetica", "B", 10)
        self.pdf.cell(45, 6, a_latin1(etiqueta))
        self.pdf.set_font("Helvetica", "", 10)
        self.pdf.multi_cell(self.ancho_util - 45, 6, a_latin1(valor), new_x="LMARGIN", new_y="NEXT")

    def tabla(self, encabezados: list[str], filas: list[list[object]], anchos: list[float]) -> None:
        """Tabla simple; `anchos` son fracciones del ancho útil (suman 1)."""
        columnas = [self.ancho_util * a for a in anchos]
        self.pdf.set_font("Helvetica", "B", 9)
        self.pdf.set_fill_color(230, 230, 230)
        for texto, ancho in zip(encabezados, columnas, strict=True):
            self.pdf.cell(ancho, 7, a_latin1(texto), border=1, fill=True)
        self.pdf.ln()
        self.pdf.set_font("Helvetica", "", 9)
        for fila in filas:
            for texto, ancho in zip(fila, columnas, strict=True):
                self.pdf.cell(ancho, 6, a_latin1(texto), border=1)
            self.pdf.ln()
