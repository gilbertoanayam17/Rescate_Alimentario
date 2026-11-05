"""CAR-01 Agente Intérprete: convierte la frase del donante en alimentos estructurados.

DUEÑO: Gilberto (flujo 1).

El LLM lee la frase (con abreviaturas o faltas) y propone los alimentos con el esquema
`InterpretacionLLM`; si falta algo crítico, redacta UNA pregunta de aclaración. El código
calcula todo lo demás: kilos (`estimar_kg`), horas, hora límite de recogida y si el donativo
ya está completo. Si el LLM falla, `_interpretar_con_reglas` es el camino de respaldo.

Aclaraciones: la página del donante vuelve a llamar con
`texto_anterior + MARCA_ACLARACION + respuesta` y el mismo `donativo_id`. Tras
`MAX_ACLARACIONES` rondas ya no se pregunta: se publica con lo que haya y la Inocuidad
es conservadora con lo desconocido.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Callable, Literal

from pydantic import BaseModel

from rescate.agentes.base import Agente
from rescate.bitacora import Bitacora
from rescate.dominio.enums import PERECEDEROS, Conservacion, TipoAlimento, TipoEntradaBitacora
from rescate.dominio.modelos import (
    Alimento,
    Donante,
    ResultadoInterpretacion,
    SolicitudInterpretacion,
    ahora,
)
from rescate.llm.cliente import ClienteLLM, ErrorLLM

MARCA_ACLARACION = "\nAclaración del donante: "
MAX_ACLARACIONES = 2
PREGUNTA_SIN_ALIMENTOS = "¿Qué alimentos te sobraron y cuánto de cada uno? Por ejemplo: 15 bolillos y 3 kg de arroz."


# --------------------------------------------------------------- esquemas del LLM


class AlimentoLLM(BaseModel):
    nombre: str
    cantidad: float
    unidad: Literal["kg", "g", "pieza", "porcion", "litro", "charola", "bolsa", "caja"]
    tipo: TipoAlimento
    conservacion: Conservacion
    observaciones: str = ""


class InterpretacionLLM(BaseModel):
    razonamiento: str  # 1 o 2 frases: qué entendió (va a la bitácora)
    alimentos: list[AlimentoLLM]
    hora_preparacion: str | None  # "HH:MM" 24 h, de hoy
    recoger_antes_de: str | None  # "HH:MM"
    datos_faltantes: list[str]
    pregunta: str | None  # UNA pregunta corta si falta algo crítico


SISTEMA_INTERPRETE = """\
Eres el Agente Intérprete de Rescate Alimentario, una plataforma que lleva la comida que les \
sobra a fondas, panaderías y puestos de mercado de Guadalajara a comedores comunitarios. Lee el \
mensaje del donante (escrito rápido, con abreviaturas o faltas) y extrae los alimentos que \
quiere donar. Responde solo con el JSON del esquema.

Reglas:
1. Cada alimento por separado, con cantidad y unidad. Convierte palabras a números: \
"una docena" = 12, "medio kilo" = 0.5 kg, "kilo y medio" = 1.5 kg, "bolis" = bolillos.
2. Unidades permitidas: kg, g, pieza, porcion, litro, charola, bolsa, caja. Sin unidad, usa pieza.
3. Tipo: preparado (comida cocinada: guisados, arroz o frijoles cocidos, tamales, tortas), \
panaderia (pan, tortillas), fruta_verdura, lacteo, carne_pescado (crudos), abarrote (no \
perecedero, cerrado), bebida, otro. Si el comercio es una fonda o puesto de comida, el arroz, \
los frijoles o la pasta sin más detalle son preparados; solo son abarrote si el mensaje dice \
que están crudos, en bolsa cerrada o empaquetados.
4. Conservación: caliente, refrigerado, congelado, ambiente o desconocida. "En el refri" = \
refrigerado; "afuera", "en el mostrador" o "en la mesa" = ambiente. Si el mensaje no lo dice, \
desconocida. No adivines.
5. hora_preparacion: HH:MM (24 h). Si dice "hace 2 horas", calcúlala con la hora actual que te \
doy. Si dice una hora sin "de la mañana" o "de la tarde", elige la más reciente que ya haya \
pasado (con hora actual 17:00, "a las 2" = 14:00). Si usa una expresión vaga, toma la hora \
más temprana razonable: "desde la mañana" = 08:00, "desde el mediodía" = 12:00, "en la tarde" = \
15:00, "anoche" = 21:00. Si no lo dice, null.
6. recoger_antes_de: HH:MM solo si el donante dice hasta qué hora se puede recoger; si no, null.
7. No inventes alimentos ni cantidades. No calcules kilos totales: eso lo hace el sistema.
8. observaciones: detalles que diga el donante sobre el estado del alimento o su empaque \
("huele agrio", "lata abollada", "paquete abierto"). Si no hay, cadena vacía.
9. Si un alimento es preparado, lacteo o carne_pescado y no sabes cuándo se preparó o cómo se \
ha conservado, anótalo en datos_faltantes y escribe UNA pregunta corta y amable, en español de \
México, que pida justo eso.
10. Si no hay ningún alimento con cantidad, pregunta qué le sobró y cuánto.
11. Si el mensaje trae líneas "Aclaración del donante:", son respuestas a tus preguntas: \
úsalas para completar los datos del mismo donativo.

