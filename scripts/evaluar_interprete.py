"""Mide qué tan bien interpreta el Agente Intérprete las frases de tests/frases_interprete.json.

Uso:
    python scripts/evaluar_interprete.py             # con el LLM configurado en .env
    python scripts/evaluar_interprete.py --reglas    # solo el respaldo de reglas, sin LLM
    python scripts/evaluar_interprete.py --detalle   # también muestra los campos acertados

Califica, por frase: si quedó completo, cuántos alimentos encontró y, por cada alimento
esperado, si lo identificó, su cantidad, unidad, tipo y conservación, y la hora de
preparación. La meta del documento de visión es 90 % de campos correctos.

DUEÑO: Gilberto (flujo 1).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from rescate.agentes.interprete import AgenteInterprete  # noqa: E402
from rescate.bitacora import Bitacora  # noqa: E402
from rescate.config import cargar_configuracion  # noqa: E402
from rescate.dominio.modelos import (  # noqa: E402
    Donante,
    ResultadoInterpretacion,
    SolicitudInterpretacion,
    Ubicacion,
)
from rescate.llm.cliente import ClienteLLM  # noqa: E402
from rescate.llm.falso import ClienteLLMFalso  # noqa: E402
from rescate.llm.ollama_cliente import ClienteOllama  # noqa: E402
from rescate.persistencia.db import conectar  # noqa: E402
from rescate.persistencia.repositorios import BitacoraDuckDB  # noqa: E402

RUTA_FRASES = RAIZ / "tests" / "frases_interprete.json"
META = 0.90
FECHA = datetime(2026, 11, 5)  # fecha fija: las horas esperadas no dependen del día real

Campo = tuple[str, bool, str]  # (nombre del campo, acertó, lo que se obtuvo)


def normalizar(texto: str) -> str:
    sin_acentos = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sin_acentos.lower()


def coincide(valor: str, esperado: str | list[str]) -> bool:
    return valor in (esperado if isinstance(esperado, list) else [esperado])


def calificar(resultado: ResultadoInterpretacion, esperado: dict) -> list[Campo]:
    """Compara campo por campo el resultado del agente con la respuesta esperada."""
    campos: list[Campo] = [
        ("completo", resultado.completo == esperado["completo"], str(resultado.completo)),
        (
            "número de alimentos",
            len(resultado.alimentos) == len(esperado["alimentos"]),
            str(len(resultado.alimentos)),
        ),
    ]
    usados: set[int] = set()
    for e in esperado["alimentos"]:
        nombres = [normalizar(n) for n in e["nombre"]]
        indice = next(
            (
                i
                for i, a in enumerate(resultado.alimentos)
                if i not in usados and any(n in normalizar(a.nombre) for n in nombres)
            ),
            None,
        )
        etiqueta = e["nombre"][0]
        evaluables = [k for k in ("cantidad", "unidad", "tipo", "conservacion") if k in e]
        if indice is None:
            campos.append((f"{etiqueta}: identificado", False, "no aparece"))
            campos.extend((f"{etiqueta}: {k}", False, "—") for k in evaluables)
            continue
        usados.add(indice)
        a = resultado.alimentos[indice]
        campos.append((f"{etiqueta}: identificado", True, a.nombre))
        obtenido = {
            "cantidad": (abs(a.cantidad - e.get("cantidad", 0)) < 1e-6, f"{a.cantidad:g}"),
            "unidad": (coincide(a.unidad, e.get("unidad", "")), a.unidad),
            "tipo": (coincide(a.tipo.value, e.get("tipo", "")), a.tipo.value),
            "conservacion": (coincide(a.conservacion.value, e.get("conservacion", "")), a.conservacion.value),
        }
        campos.extend((f"{etiqueta}: {k}", *obtenido[k]) for k in evaluables)
    if "hora_preparacion" in esperado:
        hora = resultado.hora_preparacion.strftime("%H:%M") if resultado.hora_preparacion else None
        campos.append(("hora de preparación", hora == esperado["hora_preparacion"], str(hora)))
    return campos


def cargar_frases(ruta: Path = RUTA_FRASES) -> dict:
    return json.loads(ruta.read_text(encoding="utf-8"))


def evaluar(llm: ClienteLLM, datos: dict) -> tuple[int, int, list[dict]]:
    """Corre el agente sobre cada frase. Devuelve (aciertos, campos evaluados, detalle por frase)."""
    horas, minutos = map(int, datos["hora_actual"].split(":"))
    momento = FECHA.replace(hour=horas, minute=minutos)
    agente = AgenteInterprete(llm, Bitacora(BitacoraDuckDB(conectar(":memory:"))), reloj=lambda: momento)
    filas = []
    for i, frase in enumerate(datos["frases"], 1):
        donante = Donante(
            id="don-evaluacion",
            nombre="Comercio de prueba",
            ubicacion=Ubicacion(lat=20.67, lon=-103.34),
            tipo_comercio=frase.get("comercio", "fonda"),
            hora_cierre=frase.get("hora_cierre", "18:00"),
        )
        inicio = time.time()
        resultado = agente.ejecutar(
            SolicitudInterpretacion(texto=frase["texto"], donante=donante, donativo_id=f"frase-{i}")
        )
        campos = calificar(resultado, frase["esperado"])
        filas.append({"texto": frase["texto"], "campos": campos, "segundos": time.time() - inicio})
    aciertos = sum(ok for fila in filas for _, ok, _ in fila["campos"])
    total = sum(len(fila["campos"]) for fila in filas)
    return aciertos, total, filas


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--reglas", action="store_true", help="evalúa solo el respaldo de reglas (sin LLM)")
    parser.add_argument("--detalle", action="store_true", help="muestra también los campos acertados")
    args = parser.parse_args()

    config = cargar_configuracion()
    if args.reglas or config.usar_llm_falso:
        llm: ClienteLLM = ClienteLLMFalso()
        nombre = "reglas de respaldo (sin LLM)"
    else:
        llm = ClienteOllama(config.modelo, config.modelo_embeddings, config.ollama_url)
        nombre = config.modelo
    datos = cargar_frases()
    print(
        f"Agente Intérprete con {nombre} · {len(datos['frases'])} frases · hora fija {datos['hora_actual']}\n"
    )

    aciertos, total, filas = evaluar(llm, datos)
    for fila in filas:
        buenos = sum(ok for _, ok, _ in fila["campos"])
        marca = "✔" if buenos == len(fila["campos"]) else "✘"
        texto = fila["texto"].replace("\n", " / ")
        print(f"{marca} {buenos:>2}/{len(fila['campos']):<2} {texto[:75]} ({fila['segundos']:.1f} s)")
        for campo, ok, obtenido in fila["campos"]:
            if not ok or args.detalle:
                print(f"       {'✔' if ok else '✘'} {campo}: {obtenido}")

    porcentaje = aciertos / total
    perfectas = sum(all(ok for _, ok, _ in f["campos"]) for f in filas)
    veredicto = "cumple" if porcentaje >= META else "no cumple"
    print(
        f"\nCampos correctos: {aciertos}/{total} = {porcentaje:.1%} (meta de la visión: {META:.0%}, {veredicto})"
    )
    print(f"Frases sin ningún error: {perfectas}/{len(filas)}")


if __name__ == "__main__":
    main()
