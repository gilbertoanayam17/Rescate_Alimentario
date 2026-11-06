"""CAR-02 Agente de Inocuidad: dictamina si un donativo es apto para donarse.

DUEÑO: Gilberto (flujo 1).

1. Corre la cadena de reglas deterministas (`reglas_inocuidad`, Chain of Responsibility).
   Si dicen NO_APTO, ahí termina: el LLM no puede relajar un dictamen.
2. Busca en la NOM-251-SSA1-2009 y en los criterios de donación (RAG).
3. Le pide al LLM que mantenga o endurezca el dictamen preliminar con el esquema `EvaluacionLLM`.
4. Combina en código: el dictamen más estricto, la vida útil de las reglas y solo las citas
   que vienen de los fragmentos recuperados (defensa contra numerales inventados).

No cambies la firma del constructor ni de `ejecutar` (solo se agregan parámetros opcionales).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Callable

from pydantic import BaseModel

from rescate.agentes.base import Agente
from rescate.agentes.reglas_inocuidad import Hallazgo, combinar, crear_cadena, horas_desde
from rescate.bitacora import Bitacora
from rescate.dominio.enums import PERECEDEROS, Conservacion, Dictamen, TipoEntradaBitacora
from rescate.dominio.modelos import DictamenInocuidad, Donativo, ahora
from rescate.llm.cliente import ClienteLLM, ErrorLLM
from rescate.rag.base_conocimiento import BaseConocimiento, BaseConocimientoVacia, Fragmento


class EvaluacionLLM(BaseModel):
    razonamiento: str
    dictamen: Dictamen
    motivo: str  # 1 o 2 frases para el donante
    condiciones: list[str]
    citas: list[str]  # solo secciones de los fragmentos recibidos


SISTEMA_INOCUIDAD = """\
Eres el Agente de Inocuidad de Rescate Alimentario. Decides si un donativo es seguro para un \
comedor comunitario. La seguridad de las personas va primero: ante la duda, sé más estricto. \
Solo puedes mantener o endurecer el dictamen preliminar de las reglas, nunca relajarlo. Responde \
solo con el JSON del esquema.

