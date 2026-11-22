"""Genera un año de donativos ENTREGADOS para el tablero de impacto y el Predictor.

Uso (con Streamlit detenido):
    python scripts/generar_historial.py                 # 12 meses que terminan hace 8 días
    python scripts/generar_historial.py --semilla 7     # otra secuencia aleatoria
    python scripts/generar_historial.py --borrar        # quita todo lo generado (ids hist-...)
    python scripts/generar_historial.py --caso-vencido  # además, un ASIGNADO con el plazo vencido

Patrones (los detecta el Predictor):
    don-lupe    guisados preparados de lunes a jueves, 2 a 4 kg
    pan-espiga  pan dulce y bolillo martes y viernes, 25 a 35 piezas
    fru-guero   frutas y verduras los sábados, 5 a 10 kg
    tac-corona  preparados los domingos, 2 a 3 kg
    resto       donativos esporádicos

El historial termina hace 8 días para no alterar la capacidad de hoy ni la equidad de la semana.
Cada corrida borra lo generado antes y lo vuelve a crear (misma semilla = mismos datos).
"""
from __future__ import annotations

import argparse
import random
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rescate.dominio.enums import Dictamen, EstadoDonativo, TipoAlimento  # noqa: E402
from rescate.dominio.modelos import (  # noqa: E402
    Alimento,
    Asignacion,
    DictamenInocuidad,
    Donante,
    Donativo,
    Receptor,
    Recolector,
    ahora,
)
from rescate.herramientas.compatibilidad import evaluar_compatibilidad  # noqa: E402
from rescate.herramientas.geo import haversine_km  # noqa: E402

PREFIJO = "hist-"
ID_VENCIDO = "hist-vencido"
DIAS_DE_HISTORIA = 365
DIAS_SIN_HISTORIA = 8
KG_POR_PIEZA_PAN = 0.07  # el mismo que usa el Intérprete para panadería

E = EstadoDonativo
TRANSICIONES = [  # (anterior, nuevo, evento, minutos después de publicar)
    (None, E.PUBLICADO, "publicar", 0),
    (E.PUBLICADO, E.EVALUADO, "evaluar_apto", 1),
    (E.EVALUADO, E.ASIGNADO, "asignar", 2),
    (E.ASIGNADO, E.ASIGNADO, "aceptar", 15),
    (E.ASIGNADO, E.EN_RECOLECCION, "iniciar_recoleccion", 40),
    (E.EN_RECOLECCION, E.ENTREGADO, "entregar", 95),
]


@dataclass
class Patron:
    dias: set[int]  # 0 = lunes
    probabilidad: float
    alimentos: list[tuple[str, TipoAlimento]]
    kg: tuple[float, float] = (0, 0)
    piezas: tuple[int, int] = (0, 0)
    requiere_frio: bool = False
    extras: list[str] = field(default_factory=list)


PATRONES: dict[str, Patron] = {
    "don-lupe": Patron(
        {0, 1, 2, 3},
        0.9,
        [("guisado de pollo en mole", TipoAlimento.PREPARADO), ("arroz rojo", TipoAlimento.PREPARADO),
         ("frijoles charros", TipoAlimento.PREPARADO), ("picadillo", TipoAlimento.PREPARADO)],
        kg=(2, 4),
    ),
    "pan-espiga": Patron(
        {1, 4}, 0.9, [("pan dulce", TipoAlimento.PANADERIA), ("bolillo", TipoAlimento.PANADERIA)], piezas=(25, 35)
    ),
    "fru-guero": Patron(
        {5},
        0.9,
        [("jitomate", TipoAlimento.FRUTA_VERDURA), ("plátano", TipoAlimento.FRUTA_VERDURA),
         ("papaya", TipoAlimento.FRUTA_VERDURA)],
        kg=(5, 10),
    ),
    "tac-corona": Patron(
        {6}, 0.85, [("frijoles refritos", TipoAlimento.PREPARADO), ("guisado de res", TipoAlimento.PREPARADO)],
        kg=(2, 3),
    ),
}
ESPORADICOS: dict[str, Patron] = {
    "cre-santatere": Patron(set(range(7)), 0.06, [("yogur", TipoAlimento.LACTEO), ("queso fresco", TipoAlimento.LACTEO)],
                            kg=(1, 3), requiere_frio=True),
    "pan-tlaque": Patron(set(range(7)), 0.08, [("bolillo", TipoAlimento.PANADERIA), ("concha", TipoAlimento.PANADERIA)],
                         piezas=(10, 25)),
    "coc-zapopan": Patron(set(range(7)), 0.08, [("caldo de pollo", TipoAlimento.PREPARADO),
                                                ("sopa de fideo", TipoAlimento.PREPARADO)], kg=(2, 5)),
}