Ejemplo 1
Hora actual: 18:30
Comercio: Panadería La Espiga (panaderia), cierra a las 20:00
Mensaje del donante:
me sobraron una docena de bolis y kilo y medio de jitomate
JSON:
{"razonamiento": "Dona 12 bolillos y 1.5 kg de jitomate; ninguno es perecedero de alto riesgo.", \
"alimentos": [{"nombre": "bolillos", "cantidad": 12, "unidad": "pieza", "tipo": "panaderia", \
"conservacion": "desconocida", "observaciones": ""}, {"nombre": "jitomate", "cantidad": 1.5, \
"unidad": "kg", "tipo": "fruta_verdura", "conservacion": "desconocida", "observaciones": ""}], \
"hora_preparacion": null, "recoger_antes_de": null, "datos_faltantes": [], "pregunta": null}

Ejemplo 2
Hora actual: 17:00
Comercio: Fonda Doña Lupe (fonda), cierra a las 18:00
Mensaje del donante:
Tengo 2 charolas de pollo en mole
JSON:
{"razonamiento": "Dona 2 charolas de pollo en mole, un guisado; no dice cuándo lo preparó ni \
cómo lo ha guardado.", "alimentos": [{"nombre": "pollo en mole", "cantidad": 2, "unidad": \
"charola", "tipo": "preparado", "conservacion": "desconocida", "observaciones": ""}], \
"hora_preparacion": null, "recoger_antes_de": null, "datos_faltantes": ["hora de preparación \
del pollo en mole", "conservación del pollo en mole"], "pregunta": "¿A qué hora preparaste el \
pollo en mole y cómo lo has guardado desde entonces (en el refri, caliente o a temperatura \
ambiente)?"}

