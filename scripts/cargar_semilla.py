"""Carga (o recarga) los datos de demostración en la base.

Uso:
    python scripts/cargar_semilla.py              # agrega/actualiza participantes
    python scripts/cargar_semilla.py --reiniciar  # borra la base y empieza de cero

DUEÑO: Alejandro (tarea A1).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rescate.config import cargar_configuracion  # noqa: E402
from rescate.persistencia.db import conectar  # noqa: E402
from rescate.persistencia.repositorios import ParticipantesDuckDB  # noqa: E402
from rescate.semilla import cargar_semilla  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reiniciar", action="store_true", help="borra la base antes de cargar")
    args = parser.parse_args()

    config = cargar_configuracion()
    if args.reiniciar and Path(config.ruta_db).exists():
        Path(config.ruta_db).unlink()
        print(f"Base borrada: {config.ruta_db}")
    con = conectar(config.ruta_db)
    total = cargar_semilla(ParticipantesDuckDB(con), config.ruta_semilla)
    con.close()
    print(f"{total} participantes cargados en {config.ruta_db}")


if __name__ == "__main__":
    main()
