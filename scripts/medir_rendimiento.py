"""Mide el rendimiento contra las metas de la visión (secciones 7 y 9.3) y escribe docs/rendimiento.md.

Uso (con Streamlit detenido):
    python scripts/medir_rendimiento.py                 # todo, con el perfil del .env
    python scripts/medir_rendimiento.py --corridas 5    # menos corridas de frase → asignación
    python scripts/medir_rendimiento.py --sin-flujo     # sin las corridas con el LLM (equipo sin el modelo)
    python scripts/medir_rendimiento.py --no-guardar    # solo imprime la tabla

Mediciones:
    1. Frase → asignación con el LLM del perfil (media, p95 y máximo; meta ≤ 60 s).
    2. Tablero de impacto con un año de historial (meta ≤ 3 s).
    3. 20 búsquedas del RAG con los embeddings reales (meta ≤ 2 s cada una).
    4. 10 publicaciones simultáneas con el LLM falso (meta: ninguna perdida).

Lo que no se puede medir en el equipo (por ejemplo, sin el modelo descargado) queda como
"pendiente"; nunca se inventa un resultado. Usa bases en memoria: no toca datos/rescate.duckdb.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import statistics
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from pydantic import BaseModel  # noqa: E402

from rescate.config import cargar_configuracion  # noqa: E402
from rescate.contenedor import construir_aplicacion  # noqa: E402
from rescate.dominio.enums import EstadoDonativo, Rol  # noqa: E402
from rescate.dominio.modelos import Actor, Donante, Receptor, Ubicacion, ahora  # noqa: E402
from rescate.llm.cliente import ErrorLLM  # noqa: E402
from rescate.llm.falso import ClienteLLMFalso  # noqa: E402
from rescate.llm.ollama_cliente import ClienteOllama  # noqa: E402

SALIDA = RAIZ / "docs" / "rendimiento.md"
FRASES = RAIZ / "tests" / "frases_interprete.json"
CONSULTAS_RAG = [
    "temperatura de refrigeración de lácteos",
    "alimentos preparados a temperatura ambiente",
    "cuánto tiempo dura la comida cocinada",
    "pan del día anterior",
    "frutas y verduras golpeadas",
    "carne cruda sin refrigerar",
    "leche fuera del refrigerador",
    "recalentar guisados",
    "contaminación cruzada",
    "envases y recipientes limpios",
    "señales de descomposición olor",
    "arroz cocido a temperatura ambiente",
    "huevo y mayonesa",
    "pescado y mariscos",
    "transporte de alimentos en frío",
    "tortillas del día",
    "productos enlatados abollados",
    "alimentos con moho",
    "salsas caseras",
    "lavado de manos y manipulación",
]


@dataclass
class Resultado:
    medicion: str
    meta: str
    resultado: str = "pendiente"
    cumple: str = "pendiente"
    detalle: list[str] = field(default_factory=list)


def p95(valores: list[float]) -> float:
    """Percentil 95 por rango más cercano."""
    orden = sorted(valores)
    return orden[max(0, math.ceil(0.95 * len(orden)) - 1)]


def resumen_tiempos(valores: list[float]) -> str:
    return f"media {statistics.mean(valores):.2f} s · p95 {p95(valores):.2f} s · máx {max(valores):.2f} s"


class Sonda(BaseModel):
    ok: bool


# -------------------------------------------------------------------- mediciones


def medir_flujo(corridas: int) -> Resultado:
    r = Resultado(f"Frase → asignación ({corridas} corridas)", "≤ 60 s por corrida")
    config = cargar_configuracion()
    llm = ClienteOllama(config.modelo, config.modelo_embeddings, config.ollama_url)
    try:
        llm.generar_json('Responde {"ok": true}', Sonda)
    except ErrorLLM as exc:
        r.detalle.append(f"No se midió: el modelo `{config.modelo}` no respondió en este equipo ({exc}).")
        return r
    frases = [f["texto"] for f in json.loads(FRASES.read_text(encoding="utf-8"))["frases"]]
    hoy_17 = datetime.combine(ahora().date(), datetime.min.time()).replace(hour=17)
    app = construir_aplicacion(config=config, llm=llm, ruta_db=":memory:", reloj=lambda: hoy_17)
    donante = next(p for p in app.repos.participantes.donantes())
    actor = Actor(rol=Rol.DONANTE, participante_id=donante.id)
    tiempos, asignados, aclaraciones = [], 0, 0
    for texto in (frases * math.ceil(corridas / len(frases)))[:corridas]:
        inicio = time.perf_counter()
        resultado = app.servicios.publicacion.publicar(actor, texto)
        tiempos.append(time.perf_counter() - inicio)
        if not resultado.completo:
            aclaraciones += 1
        elif resultado.donativo.estado == EstadoDonativo.ASIGNADO:
            asignados += 1
    r.resultado = resumen_tiempos(tiempos)
    r.cumple = "sí" if max(tiempos) <= 60 else f"no ({sum(t > 60 for t in tiempos)} sobre 60 s)"
    r.detalle.append(
        f"Modelo `{config.modelo}` (perfil `{config.perfil}`); {asignados} asignados y "
        f"{aclaraciones} que pidieron aclaración. Frases de `tests/frases_interprete.json`."
    )
    return r


def medir_tablero(repeticiones: int = 5) -> Resultado:
    from rescate.semilla import cargar_semilla
    from scripts.generar_historial import cargar_historial

    r = Resultado("Tablero de impacto con un año de historial", "≤ 3 s")
    config = cargar_configuracion()
    app = construir_aplicacion(
        config=config, llm=ClienteLLMFalso(), ruta_db=":memory:", cargar_datos_semilla=False
    )
    cargar_semilla(app.repos.participantes, config.ruta_semilla)
    total = cargar_historial(app.repos.donativos._con, app.repos.participantes, app.repos.donativos)
    coordinador = Actor(rol=Rol.COORDINADOR)
    hoy = ahora().date()
    tiempos = []
    for _ in range(repeticiones):
        inicio = time.perf_counter()
        app.servicios.reportes.tablero(coordinador, hoy - timedelta(days=365), hoy)
        tiempos.append(time.perf_counter() - inicio)
    r.resultado = f"máx {max(tiempos):.3f} s ({repeticiones} repeticiones)"
    r.cumple = "sí" if max(tiempos) <= 3 else "no"
    r.detalle.append(
        f"{total} donativos entregados generados con `scripts/generar_historial.py` (semilla 42)."
    )
    return r


def medir_rag() -> Resultado:
    from rescate.rag.base_conocimiento import BaseConocimientoVectorial

    r = Resultado(f"Búsqueda en el RAG ({len(CONSULTAS_RAG)} consultas)", "≤ 2 s por consulta")
    config = cargar_configuracion()
    llm = ClienteOllama(config.modelo, config.modelo_embeddings, config.ollama_url)
    try:
        inicio = time.perf_counter()
        base = BaseConocimientoVectorial.desde_config(config, llm)
        preparar = time.perf_counter() - inicio
        tiempos = []
        for consulta in CONSULTAS_RAG:
            inicio = time.perf_counter()
            base.buscar(consulta)
            tiempos.append(time.perf_counter() - inicio)
    except ErrorLLM as exc:
        r.detalle.append(f"No se midió: los embeddings `{config.modelo_embeddings}` no respondieron ({exc}).")
        return r
    r.resultado = resumen_tiempos(tiempos)
    r.cumple = "sí" if max(tiempos) <= 2 else "no"
    r.detalle.append(
        f"Embeddings `{config.modelo_embeddings}` en Ollama; cargar o construir el índice tomó {preparar:.1f} s "
        "(no cuenta en la meta, se hace una vez al arrancar)."
    )
    return r


def medir_concurrencia(hilos: int = 10) -> Resultado:
    r = Resultado(f"{hilos} publicaciones simultáneas (LLM falso)", "ninguna perdida")
    app = construir_aplicacion(llm=ClienteLLMFalso(), ruta_db=":memory:", cargar_datos_semilla=False)
    coordinador = Actor(rol=Rol.COORDINADOR)
    centro = Ubicacion(lat=20.6741, lon=-103.3404)
    app.servicios.participantes.registrar(
        coordinador, Donante(id="don-carga", nombre="Fonda", ubicacion=centro)
    )
    app.servicios.participantes.registrar(
        coordinador, Receptor(id="rec-carga", nombre="Comedor", ubicacion=centro)
    )
    actor = Actor(rol=Rol.DONANTE, participante_id="don-carga")
    barrera, ids, errores = threading.Barrier(hilos), [], []

    def publicar(numero: int) -> None:
        barrera.wait()
        try:
            ids.append(app.servicios.publicacion.publicar(actor, f"{numero + 10} bolillos").donativo_id)
        except Exception as exc:  # noqa: BLE001 - se reporta en el resultado
            errores.append(str(exc))

    inicio = time.perf_counter()
    trabajadores = [threading.Thread(target=publicar, args=(i,)) for i in range(hilos)]
    for t in trabajadores:
        t.start()
    for t in trabajadores:
        t.join()
    duracion = time.perf_counter() - inicio
    guardados = {d.id for d in app.repos.donativos.listar()}
    perdidos = hilos - len(guardados & set(ids))
    r.resultado = f"{len(guardados)} guardados de {hilos}, {perdidos} perdidos, {len(errores)} errores ({duracion:.2f} s)"
    r.cumple = "sí" if perdidos == 0 and not errores and len(set(ids)) == hilos else "no"
    r.detalle.append("Las publicaciones se atienden una por una (candado de `ServicioPublicacion`).")
    return r


# --------------------------------------------------------------------- reporte


def tabla(resultados: list[Resultado]) -> str:
    filas = ["| Medición | Meta | Resultado | Cumple |", "| --- | --- | --- | --- |"]
    filas += [f"| {r.medicion} | {r.meta} | {r.resultado} | {r.cumple} |" for r in resultados]
    return "\n".join(filas)


def documento(resultados: list[Resultado]) -> str:
    config = cargar_configuracion()
    equipo = f"{platform.system()} {platform.release()}, {os.cpu_count()} núcleos, Python {platform.python_version()}"
    notas = "\n".join(f"- **{r.medicion}:** {d}" for r in resultados for d in r.detalle)
    return f"""# Rendimiento

