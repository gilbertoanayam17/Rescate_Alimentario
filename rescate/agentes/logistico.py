"""Agente Logístico (CAR-04): agrupa donativos cercanos en una ruta para el recolector.

Las herramientas calculan (rescate/herramientas/rutas.py); el LLM solo elige entre las rutas
calculadas y explica. Pasos:

1. Candidatos: los donativos que el recolector ya lleva, más los disponibles a 6 km o menos,
   hasta la capacidad de su transporte.
2. Calcula una ruta con cada estrategia (vecino más cercano y primero el más urgente).
3. Si son iguales o solo una cumple los límites, elige sin LLM. Si no, el LLM elige con
   `DecisionRuta`; se valida que no elija una ruta que incumple cuando la otra cumple.
4. Respaldo determinista (ErrorLLM o elección inválida): la de menos km entre las que cumplen.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from rescate.agentes.base import Agente
from rescate.agentes.seguridad_prompt import REGLA_DATOS, delimitar
from rescate.dominio.enums import TipoEntradaBitacora
from rescate.dominio.modelos import Donativo, Participante, Recolector, ahora
from rescate.herramientas.geo import haversine_km
from rescate.herramientas.horario import limite_recoleccion
from rescate.herramientas.rutas import ESTRATEGIAS, Parada, RutaCalculada, capacidad
from rescate.llm.cliente import ErrorLLM

#: Solo se proponen donativos a esta distancia del recolector o menos.
RADIO_KM = 6.0

NOMBRE_ESTRATEGIA = {
    "vecino_mas_cercano": "vecino más cercano",
    "primero_el_mas_urgente": "primero el más urgente",
}

SISTEMA_LOGISTICO = (
    "Eres el Agente Logístico de Rescate Alimentario. El sistema ya calculó dos rutas de "
    "recolección con kilómetros, horas de llegada y retrasos. Elige una con su nombre exacto "
    "(vecino_mas_cercano o primero_el_mas_urgente). Nunca elijas una ruta con retrasos si la otra "
    "no tiene. No hagas cálculos ni inventes datos: usa solo las cifras dadas. Explica en una o dos "
    "frases, en español de México, por qué conviene al voluntario. Responde con el esquema JSON. "
    + REGLA_DATOS.format(etiqueta="datos_ruta")
)


class SolicitudRuta(BaseModel):
    recolector: Recolector
    tomados: list[Donativo] = []  # los que ya lleva
    disponibles: list[Donativo] = []  # aceptados, sin recolector
    participantes: dict[str, Participante] = {}  # donantes y receptores involucrados, por id
    salida: datetime | None = None  # por omisión, ahora


class DecisionRuta(BaseModel):
    razonamiento: str = Field(min_length=1)
    estrategia: Literal["vecino_mas_cercano", "primero_el_mas_urgente"]
    explicacion: str = Field(min_length=1)


class ParadaRuta(BaseModel):
    orden: int
    tipo: Literal["recoger", "entregar"]
    donativo_id: str
    nombre: str
    lat: float
    lon: float
    llegada: datetime
    limite: datetime | None = None
    km_tramo: float


class RutaRecoleccion(BaseModel):
    """La ruta que se le propone al recolector."""

    estrategia: str
    paradas: list[ParadaRuta]
    km_total: float
    minutos: float
    cumple_limites: bool
    retrasos: list[str] = []
    explicacion: str
    por_tomar: list[str]  # disponibles incluidos en la ruta (los toma "Tomar estos donativos")
    sin_capacidad: list[str] = []  # disponibles cercanos que no cupieron


class AgenteLogistico(Agente[SolicitudRuta, RutaRecoleccion | None]):
    nombre = "Logístico"

    def ejecutar(self, entrada: SolicitudRuta) -> RutaRecoleccion | None:
        r = entrada.recolector
        salida = entrada.salida or ahora()
        cupo = capacidad(r.transporte)
        self._anotar(
            TipoEntradaBitacora.PENSAMIENTO,
            f"Busco donativos para {r.nombre} ({r.transporte}, hasta {cupo:g} kg) a {RADIO_KM:g} km o menos.",
        )
        elegidos, sin_capacidad = self._candidatos(entrada, salida, cupo)
        if not entrada.tomados and not elegidos:
            self._anotar(TipoEntradaBitacora.RESULTADO, "No hay donativos cercanos que quepan; no propongo ruta.")
            return None

        paradas = self._paradas(entrada, elegidos, salida)
        self._anotar(
            TipoEntradaBitacora.ACCION,
            f"Calculo {len(ESTRATEGIAS)} rutas con {len(paradas)} paradas.",
            datos={"donativos": [d.id for d in entrada.tomados + elegidos], "sin_capacidad": sin_capacidad},
        )
        rutas = {nombre: e.ordenar(r.ubicacion, paradas, r.transporte, salida) for nombre, e in ESTRATEGIAS.items()}
        self._anotar(
            TipoEntradaBitacora.OBSERVACION,
            "; ".join(self._resumen(ruta) for ruta in rutas.values()),
        )
        ruta, explicacion = self._elegir(rutas, entrada)
        resultado = self._a_modelo(ruta, explicacion, [d.id for d in elegidos], sin_capacidad)
        self._anotar(
            TipoEntradaBitacora.RESULTADO,
            f"Propongo {NOMBRE_ESTRATEGIA[ruta.estrategia]}: {explicacion}",
            datos={"km": ruta.km_total, "minutos": ruta.minutos, "cumple": ruta.cumple_limites},
        )
        return resultado

    # ------------------------------------------------------------------ pasos

    def _candidatos(
        self, entrada: SolicitudRuta, salida: datetime, cupo: float
    ) -> tuple[list[Donativo], list[str]]:
        """Disponibles cercanos, del más urgente al menos urgente, mientras quepan."""
        carga = sum(d.kg_totales for d in entrada.tomados)
        cercanos = []
        for d in entrada.disponibles:
            donante = entrada.participantes.get(d.donante_id)
            if donante and d.receptor_id in entrada.participantes:
                km = haversine_km(entrada.recolector.ubicacion, donante.ubicacion)
                if km <= RADIO_KM:
                    cercanos.append((limite_recoleccion(d, salida), km, d))
        elegidos, sin_capacidad = [], []
        for _, _, d in sorted(cercanos, key=lambda x: (x[0], x[1], x[2].id)):
            if carga + d.kg_totales <= cupo:
                elegidos.append(d)
                carga += d.kg_totales
            else:
                sin_capacidad.append(d.id)
        return elegidos, sin_capacidad

    def _paradas(self, entrada: SolicitudRuta, elegidos: list[Donativo], salida: datetime) -> list[Parada]:
        paradas = []
        for d in elegidos:
            donante = entrada.participantes[d.donante_id]
            paradas.append(Parada("recoger", d.id, donante.nombre, donante.ubicacion, limite_recoleccion(d, salida)))
        for d in entrada.tomados + elegidos:
            receptor = entrada.participantes.get(d.receptor_id)
            if receptor:
                paradas.append(Parada("entregar", d.id, receptor.nombre, receptor.ubicacion))
        return paradas

    def _elegir(self, rutas: dict[str, RutaCalculada], entrada: SolicitudRuta) -> tuple[RutaCalculada, str]:
        lista = list(rutas.values())
        cumplen = [r for r in lista if r.cumple_limites]
        respaldo = min(cumplen or lista, key=lambda r: (r.km_total, r.minutos, r.estrategia))
        if len({tuple(r.orden()) for r in lista}) == 1:
            return respaldo, "Las dos estrategias dan el mismo orden; " + self._resumen(respaldo)
        if len(cumplen) == 1:
            return cumplen[0], "Es la única ruta que llega a tiempo a todas las recolecciones; " + self._resumen(
                cumplen[0]
            )
        try:
            decision = self.llm.generar_json(self._prompt(rutas, entrada), DecisionRuta, sistema=SISTEMA_LOGISTICO)
            self._anotar(TipoEntradaBitacora.PENSAMIENTO, decision.razonamiento)
            elegida = rutas[decision.estrategia]
            if not elegida.cumple_limites and cumplen:
                raise ErrorLLM("El LLM eligió una ruta con retrasos aunque otra llega a tiempo")
            return elegida, decision.explicacion.strip()
        except (ErrorLLM, ValidationError) as exc:
            self._anotar(TipoEntradaBitacora.ERROR, f"{exc}; uso la ruta de menos km que cumple.")
            return respaldo, "Ruta de menos kilómetros entre las que cumplen; " + self._resumen(respaldo)

    def _prompt(self, rutas: dict[str, RutaCalculada], entrada: SolicitudRuta) -> str:
        datos = {
            "transporte": entrada.recolector.transporte,
            "rutas": [
                {
                    "estrategia": r.estrategia,
                    "km_total": r.km_total,
                    "minutos": r.minutos,
                    "cumple_limites": r.cumple_limites,
                    "retrasos": r.retrasos,
                    "paradas": [
                        f"{p.tipo} {p.nombre} ({t:%H:%M})" for p, t in zip(r.paradas, r.llegadas, strict=True)
                    ],
                }
                for r in rutas.values()
            ],
        }
        return "Elige la ruta.\n" + delimitar("datos_ruta", json.dumps(datos, ensure_ascii=False))

    @staticmethod
    def _resumen(ruta: RutaCalculada) -> str:
        estado = "sin retrasos" if ruta.cumple_limites else f"{len(ruta.retrasos)} retraso(s)"
        return (
            f"{NOMBRE_ESTRATEGIA[ruta.estrategia]}: {len(ruta.paradas)} paradas, "
            f"{ruta.km_total:.1f} km, ~{ruta.minutos:.0f} min, {estado}"
        )

    @staticmethod
    def _a_modelo(
        ruta: RutaCalculada, explicacion: str, por_tomar: list[str], sin_capacidad: list[str]
    ) -> RutaRecoleccion:
        return RutaRecoleccion(
            estrategia=ruta.estrategia,
            paradas=[
                ParadaRuta(
                    orden=i,
                    tipo=p.tipo,
                    donativo_id=p.donativo_id,
                    nombre=p.nombre,
                    lat=p.ubicacion.lat,
                    lon=p.ubicacion.lon,
                    llegada=llegada,
                    limite=p.limite,
                    km_tramo=km,
                )
                for i, (p, llegada, km) in enumerate(
                    zip(ruta.paradas, ruta.llegadas, ruta.km_por_tramo, strict=True), 1
                )
            ],
            km_total=ruta.km_total,
            minutos=ruta.minutos,
            cumple_limites=ruta.cumple_limites,
            retrasos=ruta.retrasos,
            explicacion=explicacion,
            por_tomar=por_tomar,
            sin_capacidad=sin_capacidad,
        )
