"""CAR-01 Agente Intérprete: convierte la frase del donante en alimentos estructurados.

DUEÑO: Gilberto (flujo 1).
FASE 0: versión determinista mínima con expresiones regulares, sin LLM, para que la app
funcione de punta a punta desde el primer día. La tarea G3 agrega el camino con LLM y deja
`_interpretar_con_reglas` como respaldo. No cambies la firma de `ejecutar`.
"""
from __future__ import annotations

import re

from rescate.agentes.base import Agente
from rescate.dominio.enums import Conservacion, TipoAlimento, TipoEntradaBitacora
from rescate.dominio.modelos import Alimento, ResultadoInterpretacion, SolicitudInterpretacion

PALABRAS_POR_TIPO: dict[TipoAlimento, list[str]] = {
    TipoAlimento.PANADERIA: ["pan", "bolillo", "concha", "tortilla", "telera", "dona", "galleta", "birote", "pastel"],
    TipoAlimento.PREPARADO: [
        "guisado", "arroz", "frijoles", "sopa", "caldo", "tamal", "mole", "pozole", "comida",
        "picadillo", "tinga", "chilaquiles", "torta", "taco", "pollo en", "carne en", "lonche",
    ],
    TipoAlimento.FRUTA_VERDURA: [
        "fruta", "manzana", "naranja", "platano", "plátano", "jitomate", "tomate", "papa", "zanahoria",
        "verdura", "lechuga", "aguacate", "mango", "papaya", "sandia", "sandía", "piña", "cebolla",
    ],
    TipoAlimento.LACTEO: ["leche", "queso", "yogur", "crema", "jocoque"],
    TipoAlimento.CARNE_PESCADO: ["carne cruda", "pollo crudo", "pescado", "res", "cerdo", "camaron", "camarón"],
    TipoAlimento.ABARROTE: ["lata", "enlatado", "atun", "atún", "frijol en bolsa", "pasta", "harina", "azucar", "azúcar"],
    TipoAlimento.BEBIDA: ["agua", "refresco", "jugo", "atole"],
}

UNIDADES: dict[str, str] = {
    "kg": "kg", "kilo": "kg", "kilos": "kg", "kilogramo": "kg", "kilogramos": "kg",
    "g": "g", "gr": "g", "gramos": "g",
    "pieza": "pieza", "piezas": "pieza", "pza": "pieza", "pzas": "pieza",
    "porcion": "porcion", "porción": "porcion", "porciones": "porcion",
    "orden": "porcion", "ordenes": "porcion", "órdenes": "porcion",
    "litro": "litro", "litros": "litro", "lt": "litro", "lts": "litro", "l": "litro",
    "charola": "charola", "charolas": "charola", "bolsa": "bolsa", "bolsas": "bolsa",
    "caja": "caja", "cajas": "caja",
}

#: kg aproximados por unidad; "pieza" depende del tipo de alimento.
KG_POR_UNIDAD = {"kg": 1.0, "g": 0.001, "porcion": 0.35, "litro": 1.0, "charola": 2.0, "bolsa": 1.0, "caja": 5.0}
KG_POR_PIEZA = {TipoAlimento.PANADERIA: 0.07, TipoAlimento.FRUTA_VERDURA: 0.2}

_PATRON = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(" + "|".join(sorted(map(re.escape, UNIDADES), key=len, reverse=True)) + r")?\.?\s+(?:de\s+)?(.+)",
    re.IGNORECASE,
)


def estimar_kg(cantidad: float, unidad: str, tipo: TipoAlimento) -> float:
    """Herramienta determinista: kg aproximados. El LLM nunca hace esta cuenta."""
    if unidad == "pieza":
        return round(cantidad * KG_POR_PIEZA.get(tipo, 0.25), 2)
    return round(cantidad * KG_POR_UNIDAD.get(unidad, 0.5), 2)


def clasificar(nombre: str) -> TipoAlimento:
    texto = nombre.lower()
    for tipo, palabras in PALABRAS_POR_TIPO.items():
        if any(p in texto for p in palabras):
            return tipo
    return TipoAlimento.OTRO


def detectar_conservacion(texto: str) -> Conservacion:
    texto = texto.lower()
    if "congelad" in texto:
        return Conservacion.CONGELADO
    if "refri" in texto:
        return Conservacion.REFRIGERADO
    if "caliente" in texto or "calientito" in texto:
        return Conservacion.CALIENTE
    if "afuera" in texto or "ambiente" in texto or "mostrador" in texto:
        return Conservacion.AMBIENTE
    return Conservacion.DESCONOCIDA


class AgenteInterprete(Agente[SolicitudInterpretacion, ResultadoInterpretacion]):
    nombre = "Intérprete"

    def ejecutar(self, entrada: SolicitudInterpretacion) -> ResultadoInterpretacion:
        self._anotar(
            TipoEntradaBitacora.PENSAMIENTO,
            "Interpreto el texto con reglas (versión de fase 0, sin LLM).",
            entrada.donativo_id,
            paso=1,
        )
        resultado = self._interpretar_con_reglas(entrada.texto)
        self._anotar(
            TipoEntradaBitacora.RESULTADO,
            f"Encontré {len(resultado.alimentos)} alimento(s)."
            if resultado.completo
            else "No encontré alimentos con cantidad; pido aclaración.",
            entrada.donativo_id,
            paso=2,
            datos=resultado.model_dump(mode="json"),
        )
        return resultado

    def _interpretar_con_reglas(self, texto: str) -> ResultadoInterpretacion:
        conservacion = detectar_conservacion(texto)
        alimentos: list[Alimento] = []
        for fragmento in re.split(r",|;|\by\b|\be\b", texto):
            coincidencia = _PATRON.search(fragmento.strip())
            if not coincidencia:
                continue
            cantidad = float(coincidencia.group(1).replace(",", "."))
            unidad = UNIDADES.get((coincidencia.group(2) or "pieza").lower(), "pieza")
            nombre = coincidencia.group(3).strip(" .")
            if cantidad <= 0 or not nombre:
                continue
            tipo = clasificar(nombre)
            alimentos.append(
                Alimento(
                    nombre=nombre,
                    cantidad=cantidad,
                    unidad=unidad,
                    tipo=tipo,
                    conservacion=conservacion,
                    kg_estimados=estimar_kg(cantidad, unidad, tipo),
                )
            )
        if not alimentos:
            return ResultadoInterpretacion(
                completo=False,
                preguntas=["¿Qué alimentos te sobraron y cuánto de cada uno? Por ejemplo: 15 bolillos y 3 kg de arroz."],
            )
        return ResultadoInterpretacion(completo=True, alimentos=alimentos)