@dataclass
class Generado:
    donativo: Donativo
    historial: list[tuple[EstadoDonativo | None, EstadoDonativo, str, str, datetime]]


def _hora_publicacion(donante: Donante, dia: date, azar: random.Random) -> datetime:
    try:
        cierre = time.fromisoformat(donante.hora_cierre)
    except ValueError:
        cierre = time(18, 0)
    base = datetime.combine(dia, cierre) - timedelta(minutes=azar.randint(30, 90))
    return base.replace(second=0, microsecond=0)


def _alimentos(patron: Patron, azar: random.Random) -> list[Alimento]:
    if patron.piezas != (0, 0):  # pan: piezas repartidas entre dos nombres
        total = azar.randint(*patron.piezas)
        primero = azar.randint(total // 3, 2 * total // 3)
        partes = [(patron.alimentos[0], primero), (patron.alimentos[1], total - primero)]
        return [
            Alimento(nombre=n, cantidad=c, unidad="pieza", tipo=t, kg_estimados=round(c * KG_POR_PIEZA_PAN, 2))
            for (n, t), c in partes
            if c > 0
        ]
    nombres = azar.sample(patron.alimentos, k=min(2, len(patron.alimentos)))
    kg_total = round(azar.uniform(*patron.kg), 1)
    kg_primero = round(kg_total * azar.uniform(0.4, 0.7), 1)
    partes = [(nombres[0], kg_primero), (nombres[1], round(kg_total - kg_primero, 1))]
    return [
        Alimento(nombre=n, cantidad=kg, unidad="kg", tipo=t, kg_estimados=kg)
        for (n, t), kg in partes
        if kg > 0
    ]


def _elegir_receptor(donativo: Donativo, donante: Donante, receptores: list[Receptor], azar: random.Random):
    """Un receptor compatible, con más probabilidad mientras más cerca esté."""
    compatibles = [r for r in receptores if evaluar_compatibilidad(donativo, r).compatible]
    if not compatibles:
        return None
    pesos = [1 / (haversine_km(donante.ubicacion, r.ubicacion) + 0.5) for r in compatibles]
    return azar.choices(compatibles, weights=pesos, k=1)[0]


def generar_donativos(
    donantes: list[Donante],
    receptores: list[Receptor],
    recolectores: list[Recolector],
    fin: date,
    semilla: int = 42,
    dias: int = DIAS_DE_HISTORIA,
) -> list[Generado]:
    """Donativos ENTREGADOS de `fin - dias` a `fin` (incluido), con su historial de estados."""
    azar = random.Random(semilla)
    por_id = {d.id: d for d in donantes}
    patrones = {**PATRONES, **ESPORADICOS}
    generados = []
    for desplazamiento in range(dias, -1, -1):
        dia = fin - timedelta(days=desplazamiento)
        for donante_id, patron in patrones.items():
            donante = por_id.get(donante_id)
            if donante is None or dia.weekday() not in patron.dias or azar.random() > patron.probabilidad:
                continue
            publicado = _hora_publicacion(donante, dia, azar)
            donativo = Donativo(
                id=f"{PREFIJO}{dia:%Y%m%d}-{donante_id}",
                donante_id=donante_id,
                texto_original="(historial simulado)",
                alimentos=_alimentos(patron, azar),
                hora_preparacion=publicado - timedelta(hours=3),
                creado=publicado,
                dictamen=DictamenInocuidad(
                    dictamen=Dictamen.APTO_CON_CONDICIONES if patron.requiere_frio else Dictamen.APTO,
                    motivo="Historial simulado",
                    condiciones=["Mantener en refrigeración (≤ 4 °C)"] if patron.requiere_frio else [],
                    requiere_refrigeracion=patron.requiere_frio,
                ),
            )
            receptor = _elegir_receptor(donativo, donante, receptores, azar)
            if receptor is None or not recolectores:
                continue
            momento = {m: publicado + timedelta(minutes=m) for *_, m in TRANSICIONES}
            donativo.asignacion = Asignacion(
                receptor_id=receptor.id,
                puntaje=0.0,
                justificacion=f"Historial simulado: el más cercano compatible fue {receptor.nombre}",
                aceptada=True,
                fecha=momento[2],
            )
            donativo.recolector_id = azar.choice(recolectores).id
            donativo.estado = EstadoDonativo.ENTREGADO
            donativo.actualizado = momento[95]
            historial = [(a, n, ev, "Historial simulado", momento[m]) for a, n, ev, m in TRANSICIONES]
            generados.append(Generado(donativo, historial))
    return generados


def caso_vencido(donantes: list[Donante], receptores: list[Receptor], momento: datetime) -> Generado | None:
    """Un donativo ASIGNADO, sin aceptar y con el plazo vencido: expira al abrir la coordinación."""
    donante = next((d for d in donantes if d.id == "coc-zapopan"), donantes[0] if donantes else None)
    if donante is None or not receptores:
        return None
    publicado = momento - timedelta(hours=3)
    donativo = Donativo(
        id=ID_VENCIDO,
        donante_id=donante.id,
        texto_original="3 kg de caldo de pollo",
        alimentos=[Alimento(nombre="caldo de pollo", cantidad=3, unidad="kg", tipo=TipoAlimento.PREPARADO,
                            kg_estimados=3)],
        hora_preparacion=publicado - timedelta(hours=1),
        recoger_antes_de=momento - timedelta(minutes=30),
        creado=publicado,
        actualizado=publicado + timedelta(minutes=2),
        estado=EstadoDonativo.ASIGNADO,
        dictamen=DictamenInocuidad(dictamen=Dictamen.APTO, motivo="Caldo recién hecho"),
    )
    receptor = next((r for r in receptores if evaluar_compatibilidad(donativo, r).compatible), None)
    if receptor is None:
        return None
    donativo.asignacion = Asignacion(receptor_id=receptor.id, justificacion="Asignación de demostración",
                                     fecha=publicado + timedelta(minutes=2))
    historial = [(a, n, ev, "Demostración de caso vencido", publicado + timedelta(minutes=m))
                 for a, n, ev, m in TRANSICIONES[:3]]
    return Generado(donativo, historial)


# ------------------------------------------------------------------- base


def borrar(con) -> int:
    total = con.execute("SELECT count(*) FROM donativos WHERE id LIKE ?", [f"{PREFIJO}%"]).fetchone()[0]
    con.execute("DELETE FROM historial_estados WHERE donativo_id LIKE ?", [f"{PREFIJO}%"])
    con.execute("DELETE FROM donativos WHERE id LIKE ?", [f"{PREFIJO}%"])
    return total


def guardar(con, repo_donativos, generados: list[Generado]) -> None:
    """Escribe con el repositorio; el historial va por SQL para conservar las fechas del pasado."""
    for g in generados:
        repo_donativos.guardar(g.donativo)
        con.executemany(
            "INSERT INTO historial_estados VALUES (?, ?, ?, ?, ?, ?)",
            [
                [g.donativo.id, a.value if a else None, n.value, evento, motivo, fecha]
                for a, n, evento, motivo, fecha in g.historial
            ],
        )


def cargar_historial(con, participantes, donativos, semilla: int = 42, con_caso_vencido: bool = False,
                     hoy: date | None = None) -> int:
    """Borra lo generado antes y genera el año de historial. Regresa cuántos donativos creó."""
    hoy = hoy or ahora().date()
    borrar(con)
    generados = generar_donativos(
        participantes.donantes(),
        participantes.receptores(),
        participantes.recolectores(),
        fin=hoy - timedelta(days=DIAS_SIN_HISTORIA),
        semilla=semilla,
    )
    if con_caso_vencido:
        vencido = caso_vencido(participantes.donantes(), participantes.receptores(), ahora())
        if vencido:
            generados.append(vencido)
    guardar(con, donativos, generados)
    return len(generados)


def main() -> None:
    from rescate.config import cargar_configuracion
    from rescate.persistencia.db import conectar
    from rescate.persistencia.repositorios import DonativosDuckDB, ParticipantesDuckDB
    from rescate.semilla import cargar_semilla

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--semilla", type=int, default=42, help="semilla del azar (por defecto 42)")
    parser.add_argument("--borrar", action="store_true", help="solo borra lo generado (ids hist-...)")
    parser.add_argument("--caso-vencido", action="store_true", help="agrega un ASIGNADO con el plazo vencido")
    args = parser.parse_args()

    config = cargar_configuracion()
    con = conectar(config.ruta_db)
    participantes, donativos = ParticipantesDuckDB(con), DonativosDuckDB(con)
    if args.borrar:
        print(f"{borrar(con)} donativos del historial borrados de {config.ruta_db}")
        con.close()
        return
    if participantes.vacio():
        cargar_semilla(participantes, config.ruta_semilla)
    total = cargar_historial(con, participantes, donativos, args.semilla, args.caso_vencido)
    con.close()
    print(f"{total} donativos de historial cargados en {config.ruta_db}")


if __name__ == "__main__":
    main()