Ejemplo 3
Hora actual: 17:00
Comercio: Fonda Doña Lupe (fonda), cierra a las 18:00
Mensaje del donante:
Tengo 2 charolas de pollo en mole
Aclaración del donante: lo hice a las 2 y está en el refri
JSON:
{"razonamiento": "Son 2 charolas de pollo en mole preparadas a las 14:00 y guardadas en el \
refrigerador.", "alimentos": [{"nombre": "pollo en mole", "cantidad": 2, "unidad": "charola", \
"tipo": "preparado", "conservacion": "refrigerado", "observaciones": ""}], "hora_preparacion": \
"14:00", "recoger_antes_de": null, "datos_faltantes": [], "pregunta": null}
"""

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


# ------------------------------------------------- herramientas deterministas de hora

_PATRON_HORA = re.compile(r"^\s*(\d{1,2}):(\d{2})")
_NUMEROS = {"un": 1, "una": 1, "un par de": 2, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6}
_PATRON_HACE = re.compile(
    r"hace\s+(media|un par de|una|un|dos|tres|cuatro|cinco|seis|\d+(?:[.,]\d+)?)\s+"
    r"(horas?|hrs?|minutos?|mins?)(\s+y\s+media)?",
    re.IGNORECASE,
)


def hora_de_hoy(hhmm: str | None, referencia: datetime) -> datetime | None:
    """Convierte "HH:MM" en un datetime del día de `referencia`. None si no se puede leer."""
    coincidencia = _PATRON_HORA.match(hhmm or "")
    if not coincidencia:
        return None
    horas, minutos = int(coincidencia.group(1)), int(coincidencia.group(2))
    if horas > 23 or minutos > 59:
        return None
    return referencia.replace(hour=horas, minute=minutos, second=0, microsecond=0)


def calcular_hora_preparacion(hhmm: str | None, referencia: datetime) -> datetime | None:
    """Hora de preparación de hoy; si quedaría en el futuro, es la de ayer."""
    hora = hora_de_hoy(hhmm, referencia)
    if hora is not None and hora > referencia:
        hora -= timedelta(days=1)
    return hora


def hora_relativa(texto: str, referencia: datetime) -> datetime | None:
    """Calcula en código frases como "hace una hora" o "hace 30 minutos" (la última que aparezca)."""
    coincidencias = list(_PATRON_HACE.finditer(texto))
    if not coincidencias:
        return None
    numero, unidad, y_media = coincidencias[-1].groups()
    numero = numero.lower()
    cantidad = 0.5 if numero == "media" else _NUMEROS.get(numero) or float(numero.replace(",", "."))
    if y_media:
        cantidad += 0.5
    minutos = cantidad * 60 if unidad.lower().startswith("h") else cantidad
    return (referencia - timedelta(minutes=minutos)).replace(second=0, microsecond=0)


def calcular_recoger_antes_de(hhmm: str | None, donante: Donante, referencia: datetime) -> datetime:
    """Hora límite de recogida: la que dio el donante o, si no, su cierre + 1 h (o ahora + 2 h)."""
    limite = hora_de_hoy(hhmm, referencia)
    if limite is not None and limite > referencia:
        return limite
    cierre = hora_de_hoy(donante.hora_cierre, referencia)
    if cierre is not None and cierre + timedelta(hours=1) > referencia:
        return cierre + timedelta(hours=1)
    return referencia + timedelta(hours=2)


def _describir(alimento: Alimento) -> str:
    return (
        f"{alimento.nombre}: {alimento.cantidad:g} {alimento.unidad}, {alimento.tipo.value}, "
        f"conservación {alimento.conservacion.value}"
    )


#: En comercios que cocinan, estos alimentos casi siempre están cocidos (preparado), no crudos.
COMERCIOS_QUE_COCINAN = ("fonda", "cocina", "restaurante", "comedor", "taquer", "loncher")
GUARNICIONES = ("arroz", "frijol", "pasta", "sopa", "espagueti", "lenteja", "garbanzo")
SENALES_DE_CRUDO = (
    "crud", "bolsa", "cerrad", "empaquet", "paquete", "sellad", "lata", "enlatad", "sin abrir", "sin cocer",
)


def corregir_tipo(alimento: Alimento, donante: Donante) -> Alimento:
    """Ante la duda, lo más estricto: el arroz o los frijoles de una fonda se tratan como preparados."""
    texto = f"{alimento.nombre} {alimento.observaciones}".lower()
    if (
        alimento.tipo == TipoAlimento.ABARROTE
        and any(c in donante.tipo_comercio.lower() for c in COMERCIOS_QUE_COCINAN)
        and any(g in texto for g in GUARNICIONES)
        and not any(s in texto for s in SENALES_DE_CRUDO)
    ):
        kg = estimar_kg(alimento.cantidad, alimento.unidad, TipoAlimento.PREPARADO)
        return alimento.model_copy(update={"tipo": TipoAlimento.PREPARADO, "kg_estimados": kg})
    return alimento


def _pregunta_por_defecto(sin_hora: list[Alimento], sin_conservacion: list[Alimento]) -> str:
    nombres = " y ".join(dict.fromkeys(a.nombre for a in [*sin_hora, *sin_conservacion]))
    if sin_hora and sin_conservacion:
        return (
            f"Sobre {nombres}: ¿a qué hora lo preparaste y cómo lo has guardado desde entonces "
            "(en el refri, caliente o a temperatura ambiente)?"
        )
    if sin_conservacion:
        return f"Sobre {nombres}: ¿cómo lo has guardado (en el refri, caliente o a temperatura ambiente)?"
    return f"Sobre {nombres}: ¿desde qué hora lo tienes así? Dime a qué hora lo preparaste o lo sacaste del refri."


# ------------------------------------------------------------------------- agente


class AgenteInterprete(Agente[SolicitudInterpretacion, ResultadoInterpretacion]):
    nombre = "Intérprete"

    def __init__(self, llm: ClienteLLM, bitacora: Bitacora, reloj: Callable[[], datetime] = ahora) -> None:
        super().__init__(llm, bitacora)
        self.reloj = reloj

    def ejecutar(self, entrada: SolicitudInterpretacion) -> ResultadoInterpretacion:
        did = entrada.donativo_id
        aclaraciones = entrada.texto.count(MARCA_ACLARACION)
        momento = self.reloj()
        self._anotar(
            TipoEntradaBitacora.ACCION,
            f"Consulto a {self.llm.nombre_modelo} con el esquema InterpretacionLLM"
            + (f" (aclaración {aclaraciones} de {MAX_ACLARACIONES})." if aclaraciones else "."),
            did,
            paso=1,
        )
        try:
            respuesta = self.llm.generar_json(
                self._prompt(entrada, momento), InterpretacionLLM, sistema=SISTEMA_INTERPRETE, temperatura=0.1
            )
        except ErrorLLM as e:
            self._anotar(
                TipoEntradaBitacora.ERROR, "El LLM no respondió; uso reglas.", did, paso=2, datos={"error": str(e)}
            )
            resultado = self._interpretar_con_reglas(entrada.texto)
            self._anotar(
                TipoEntradaBitacora.RESULTADO,
                f"Con reglas encontré {len(resultado.alimentos)} alimento(s)."
                if resultado.completo
                else f"Con reglas no encontré alimentos; pregunto: {' '.join(resultado.preguntas)}",
                did,
                paso=3,
                datos=resultado.model_dump(mode="json"),
            )
            return resultado

        self._anotar(TipoEntradaBitacora.PENSAMIENTO, respuesta.razonamiento, did, paso=2)
        resultado = self._postprocesar(respuesta, entrada, momento, aclaraciones)
        self._anotar(
            TipoEntradaBitacora.OBSERVACION,
            "; ".join(_describir(a) for a in resultado.alimentos) or "No identifiqué alimentos con cantidad.",
            did,
            paso=4,
            datos={"datos_faltantes": respuesta.datos_faltantes},
        )
        if resultado.completo:
            kg = round(sum(a.kg_estimados for a in resultado.alimentos), 2)
            resumen = f"Donativo completo: {len(resultado.alimentos)} alimento(s), {kg:g} kg estimados por código."
            if aclaraciones >= MAX_ACLARACIONES and respuesta.datos_faltantes:
                resumen += " Ya van dos aclaraciones; publico con lo que hay y la Inocuidad decide con lo desconocido."
        else:
            resumen = f"Pregunto: {' '.join(resultado.preguntas)}"
        self._anotar(TipoEntradaBitacora.RESULTADO, resumen, did, paso=5, datos=resultado.model_dump(mode="json"))
        return resultado

    @staticmethod
    def _prompt(entrada: SolicitudInterpretacion, momento: datetime) -> str:
        donante = entrada.donante
        return (
            f"Hora actual: {momento:%H:%M}\n"
            f"Comercio: {donante.nombre} ({donante.tipo_comercio}), cierra a las {donante.hora_cierre}\n"
            f"Mensaje del donante:\n{entrada.texto}"
        )

    def _postprocesar(
        self, respuesta: InterpretacionLLM, entrada: SolicitudInterpretacion, momento: datetime, aclaraciones: int
    ) -> ResultadoInterpretacion:
        """Lo que calcula el código, no el LLM: kilos, horas y si ya está completo."""
        alimentos: list[Alimento] = []
        for a in respuesta.alimentos:
            if a.cantidad <= 0 or not a.nombre.strip():
                continue
            propuesto = Alimento(
                nombre=a.nombre.strip(),
                cantidad=a.cantidad,
                unidad=a.unidad,
                tipo=a.tipo,
                conservacion=a.conservacion,
                kg_estimados=estimar_kg(a.cantidad, a.unidad, a.tipo),
                observaciones=a.observaciones,
            )
            corregido = corregir_tipo(propuesto, entrada.donante)
            if corregido.tipo != propuesto.tipo:
                self._anotar(
                    TipoEntradaBitacora.PENSAMIENTO,
                    f"Trato «{corregido.nombre}» como preparado y no como abarrote: en una "
                    f"{entrada.donante.tipo_comercio} casi siempre está cocido. Ante la duda, lo más estricto.",
                    entrada.donativo_id,
                    paso=3,
                )
            alimentos.append(corregido)
        hora_preparacion = hora_relativa(entrada.texto, momento) or calcular_hora_preparacion(
            respuesta.hora_preparacion, momento
        )
        recoger_antes_de = calcular_recoger_antes_de(respuesta.recoger_antes_de, entrada.donante, momento)

        perecederos = [a for a in alimentos if a.tipo in PERECEDEROS]
        sin_conservacion = [a for a in perecederos if a.conservacion == Conservacion.DESCONOCIDA]
        sin_hora = perecederos if hora_preparacion is None else []
        datos_completos = not sin_conservacion and not sin_hora

        if alimentos and (datos_completos or aclaraciones >= MAX_ACLARACIONES):
            return ResultadoInterpretacion(
                completo=True,
                alimentos=alimentos,
                hora_preparacion=hora_preparacion,
                recoger_antes_de=recoger_antes_de,
            )
        if not alimentos:
            pregunta = respuesta.pregunta or PREGUNTA_SIN_ALIMENTOS
        else:
            pregunta = respuesta.pregunta or _pregunta_por_defecto(sin_hora, sin_conservacion)
        return ResultadoInterpretacion(
            completo=False,
            alimentos=alimentos,
            hora_preparacion=hora_preparacion,
            recoger_antes_de=recoger_antes_de,
            preguntas=[pregunta],
        )

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