- dictamen: apto, apto_con_condiciones o no_apto.
- Endurece solo si ves un riesgo concreto que las reglas no consideraron (por ejemplo, el mensaje \
describe contaminación, mal manejo o un alimento de alto riesgo). La hora de preparación y la \
conservación solo importan para los perecederos (preparado, lacteo, carne_pescado): el pan, la \
fruta, la verdura y los abarrotes cerrados son de bajo riesgo aunque no se sepa cómo se guardaron.
- razonamiento: 1 o 2 frases sobre qué revisaste y por qué decides así.
- motivo: 1 o 2 frases para el donante que expliquen el dictamen: qué riesgo hay y qué se debe \
cuidar. Amable, en español de México, sin saludos ni agradecimientos.
- condiciones: instrucciones concretas para el receptor y el recolector. Las condiciones \
preliminares ya se incluyen; escribe solo condiciones nuevas y distintas (máximo 2) o deja la lista vacía.
- citas: copia solo el texto de "Sección:" de los fragmentos que fundamenten tu dictamen, tal como \
viene; si ninguno aplica, deja la lista vacía. No inventes numerales.
- Las horas, los kilos y la vida útil ya los calculó el sistema: no los recalcules.
"""

FRASE_CONSERVACION = {
    Conservacion.REFRIGERADO: "en refrigeración",
    Conservacion.CONGELADO: "congelado",
    Conservacion.CALIENTE: "caliente",
    Conservacion.AMBIENTE: "a temperatura ambiente",
    Conservacion.DESCONOCIDA: "conservación desconocida",
}
TEMA_POR_REGLA = {
    "CI-02": "tiempo a temperatura ambiente",
    "CI-04": "refrigeración a 7 °C y cadena de frío",
    "CI-05": "comida caliente a más de 60 °C y recalentar a 74 °C",
    "CI-06": "vida útil",
}


_NUMERAL = re.compile(r"numeral\s+(\d+(?:\.\d+)+)", re.IGNORECASE)
_CRITERIO = re.compile(r"\bCI-0?(\d)\b", re.IGNORECASE)
_ETIQUETA = re.compile(r"^(\[\d+\]\s*)?secci[oó]n\s*:\s*", re.IGNORECASE)  # "[1] Sección: ..."
MAX_CONDICIONES_LLM = 2


def clave_cita(texto: str) -> str:
    """Forma canónica de una cita o sección, sin el tema.

    "NOM-251-SSA1-2009, numeral 7.3.3: tema" -> "NOM-251-SSA1-2009, numeral 7.3.3"
    "CI-04: Pollo en mole: ..."              -> "Criterio interno CI-04"
    """
    cabeza = _ETIQUETA.sub("", texto.strip()).split(":", 1)[0]
    numeral = _NUMERAL.search(cabeza)
    if numeral and "251" in cabeza:
        return f"NOM-251-SSA1-2009, numeral {numeral.group(1)}"
    criterio = _CRITERIO.search(cabeza)
    if criterio:
        return f"Criterio interno CI-0{criterio.group(1)}"
    return " ".join(cabeza.split())


def filtrar_citas(citas: list[str], fragmentos: list[Fragmento]) -> tuple[list[str], list[str]]:
    """Separa las citas del LLM en (aceptadas, descartadas): solo vale lo que está en los fragmentos recuperados."""
    validas = {clave_cita(f.seccion).casefold(): clave_cita(f.seccion) for f in fragmentos if f.seccion}
    aceptadas, descartadas = [], []
    for cita in citas:
        clave = clave_cita(cita).casefold()
        if clave in validas:
            aceptadas.append(validas[clave])
        elif cita.strip():
            descartadas.append(cita.strip())
    return aceptadas, descartadas


def _palabras(texto: str) -> list[str]:
    return re.findall(r"\w+", texto.lower())


def es_parecida(a: str, b: str) -> bool:
    """Dos condiciones dicen casi lo mismo si una contiene a la otra o comparten 60 % de sus palabras."""
    pa, pb = _palabras(a), _palabras(b)
    if not pa or not pb:
        return False
    ja, jb = " ".join(pa), " ".join(pb)
    comunes = set(pa) & set(pb)
    return ja in jb or jb in ja or len(comunes) / len(set(pa) | set(pb)) >= 0.6


def condiciones_nuevas(existentes: list[str], propuestas: list[str]) -> list[str]:
    """Las condiciones del LLM que no repiten a otra, como máximo MAX_CONDICIONES_LLM."""
    aceptadas: list[str] = []
    for c in (p.strip() for p in propuestas):
        if c and not any(es_parecida(c, x) for x in [*existentes, *aceptadas]):
            aceptadas.append(c)
    return aceptadas[:MAX_CONDICIONES_LLM]


def _sin_repetir(*listas: list[str]) -> list[str]:
    return list(dict.fromkeys(x for lista in listas for x in lista))


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
        momento = self.reloj()

        # 1. Reglas deterministas
        self._anotar(
            TipoEntradaBitacora.PENSAMIENTO,
            f"Reviso {entrada.resumen()} con las reglas de inocuidad.",
            did,
            paso=1,
        )
        hallazgos = crear_cadena().evaluar(entrada, momento)
        for hallazgo in hallazgos:
            self._anotar(
                TipoEntradaBitacora.OBSERVACION,
                f"{hallazgo.regla}: {hallazgo.motivo}",
                did,
                paso=2,
                datos=hallazgo.model_dump(mode="json"),
            )
        dictamen_reglas = combinar(hallazgos)
        if dictamen_reglas.dictamen == Dictamen.NO_APTO:
            return self._resultado(dictamen_reglas, did, "No consulto al LLM: no puede relajar un no apto.")

        # 2. RAG sobre la NOM-251 y los criterios
        consulta = self._consulta(entrada, hallazgos)
        self._anotar(
            TipoEntradaBitacora.ACCION, f"Busco en la NOM-251 y en los criterios: {consulta}", did, paso=3
        )
        try:
            fragmentos = self.base_conocimiento.buscar(consulta, k=4)
        except ErrorLLM as e:
            fragmentos = []
            self._anotar(
                TipoEntradaBitacora.ERROR,
                "No pude consultar la base de conocimiento.",
                did,
                paso=4,
                datos={"error": str(e)},
            )
        self._anotar(
            TipoEntradaBitacora.OBSERVACION,
            "Encontré: " + "; ".join(clave_cita(f.seccion) for f in fragmentos)
            if fragmentos
            else "No encontré fragmentos de referencia.",
            did,
            paso=4,
            datos={"fragmentos": [f.model_dump() for f in fragmentos]},
        )

        # 3. LLM: mantener o endurecer
        self._anotar(
            TipoEntradaBitacora.ACCION,
            f"Consulto a {self.llm.nombre_modelo} con el esquema EvaluacionLLM.",
            did,
            paso=5,
        )
        try:
            evaluacion = self.llm.generar_json(
                self._prompt(entrada, momento, hallazgos, dictamen_reglas, fragmentos),
                EvaluacionLLM,
                sistema=SISTEMA_INOCUIDAD,
                temperatura=0.1,
            )
        except ErrorLLM as e:
            self._anotar(
                TipoEntradaBitacora.ERROR,
                "El LLM no respondió; me quedo con el dictamen de las reglas.",
                did,
                paso=6,
                datos={"error": str(e)},
            )
            return self._resultado(dictamen_reglas, did)
        self._anotar(
            TipoEntradaBitacora.PENSAMIENTO,
            evaluacion.razonamiento,
            did,
            paso=6,
            datos=evaluacion.model_dump(mode="json"),
        )

        # 4. Combinación en código
        return self._resultado(self._combinar(dictamen_reglas, evaluacion, fragmentos, did), did)

    # ------------------------------------------------------------------ pasos

    def _combinar(
        self, reglas: DictamenInocuidad, evaluacion: EvaluacionLLM, fragmentos: list[Fragmento], did: str
    ) -> DictamenInocuidad:
        dictamen = Dictamen.mas_estricto(reglas.dictamen, evaluacion.dictamen)
        relajaba = evaluacion.dictamen.severidad < reglas.dictamen.severidad
        if relajaba:
            self._anotar(
                TipoEntradaBitacora.OBSERVACION,
                f"El LLM propuso «{evaluacion.dictamen.value}», pero no puede relajar el dictamen de las reglas; "
                f"queda «{reglas.dictamen.value}».",
                did,
                paso=7,
            )
        aceptadas, descartadas = filtrar_citas(evaluacion.citas, fragmentos)
        if descartadas:
            self._anotar(
                TipoEntradaBitacora.OBSERVACION,
                "Descarto citas que no vienen de los fragmentos recuperados: " + "; ".join(descartadas),
                did,
                paso=7,
                datos={"descartadas": descartadas},
            )
        if dictamen == Dictamen.NO_APTO:  # el LLM lo endureció
            return DictamenInocuidad(
                dictamen=dictamen,
                motivo=evaluacion.motivo,
                vida_util_horas=reglas.vida_util_horas,
                reglas_citadas=_sin_repetir(reglas.reglas_citadas, aceptadas),
            )
        return DictamenInocuidad(
            dictamen=dictamen,
            motivo=reglas.motivo if relajaba else evaluacion.motivo,
            # Un apto no lleva condiciones: si el LLM las cree necesarias, debió decir apto_con_condiciones
            condiciones=[]
            if dictamen == Dictamen.APTO
            else _sin_repetir(
                reglas.condiciones, condiciones_nuevas(reglas.condiciones, evaluacion.condiciones)
            ),
            vida_util_horas=reglas.vida_util_horas,
            requiere_refrigeracion=reglas.requiere_refrigeracion,
            reglas_citadas=_sin_repetir(reglas.reglas_citadas, aceptadas),
        )

    def _resultado(self, dictamen: DictamenInocuidad, did: str, nota: str = "") -> DictamenInocuidad:
        texto = f"{dictamen.dictamen.value}: {dictamen.motivo}"
        if dictamen.reglas_citadas:
            texto += f" Fundamento: {'; '.join(dictamen.reglas_citadas)}."
        if nota:
            texto += f" {nota}"
        self._anotar(
            TipoEntradaBitacora.RESULTADO, texto, did, paso=8, datos=dictamen.model_dump(mode="json")
        )
        return dictamen

    @staticmethod
    def _consulta(donativo: Donativo, hallazgos: list[Hallazgo]) -> str:
        alimentos = ", ".join(
            f"{a.nombre} ({a.tipo.value}, {FRASE_CONSERVACION[a.conservacion]})" for a in donativo.alimentos
        )
        temas = [TEMA_POR_REGLA[h.regla] for h in hallazgos if h.regla in TEMA_POR_REGLA]
        return f"{alimentos}; {', '.join(dict.fromkeys(temas))}" if temas else alimentos

    @staticmethod
    def _prompt(
        donativo: Donativo,
        momento: datetime,
        hallazgos: list[Hallazgo],
        reglas: DictamenInocuidad,
        fragmentos: list[Fragmento],
    ) -> str:
        lineas = ["Alimentos:"]
        for a in donativo.alimentos:
            obs = f", observaciones: {a.observaciones}" if a.observaciones else ""
            riesgo = "perecedero" if a.tipo in PERECEDEROS else "no perecedero, bajo riesgo"
            lineas.append(
                f"- {a.nombre}: {a.cantidad:g} {a.unidad}, tipo {a.tipo.value} ({riesgo}), "
                f"conservación {a.conservacion.value}{obs}"
            )
        horas = horas_desde(donativo.hora_preparacion, momento)
        if horas is None:
            lineas.append("Hora de preparación: desconocida")
        else:
            lineas.append(
                f"Hora de preparación: {donativo.hora_preparacion:%H:%M} (hace {round(horas, 1):g} h, calculado por el sistema)"
            )
        lineas.append(f"Mensaje original del donante: {donativo.texto_original}")
        lineas.append("")
        lineas.append(f"Dictamen preliminar de las reglas: {reglas.dictamen.value}")
        lineas.append(f"Motivo preliminar: {reglas.motivo}")
        lineas.extend(f"- {h.regla}: {h.motivo}" for h in hallazgos)
        if reglas.condiciones:
            lineas.append("Condiciones preliminares: " + "; ".join(reglas.condiciones))
        if reglas.vida_util_horas is not None:
            vida = f"Vida útil (calculada): {reglas.vida_util_horas:g} h desde su preparación"
            if horas is not None:
                vida += f"; le quedan {max(0.0, round(reglas.vida_util_horas - horas, 1)):g} h"
            lineas.append(vida)
        lineas.append("")
        if fragmentos:
            lineas.append("Fragmentos de referencia:")
            for i, f in enumerate(fragmentos, 1):
                lineas.append(f"[{i}] Sección: {f.seccion}\n{f.texto}")
        else:
            lineas.append("Fragmentos de referencia: ninguno (deja citas vacía).")
        return "\n".join(lineas)