Resultados de `python scripts/medir_rendimiento.py` contra las metas de la visión (secciones 7 y 9.3).
Este archivo lo escribe el script; no se edita a mano.

- Fecha: {ahora():%d/%m/%Y %H:%M}
- Equipo: {equipo}
- Perfil del `.env`: `{config.perfil}` (modelo `{config.modelo}`, embeddings `{config.modelo_embeddings}`)

{tabla(resultados)}

## Notas

{notas}
"""


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--corridas", type=int, default=20, help="corridas de frase → asignación (por defecto 20)"
    )
    parser.add_argument("--sin-flujo", action="store_true", help="no mide las corridas con el LLM")
    parser.add_argument("--no-guardar", action="store_true", help="no escribe docs/rendimiento.md")
    args = parser.parse_args()

    flujo = Resultado(f"Frase → asignación ({args.corridas} corridas)", "≤ 60 s por corrida")
    if args.sin_flujo:
        flujo.detalle.append("No se midió en este equipo (`--sin-flujo`): se corre en la PC de integración.")
    else:
        flujo = medir_flujo(args.corridas)
    resultados = [flujo, medir_tablero(), medir_rag(), medir_concurrencia()]
    print(tabla(resultados))
    if not args.no_guardar:
        SALIDA.write_text(documento(resultados), encoding="utf-8")
        print(f"\nGuardado en {SALIDA}")


if __name__ == "__main__":
    main()
