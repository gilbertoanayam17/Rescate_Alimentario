"""CAR-07 Agente Predictor: anticipa excedentes y redacta el aviso al donante.

DUEÑO: Gilberto.

El código calcula el patrón, los kilos y la confianza (`rescate.herramientas.patrones`). El LLM
solo decide si vale la pena avisar y redacta el mensaje; su respuesta se valida (no vacía, 300
caracteres o menos y sin cifras de kilos distintas de las calculadas). Si el LLM falla o responde
algo inválido, se usa una plantilla.
"""
from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel

from rescate.agentes.base import Agente
from rescate.agentes.seguridad_prompt import (
    REGLA_DATOS,
    delimitar,
    limpiar_texto_usuario,
)
from rescate.dominio.enums import TipoAlimento, TipoEntradaBitacora
from rescate.dominio.modelos import Donante, Pronostico
from rescate.herramientas.compatibilidad import NOMBRE_TIPO
from rescate.herramientas.patrones import DIAS_PLURAL
from rescate.llm.cliente import ErrorLLM

CONFIANZA_MINIMA = 0.5
MAXIMO_MENSAJE = 300
PLANTILLA = "Los {dia} sueles donar {descripcion} (unos {kg:g} kg). ¿Quieres publicarlo hoy?"
_KILOS = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:kg|kgs|kilos?|kilogramos?)\b", re.IGNORECASE)


class SolicitudPronostico(BaseModel):
    donante: Donante
    fecha: date
    patrones: list[dict] = []  # Patron como dict (dataclasses.asdict)


class DecisionPronostico(BaseModel):
    razonamiento: str
    avisar: bool
    mensaje: str  # 1 o 2 frases al donante, español de México


SISTEMA_PREDICTOR = f"""\
Eres el Agente Predictor de Rescate Alimentario, una plataforma que lleva la comida que les sobra \
a pequeños comercios de Guadalajara a comedores comunitarios. El sistema ya detectó un patrón: \
qué suele donar este comercio en este día de la semana, cuántos kilos y con qué confianza. Tú \
decides si vale la pena avisarle hoy y redactas el aviso. Responde solo con el JSON del esquema.

- avisar: true si el patrón es útil para el comercio (es frecuente y la cantidad vale la pena); \
false si es poco claro o no aporta.
- mensaje: 1 o 2 frases cortas y amables, en español de México, que le recuerden lo que suele \
donar ese día y lo inviten a publicarlo. Sin saludos largos ni agradecimientos.
- Si mencionas kilos, usa exactamente los kg_promedio que te da el sistema. No inventes cifras.
- razonamiento: 1 frase sobre por qué decides avisar o no.
- {REGLA_DATOS.format(etiqueta="datos_patron")}
"""


def cifras_validas(mensaje: str, kg: float) -> bool:
    """¿Las cifras de kilos del mensaje coinciden con las calculadas (o su redondeo)?"""
    permitidas = {round(kg, 1), float(round(kg))}
    for texto in _KILOS.findall(mensaje):
        valor = float(texto.replace(",", "."))
        if not any(abs(valor - p) < 0.05 for p in permitidas):
            return False
    return True


def mensaje_de_plantilla(patron: dict) -> str:
    return PLANTILLA.format(
        dia=DIAS_PLURAL[patron["dia_semana"]], descripcion=patron["descripcion"], kg=patron["kg_promedio"]
    )


