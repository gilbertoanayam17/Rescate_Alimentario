"""CAR-02 Reglas deterministas de inocuidad, con el patrón Chain of Responsibility.

DUEÑO: Gilberto (flujo 1).

Cada regla es un eslabón: revisa el donativo, agrega su hallazgo (si lo hay) y pasa al
siguiente. `combinar` junta los hallazgos en un DictamenInocuidad tomando siempre lo más
estricto. Funcionan sin LLM y son la base del dictamen: el LLM puede endurecerlo, nunca
relajarlo.

Citas: de la NOM-251-SSA1-2009 solo se citan los numerales verificados en el texto oficial
(5.5.2, 7.3.2 y 7.3.3). Los umbrales de tiempo son criterios internos del proyecto.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import datetime, timedelta

from pydantic import BaseModel

from rescate.dominio.enums import PERECEDEROS, Conservacion, Dictamen, TipoAlimento
from rescate.dominio.modelos import Alimento, DictamenInocuidad, Donativo

NOM_REFRIGERACION = "NOM-251-SSA1-2009, numeral 5.5.2"  # refrigeración a 7 °C como máximo
NOM_RECALENTAR = "NOM-251-SSA1-2009, numeral 7.3.2"  # recalentar a 74 °C como mínimo
NOM_TEMPERATURAS = "NOM-251-SSA1-2009, numeral 7.3.3"  # calientes > 60 °C, fríos <= 7 °C

HORAS_SIN_CONTROL = 2  # CI-02: máximo de horas de un perecedero a temperatura ambiente

CONDICION_FRIO = "Mantener a 7 °C o menos"
CONDICION_CALIENTE = (
    "Mantener por encima de 60 °C o refrigerar a 7 °C o menos; recalentar a 74 °C antes de servir"
)


def criterio(codigo: str) -> str:
    return f"Criterio interno {codigo}"


class Hallazgo(BaseModel):
    regla: str  # "CI-02"
    dictamen: Dictamen
    motivo: str
    condiciones: list[str] = []
    vida_util_horas: float | None = None
    requiere_refrigeracion: bool = False
    citas: list[str] = []  # "NOM-251-SSA1-2009, numeral 7.3.3" o "Criterio interno CI-02"


# ------------------------------------------------------------------ utilidades


def horas_desde(hora: datetime | None, ahora: datetime) -> float | None:
    """Horas transcurridas desde `hora` (nunca negativas). None si no se conoce."""
    if hora is None:
        return None
    return max(0.0, (ahora - hora).total_seconds() / 3600)


def _h(horas: float) -> str:
    return f"{round(horas, 1):g} h"


def _nombres(alimentos: list[Alimento]) -> str:
    return ", ".join(dict.fromkeys(a.nombre for a in alimentos))


def _etiqueta(alimentos: list[Alimento]) -> str:
    """Nombres con mayúscula inicial, para empezar el motivo: "Pollo en mole: ..."."""
    nombres = _nombres(alimentos)
    return nombres[:1].upper() + nombres[1:]


def _buscar(patrones: list[str], texto: str) -> str | None:
    """Devuelve el primer fragmento del texto que coincide con algún patrón."""
    for patron in patrones:
        coincidencia = re.search(patron, texto, re.IGNORECASE)
        if coincidencia:
            return coincidencia.group(0)
    return None


def _es_perecedero(alimento: Alimento) -> bool:
    return alimento.tipo in PERECEDEROS


# ------------------------------------------------------------- eslabón base


class ReglaInocuidad(ABC):
    """Eslabón de la cadena de responsabilidad."""

    codigo: str = "CI-00"

    def __init__(self) -> None:
        self._siguiente: ReglaInocuidad | None = None

    def enlazar(self, siguiente: ReglaInocuidad) -> ReglaInocuidad:
        """Conecta el siguiente eslabón y lo devuelve para encadenar: a.enlazar(b).enlazar(c)."""
        self._siguiente = siguiente
        return siguiente

    def evaluar(self, donativo: Donativo, ahora: datetime, hallazgos: list[Hallazgo] | None = None) -> list[Hallazgo]:
        hallazgos = [] if hallazgos is None else hallazgos
        hallazgo = self.revisar(donativo, ahora)
        if hallazgo is not None:
            hallazgos.append(hallazgo)
        if self._siguiente is not None:
            return self._siguiente.evaluar(donativo, ahora, hallazgos)
        return hallazgos

    @abstractmethod
    def revisar(self, donativo: Donativo, ahora: datetime) -> Hallazgo | None: ...


# ------------------------------------------------------------------- reglas


class ReglaSenalesDeterioro(ReglaInocuidad):
    """CI-01: el donante describe señales de deterioro."""

    codigo = "CI-01"
    PATRONES = [
        r"huele\s+(mal|feo|raro|agrio)", r"olor\s+(raro|feo|agrio)", r"sabe\s+(raro|feo|agrio)",
        r"\bmoho", r"\bmohos[oa]s?\b", r"\bagri[oa]s?\b", r"\bpodrid[oa]s?\b", r"\branci[oa]s?\b",
        r"\bcaducad[oa]s?\b", r"\bvencid[oa]s?\b", r"\bbabos[oa]s?\b", r"ech(ado|ada|ó|o)\s+a\s+perder",
    ]

    def revisar(self, donativo: Donativo, ahora: datetime) -> Hallazgo | None:
        texto = " ".join([donativo.texto_original, *(a.observaciones for a in donativo.alimentos)])
        senal = _buscar(self.PATRONES, texto)
        if senal is None:
            return None
        return Hallazgo(
            regla=self.codigo,
            dictamen=Dictamen.NO_APTO,
            motivo=f"El donante menciona una señal de deterioro («{senal}»); por seguridad no se dona.",
            citas=[criterio(self.codigo)],
        )


class ReglaEmpaque(ReglaInocuidad):
    """CI-07: abarrotes con el empaque abierto o dañado."""

    codigo = "CI-07"
    PATRONES = [
        r"\babiert[oa]s?\b", r"\babollad[oa]s?\b", r"\binflad[oa]s?\b", r"sin\s+etiqueta",
        r"\bgolpead[oa]s?\b", r"\boxidad[oa]s?\b",
    ]

    def revisar(self, donativo: Donativo, ahora: datetime) -> Hallazgo | None:
        abarrotes = [a for a in donativo.alimentos if a.tipo == TipoAlimento.ABARROTE]
        if not abarrotes:
            return None
        texto = " ".join([donativo.texto_original, *(f"{a.nombre} {a.observaciones}" for a in abarrotes)])
        senal = _buscar(self.PATRONES, texto)
        if senal is None:
            return None
        return Hallazgo(
            regla=self.codigo,
            dictamen=Dictamen.NO_APTO,
            motivo=f"{_etiqueta(abarrotes)}: el empaque está dañado o abierto («{senal}»); no se puede garantizar su inocuidad.",
            citas=[criterio(self.codigo)],
        )


class ReglaSinControlTemperatura(ReglaInocuidad):
    """CI-02: perecedero a temperatura ambiente. Más de 2 h: no apto; hasta 2 h: con condiciones."""

    codigo = "CI-02"

    def revisar(self, donativo: Donativo, ahora: datetime) -> Hallazgo | None:
        horas = horas_desde(donativo.hora_preparacion, ahora)
        al_ambiente = [
            a for a in donativo.alimentos if _es_perecedero(a) and a.conservacion == Conservacion.AMBIENTE
        ]
        if not al_ambiente or horas is None:
            return None  # sin hora de preparación lo resuelve CI-03
        if horas > HORAS_SIN_CONTROL:
            return Hallazgo(
                regla=self.codigo,
                dictamen=Dictamen.NO_APTO,
                motivo=(
                    f"{_etiqueta(al_ambiente)}: {_h(horas)} a temperatura ambiente. Un perecedero sin control "
                    f"de temperatura no se dona después de {HORAS_SIN_CONTROL} h."
                ),
                citas=[criterio(self.codigo), NOM_TEMPERATURAS],
            )
        limite = donativo.hora_preparacion + timedelta(hours=HORAS_SIN_CONTROL)
        return Hallazgo(
            regla=self.codigo,
            dictamen=Dictamen.APTO_CON_CONDICIONES,
            motivo=f"{_etiqueta(al_ambiente)}: está a temperatura ambiente; hay que refrigerarlo o servirlo pronto.",
            condiciones=[f"Refrigerar a 7 °C o menos o servir antes de las {limite:%H:%M}"],
            requiere_refrigeracion=True,
            citas=[criterio(self.codigo), NOM_TEMPERATURAS],
        )


class ReglaOrigenDesconocido(ReglaInocuidad):
    """CI-03: perecedero sin hora de preparación o sin conservación conocida."""

    codigo = "CI-03"

    def revisar(self, donativo: Donativo, ahora: datetime) -> Hallazgo | None:
        perecederos = [a for a in donativo.alimentos if _es_perecedero(a)]
        if not perecederos:
            return None
        sin_conservacion = [a for a in perecederos if a.conservacion == Conservacion.DESCONOCIDA]
        sin_hora = donativo.hora_preparacion is None
        faltas = (["cuándo se preparó"] if sin_hora else []) + (["cómo se ha conservado"] if sin_conservacion else [])
        if not faltas:
            return None
        afectados = perecederos if sin_hora else sin_conservacion
        return Hallazgo(
            regla=self.codigo,
            dictamen=Dictamen.NO_APTO,
            motivo=(
                f"{_etiqueta(afectados)}: no se sabe {' ni '.join(faltas)}; sin ese dato no se puede "
                "garantizar que sea seguro."
            ),
            citas=[criterio(self.codigo)],
        )


class ReglaCadenaFrio(ReglaInocuidad):
    """CI-04: lácteos, carnes y pescados, o cualquier alimento refrigerado o congelado."""

    codigo = "CI-04"
    FRIOS = {Conservacion.REFRIGERADO, Conservacion.CONGELADO}

    def revisar(self, donativo: Donativo, ahora: datetime) -> Hallazgo | None:
        en_frio = [
            a for a in donativo.alimentos
            if a.tipo in {TipoAlimento.LACTEO, TipoAlimento.CARNE_PESCADO} or a.conservacion in self.FRIOS
        ]
        if not en_frio:
            return None
        return Hallazgo(
            regla=self.codigo,
            dictamen=Dictamen.APTO_CON_CONDICIONES,
            motivo=f"{_etiqueta(en_frio)}: necesita cadena de frío durante la recolección y la entrega.",
            condiciones=[CONDICION_FRIO],
            requiere_refrigeracion=True,
            citas=[NOM_TEMPERATURAS, NOM_REFRIGERACION],
        )


class ReglaComidaCaliente(ReglaInocuidad):
    """CI-05: comida que se conserva caliente."""

    codigo = "CI-05"

    def revisar(self, donativo: Donativo, ahora: datetime) -> Hallazgo | None:
        calientes = [a for a in donativo.alimentos if a.conservacion == Conservacion.CALIENTE]
        if not calientes:
            return None
        return Hallazgo(
            regla=self.codigo,
            dictamen=Dictamen.APTO_CON_CONDICIONES,
            motivo=f"{_etiqueta(calientes)}: se conserva caliente; hay que mantenerlo caliente o enfriarlo rápido.",
            condiciones=[CONDICION_CALIENTE],
            requiere_refrigeracion=True,
            citas=[NOM_TEMPERATURAS, NOM_RECALENTAR],
        )


class ReglaVidaUtil(ReglaInocuidad):
    """CI-06: vida útil por tipo. Devuelve las horas que le QUEDAN; si ya se acabó, no apto."""

    codigo = "CI-06"
    VIDA_BASE = {
        TipoAlimento.PANADERIA: 24,
        TipoAlimento.FRUTA_VERDURA: 48,
        TipoAlimento.LACTEO: 24,
        TipoAlimento.CARNE_PESCADO: 12,
        TipoAlimento.ABARROTE: 720,
    }
    VIDA_PREPARADO = {Conservacion.REFRIGERADO: 12, Conservacion.CONGELADO: 12, Conservacion.CALIENTE: 4}
    VIDA_OTRO = 24

    @classmethod
    def vida_base(cls, alimento: Alimento) -> float:
        if _es_perecedero(alimento) and alimento.conservacion in {Conservacion.AMBIENTE, Conservacion.DESCONOCIDA}:
            return HORAS_SIN_CONTROL
        if alimento.tipo == TipoAlimento.PREPARADO:
            return cls.VIDA_PREPARADO[alimento.conservacion]
        return cls.VIDA_BASE.get(alimento.tipo, cls.VIDA_OTRO)

    def revisar(self, donativo: Donativo, ahora: datetime) -> Hallazgo | None:
        if not donativo.alimentos:
            return None
        transcurridas = horas_desde(donativo.hora_preparacion, ahora) or 0.0
        restantes = {a.nombre: self.vida_base(a) - transcurridas for a in donativo.alimentos}
        nombre, minima = min(restantes.items(), key=lambda par: par[1])
        if minima <= 0:
            return Hallazgo(
                regla=self.codigo,
                dictamen=Dictamen.NO_APTO,
                motivo=f"{nombre[:1].upper() + nombre[1:]}: ya pasó su vida útil ({_h(transcurridas)} desde su preparación).",
                vida_util_horas=0,
                citas=[criterio(self.codigo)],
            )
        return Hallazgo(
            regla=self.codigo,
            dictamen=Dictamen.APTO,
            motivo=f"Vida útil restante estimada: {_h(minima)} ({nombre}).",
            vida_util_horas=round(minima, 1),
            citas=[criterio(self.codigo)],
        )


# ----------------------------------------------------------- cadena y combinación


def crear_cadena() -> ReglaInocuidad:
    """Arma la cadena en el orden de la tabla de criterios y devuelve el primer eslabón."""
    primera = ReglaSenalesDeterioro()
    (
        primera.enlazar(ReglaEmpaque())
        .enlazar(ReglaSinControlTemperatura())
        .enlazar(ReglaOrigenDesconocido())
        .enlazar(ReglaCadenaFrio())
        .enlazar(ReglaComidaCaliente())
        .enlazar(ReglaVidaUtil())
    )
    return primera


def _sin_repetir(listas: list[list[str]]) -> list[str]:
    return list(dict.fromkeys(x for lista in listas for x in lista))


def combinar(hallazgos: list[Hallazgo]) -> DictamenInocuidad:
    """Junta los hallazgos: dictamen más estricto, vida útil mínima, condiciones y citas sin repetir."""
    dictamen = Dictamen.APTO
    for h in hallazgos:
        dictamen = Dictamen.mas_estricto(dictamen, h.dictamen)
    vidas = [h.vida_util_horas for h in hallazgos if h.vida_util_horas is not None]
    vida_util = min(vidas) if vidas else None

    if dictamen == Dictamen.APTO:
        return DictamenInocuidad(
            dictamen=Dictamen.APTO,
            motivo="Alimentos de bajo riesgo.",
            vida_util_horas=vida_util,
            reglas_citadas=_sin_repetir([h.citas for h in hallazgos]),
        )

    severos = [h for h in hallazgos if h.dictamen == dictamen]
    if dictamen == Dictamen.NO_APTO:
        # Al donante solo le sirve saber qué regla lo rechazó; las condiciones de manejo ya no aplican.
        return DictamenInocuidad(
            dictamen=Dictamen.NO_APTO,
            motivo=severos[0].motivo,
            vida_util_horas=vida_util,
            reglas_citadas=_sin_repetir([h.citas for h in severos]),
        )
    return DictamenInocuidad(
        dictamen=dictamen,
        motivo=severos[0].motivo,
        condiciones=_sin_repetir([h.condiciones for h in hallazgos]),
        vida_util_horas=vida_util,
        requiere_refrigeracion=any(h.requiere_refrigeracion for h in hallazgos),
        reglas_citadas=_sin_repetir([h.citas for h in hallazgos]),
    )


def evaluar_con_reglas(donativo: Donativo, ahora: datetime) -> tuple[list[Hallazgo], DictamenInocuidad]:
    """Atajo: corre la cadena completa y combina."""
    hallazgos = crear_cadena().evaluar(donativo, ahora)
    return hallazgos, combinar(hallazgos)
