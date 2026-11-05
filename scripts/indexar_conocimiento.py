"""Construye (o reusa) el índice del RAG con los .md de datos/conocimiento/.

Uso:
    python scripts/indexar_conocimiento.py                      # reusa el índice si no cambió nada
    python scripts/indexar_conocimiento.py --forzar             # lo reconstruye siempre
    python scripts/indexar_conocimiento.py --buscar "leche"     # búsqueda de prueba

DUEÑO: Gilberto (tarea G3).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rescate.config import cargar_configuracion  # noqa: E402
from rescate.llm.cliente import ErrorLLM  # noqa: E402
from rescate.llm.falso import ClienteLLMFalso  # noqa: E402
from rescate.llm.ollama_cliente import ClienteOllama  # noqa: E402
from rescate.rag.base_conocimiento import BaseConocimientoVectorial  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--forzar", action="store_true", help="reconstruye el índice aunque no haya cambios")
    parser.add_argument("--buscar", default="comida caliente", help="consulta de prueba (por defecto: comida caliente)")
    args = parser.parse_args()

    config = cargar_configuracion()
    llm = (
        ClienteLLMFalso()
        if config.usar_llm_falso
        else ClienteOllama(config.modelo, config.modelo_embeddings, config.ollama_url)
    )
    embeddings = "embeddings falsos" if config.usar_llm_falso else config.modelo_embeddings
    try:
        base = BaseConocimientoVectorial.desde_config(config, llm, forzar=args.forzar)
    except ErrorLLM as e:
        sys.exit(f"No se pudo indexar: {e}\n¿Está corriendo Ollama? Revisa con: ollama list")

    accion = "Indexé" if base.reconstruido else "Reusé el índice de"
    print(f"{accion} {len(base.fragmentos)} fragmentos con {embeddings} ({base.motor}) en {config.ruta_indice}")
    print(f'\nBúsqueda de prueba: "{args.buscar}"')
    for f in base.buscar(args.buscar, k=4):
        print(f"  {f.puntaje:.3f}  {f.seccion}  [{f.fuente}]")


if __name__ == "__main__":
    main()