class AgentePredictor(Agente[SolicitudPronostico, list[Pronostico]]):
    nombre = "Predictor"

    def ejecutar(self, entrada: SolicitudPronostico) -> list[Pronostico]:
        donante = entrada.donante
        if not entrada.patrones:
            return []
        self._anotar(
            TipoEntradaBitacora.PENSAMIENTO,
            f"{donante.nombre}, {DIAS_PLURAL[entrada.fecha.weekday()]}: "
            + "; ".join(
                f"{p['descripcion']} ({p['tipo']}), {p['semanas_con_donativo']} de {p['semanas_observadas']} "
                f"semanas, unos {p['kg_promedio']:g} kg"
                for p in entrada.patrones
            ),
            paso=1,
            datos={"donante_id": donante.id, "fecha": entrada.fecha.isoformat()},
        )
        pronosticos = []
        for patron in entrada.patrones:
            if patron["confianza"] < CONFIANZA_MINIMA:
                self._anotar(
                    TipoEntradaBitacora.OBSERVACION,
                    f"Descarto «{patron['descripcion']}»: confianza {patron['confianza']:.0%}, menor a "
                    f"{CONFIANZA_MINIMA:.0%}.",
                    paso=2,
                )
                continue
            mensaje = self._decidir(donante, entrada.fecha, patron)
            if mensaje is None:
                continue
            pronosticos.append(
                Pronostico(
                    donante_id=donante.id,
                    fecha=entrada.fecha,
                    tipo=TipoAlimento(patron["tipo"]),
                    descripcion=patron["descripcion"],
                    kg_esperados=patron["kg_promedio"],
                    confianza=patron["confianza"],
                    mensaje=mensaje,
                )
            )
        self._anotar(
            TipoEntradaBitacora.RESULTADO,
            f"{len(pronosticos)} pronóstico(s) para {donante.nombre}: "
            + ("; ".join(p.mensaje for p in pronosticos) or "ninguno"),
            paso=5,
            datos={"donante_id": donante.id, "pronosticos": [p.model_dump(mode="json") for p in pronosticos]},
        )
        return pronosticos

    def _decidir(self, donante: Donante, fecha: date, patron: dict) -> str | None:
        """El mensaje a enviar, o None si el LLM decide no avisar."""
        plantilla = mensaje_de_plantilla(patron)
        self._anotar(
            TipoEntradaBitacora.ACCION,
            f"Consulto a {self.llm.nombre_modelo} con el esquema DecisionPronostico para «{patron['descripcion']}».",
            paso=2,
        )
        try:
            decision = self.llm.generar_json(
                self._prompt(donante, fecha, patron), DecisionPronostico, sistema=SISTEMA_PREDICTOR, temperatura=0.3
            )
        except ErrorLLM as e:
            self._anotar(
                TipoEntradaBitacora.ERROR,
                "El LLM no respondió; aviso con la plantilla.",
                paso=3,
                datos={"error": str(e)},
            )
            return plantilla
        self._anotar(TipoEntradaBitacora.PENSAMIENTO, decision.razonamiento, paso=3)
        if not decision.avisar:
            self._anotar(TipoEntradaBitacora.OBSERVACION, "El LLM decidió no avisar hoy.", paso=4)
            return None
        mensaje = limpiar_texto_usuario(decision.mensaje, maximo=10_000).replace("\n", " ")
        if not mensaje or len(mensaje) > MAXIMO_MENSAJE or not cifras_validas(mensaje, patron["kg_promedio"]):
            self._anotar(
                TipoEntradaBitacora.OBSERVACION,
                "El mensaje del LLM no pasa la validación (vacío, muy largo o con kilos distintos a los "
                f"calculados: {patron['kg_promedio']:g} kg); uso la plantilla.",
                paso=4,
                datos={"mensaje_llm": decision.mensaje},
            )
            return plantilla
        return mensaje

    @staticmethod
    def _prompt(donante: Donante, fecha: date, patron: dict) -> str:
        datos = (
            f"Comercio: {limpiar_texto_usuario(donante.nombre, maximo=100)} ({donante.tipo_comercio})\n"
            f"Día: {DIAS_PLURAL[fecha.weekday()]}\n"
            f"Suele donar: {limpiar_texto_usuario(patron['descripcion'], maximo=120)} "
            f"({NOMBRE_TIPO.get(TipoAlimento(patron['tipo']), patron['tipo'])})\n"
            f"Semanas con donativo ese día: {patron['semanas_con_donativo']} de {patron['semanas_observadas']}\n"
            f"kg_promedio (calculado por el sistema): {patron['kg_promedio']:g}"
        )
        return delimitar("datos_patron", datos)
